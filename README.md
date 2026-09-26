# CS 528 HW2 - Graph Analysis on Google Cloud Storage

This project reads 12,000 generated HTML pages from the public Google Cloud Storage bucket `cloud_hw2_bucket` (prefix `pages/`). It builds a directed graph without a graph library, reports incoming and outgoing link statistics, computes iterative PageRank, and finds the page with the highest closeness centrality.

The Google Cloud project is `quick-formula-457319-q3`. The bucket is located in `us-central1`.

## Install

Python 3.10 or newer is required. In a fresh clone:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

The bucket is public for object reads. The default path uses Application Default Credentials when available and falls back to an anonymous Cloud Storage client when they are absent. The `--public-http` path lists and reads public objects without credentials. No graph package is required.

## Run

```bash
python3 hw2.py --bucket cloud_hw2_bucket
```

Parameters:

- `--bucket`: Cloud Storage bucket name; defaults to `cloud_hw2_bucket`.
- `--prefix`: object-name prefix containing the HTML pages; defaults to `pages/`.
- `--skip-closeness`: omit the most CPU-intensive graph calculation for a quick preliminary check. Do not use this flag for the complete assignment run.
- `--public-http`: list objects through the public Cloud Storage JSON API, then read each public object through a fresh HTTPS connection. This single-threaded path avoids the Cloud Storage client's persistent-connection read timeouts seen in Cloud Shell. The graph calculations and output are identical.
- `--checkpoint PATH`: with `--public-http`, atomically save the parsed graph every 100 new pages to `PATH` and automatically resume from it on the next run. Use a path in Cloud Shell's persistent home directory.

To open an interactive Cloud Shell session from your laptop terminal, use the instructor-recommended connection command:

```bash
gcloud cloud-shell ssh --authorize-session --ssh-flag="-o ServerAliveInterval=60"
```

At the resulting Cloud Shell prompt, enter the cloned repository and run the Python commands below. The `gcloud` command opens the remote shell; `hw2.py` executes inside Cloud Shell. The 60-second SSH keepalive helps sustain the connection during a long run, while the checkpoint allows recovery if it is interrupted.

If a default download times out in Cloud Shell, run the complete calculation with:

```bash
python3 hw2.py --bucket cloud_hw2_bucket --public-http
```

For a long Cloud Shell run that may be interrupted, use this exact command. Run the **same command again** after reopening Cloud Shell; it skips pages already saved in the checkpoint:

```bash
python3 hw2.py --bucket cloud_hw2_bucket --public-http --checkpoint "$HOME/hw2-cloudshell-checkpoint.pkl"
```

The checkpoint remains in Cloud Shell's home directory and contains the parsed graph and cumulative successful graph-loading time. The timing summary labels the resumed loading and total times; it also reports the current invocation's wall time. Work performed after the last saved checkpoint in an interrupted session is excluded from the cumulative figure.

The program prints page and link counts, average/median/min/max/20th/40th/60th/80th percentiles of link degrees, the five highest PageRank pages, the best closeness page, and a timing summary for each stage. Times are wall-clock seconds measured by `time.perf_counter()`.

## Tests

```bash
python3 -m unittest -v test_hw2.py
```

The tests use small hand-built graphs and do not depend on the generated 12,000-page dataset or a Google Cloud connection.

## Dataset and method

`generator.py` is the provided page generator. To regenerate the local dataset, run it in an empty `pages/` directory with `python3 ../generator.py -n 12000 -m 325`. The 12,000 generated HTML files are stored in `gs://cloud_hw2_bucket/pages/`; they are excluded from Git because they are large and publicly readable from the bucket.

The graph is directed: a link from page A to page B contributes one outgoing link to A and one incoming link to B. Duplicate HTML links count as separate links for degree statistics and PageRank, as in the source files. PageRank starts at `1/N` for each page and uses damping 0.85. Iteration stops when both the total-rank change and normalized sum of individual page-rank changes are at most 0.5%; the second check avoids stopping after one iteration merely because rank mass is conserved. Closeness uses exact outgoing shortest-path distances, with integer bitsets to accelerate breadth-first search while remaining single-threaded. A page that cannot reach every other page receives closeness score zero.

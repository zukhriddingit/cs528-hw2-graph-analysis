from google.cloud import storage
from google.auth.exceptions import DefaultCredentialsError
import argparse
import os
import pickle
import re
import statistics
import tempfile
import time
import urllib.error
import urllib.request


LINK_PATTERN = re.compile(r'HREF="(\d+)\.html"', re.IGNORECASE)


def get_storage_client():
    try:
        return storage.Client()
    except DefaultCredentialsError:
        return storage.Client.create_anonymous_client()


def download_public_blob(blob):
    """Read a public object with a fresh HTTP connection and bounded retries."""
    for attempt in range(5):
        try:
            with urllib.request.urlopen(blob.public_url, timeout=30) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 4:
                raise
            time.sleep(min(2 ** attempt, 8))


def save_graph_checkpoint(path, bucket_name, prefix, graph, load_seconds,
                          complete=False):
    """Atomically save completed downloads and their cumulative load time."""
    path = os.path.expanduser(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    state = {
        "version": 1,
        "bucket": bucket_name,
        "prefix": prefix,
        "graph": graph,
        "load_seconds": load_seconds,
        "complete": complete,
    }
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".hw2-checkpoint-", suffix=".tmp",
            dir=directory, delete=False
        ) as handle:
            temp_path = handle.name
            pickle.dump(state, handle, protocol=pickle.HIGHEST_PROTOCOL)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and os.path.exists(temp_path):
            os.unlink(temp_path)


def load_graph(bucket_name, prefix="pages/", public_http=False,
               checkpoint_path=None, checkpoint_every=500, progress=None):
    if checkpoint_path and not public_http:
        raise ValueError("Checkpointing requires --public-http.")
    if checkpoint_every <= 0:
        raise ValueError("checkpoint_every must be positive.")

    run_start = time.perf_counter()
    prior_load_seconds = 0.0
    graph = {}
    complete = False
    if checkpoint_path and os.path.exists(os.path.expanduser(checkpoint_path)):
        with open(os.path.expanduser(checkpoint_path), "rb") as handle:
            state = pickle.load(handle)
        if (state.get("version") != 1 or state.get("bucket") != bucket_name
                or state.get("prefix") != prefix):
            raise ValueError("Checkpoint does not match this bucket/prefix.")
        graph = state["graph"]
        prior_load_seconds = state["load_seconds"]
        complete = state.get("complete", False)
        print(f"Resuming from checkpoint: {len(graph)} files loaded.")

    resumed_files = len(graph)
    if progress is not None:
        progress["resumed_files"] = resumed_files

    if complete:
        if progress is not None:
            progress["load_seconds"] = prior_load_seconds
        return graph

    client = get_storage_client()
    new_files = 0

    for blob in client.list_blobs(bucket_name, prefix=prefix):
        if not blob.name.endswith(".html"):
            continue

        filename = blob.name.rsplit("/", 1)[-1]
        page_id = int(filename.removesuffix(".html"))
        if page_id in graph:
            continue

        if public_http:
            html = download_public_blob(blob)
        else:
            html = blob.download_as_text(encoding="utf-8")
        links = [int(x) for x in LINK_PATTERN.findall(html)]

        graph[page_id] = links
        new_files += 1
        count = len(graph)

        if count % 500 == 0:
            print(f"Loaded {count} files...")

        if checkpoint_path and new_files % checkpoint_every == 0:
            save_graph_checkpoint(
                checkpoint_path, bucket_name, prefix, graph,
                prior_load_seconds + time.perf_counter() - run_start
            )

    if checkpoint_path:
        load_seconds = prior_load_seconds + time.perf_counter() - run_start
        save_graph_checkpoint(
            checkpoint_path, bucket_name, prefix, graph, load_seconds,
            complete=True
        )
        if progress is not None:
            progress["load_seconds"] = load_seconds

    return graph


def summarize(values):
    quintiles = statistics.quantiles(values, n=5, method="inclusive")

    return {
        "average": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "q20": quintiles[0],
        "q40": quintiles[1],
        "q60": quintiles[2],
        "q80": quintiles[3],
    }


def compute_degree_stats(graph):
    incoming = {node: 0 for node in graph}
    outgoing = {node: len(graph[node]) for node in graph}

    for source in graph:
        for target in graph[source]:
            if target in incoming:
                incoming[target] += 1

    incoming_stats = summarize(list(incoming.values()))
    outgoing_stats = summarize(list(outgoing.values()))

    return incoming_stats, outgoing_stats


def pagerank(
    graph,
    damping=0.85,
    tolerance=0.005,
    max_iterations=1000,
    verbose=True
):
    nodes = list(graph)
    n = len(nodes)

    if n == 0:
        return {}, 0

    pr = {node: 1.0 / n for node in nodes}

    for iteration in range(1, max_iterations + 1):
        new_pr = {
            node: (1.0 - damping) / n
            for node in nodes
        }

        for source, targets in graph.items():
            out_degree = len(targets)

            if out_degree == 0:
                continue

            contribution = (
                damping * pr[source] / out_degree
            )

            for target in targets:
                if target in new_pr:
                    new_pr[target] += contribution

        old_sum = sum(pr.values())
        new_sum = sum(new_pr.values())

        if old_sum == 0:
            percent_change = 0
            rank_movement = sum(abs(new_pr[node] - pr[node]) for node in nodes)
        else:
            percent_change = abs(new_sum - old_sum) / old_sum
            rank_movement = (
                sum(abs(new_pr[node] - pr[node]) for node in nodes) / old_sum
            )

        pr = new_pr

        if verbose:
            print(
                f"PageRank iteration {iteration}: "
                f"sum={new_sum:.10f}, "
                f"sum change={percent_change * 100:.4f}%, "
                f"rank movement={rank_movement * 100:.4f}%"
            )

        if percent_change <= tolerance and rank_movement <= tolerance:
            return pr, iteration

    return pr, max_iterations


def closeness_centrality(graph, verbose=True):
    nodes = list(graph)
    n = len(nodes)

    if n == 0:
        return {}, None, 0.0

    if n == 1:
        return {nodes[0]: 0.0}, nodes[0], 0.0

    node_to_index = {
        node: i
        for i, node in enumerate(nodes)
    }

    node_bits = [1 << i for i in range(n)]
    adjacency = []
    for node in nodes:
        neighbors = 0
        for target in graph[node]:
            target_index = node_to_index.get(target)
            if target_index is not None:
                neighbors |= node_bits[target_index]
        adjacency.append(neighbors)

    all_nodes = (1 << n) - 1

    scores = {}
    best_node = None
    best_score = -1.0

    for start_index, start_node in enumerate(nodes):
        visited = node_bits[start_index]
        frontier = visited
        distance = 0
        total_distance = 0

        while frontier and visited != all_nodes:
            neighbors = 0
            current_level = frontier
            missing = all_nodes ^ visited

            while current_level:
                lowest_bit = current_level & -current_level
                current_index = lowest_bit.bit_length() - 1
                neighbors |= adjacency[current_index]
                current_level ^= lowest_bit

                # Once this level reaches every remaining node, scanning its
                # other pages cannot change any shortest-path distance.
                if neighbors & missing == missing:
                    break

            frontier = neighbors & missing
            distance += 1
            total_distance += distance * frontier.bit_count()
            visited |= frontier

        if visited == all_nodes and total_distance > 0:
            score = (n - 1) / total_distance
        else:
            score = 0.0

        scores[start_node] = score

        if score > best_score:
            best_score = score
            best_node = start_node

        if verbose and (start_index + 1) % 250 == 0:
            print(
                f"Closeness: "
                f"{start_index + 1}/{n} nodes processed..."
            )

    return scores, best_node, best_score


def print_stats(name, stats):
    print(f"\n{name}")
    print(f"Average: {stats['average']:.4f}")
    print(f"Median:  {stats['median']:.4f}")
    print(f"Min:     {stats['min']}")
    print(f"Max:     {stats['max']}")
    print(f"20%:     {stats['q20']:.4f}")
    print(f"40%:     {stats['q40']:.4f}")
    print(f"60%:     {stats['q60']:.4f}")
    print(f"80%:     {stats['q80']:.4f}")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--bucket",
        default="cloud_hw2_bucket"
    )

    parser.add_argument(
        "--prefix",
        default="pages/"
    )

    parser.add_argument(
        "--skip-closeness",
        action="store_true"
    )

    parser.add_argument(
        "--public-http",
        action="store_true",
        help="Download public objects through fresh HTTPS connections."
    )

    parser.add_argument(
        "--checkpoint",
        metavar="PATH",
        help="Save and resume --public-http downloads at this file."
    )

    args = parser.parse_args()
    if args.checkpoint and not args.public_http:
        parser.error("--checkpoint requires --public-http")

    total_start = time.perf_counter()

    start = time.perf_counter()
    load_progress = {}

    graph = load_graph(
        args.bucket,
        args.prefix,
        public_http=args.public_http,
        checkpoint_path=args.checkpoint,
        progress=load_progress
    )

    current_load_time = time.perf_counter() - start
    load_time = load_progress.get("load_seconds", current_load_time)

    print(f"\nPages: {len(graph)}")
    print(f"Links: {sum(len(v) for v in graph.values())}")
    if args.checkpoint:
        print(
            f"Load time: {load_time:.3f} seconds "
            "(cumulative successful graph loading across sessions)"
        )
        print(
            f"Resumed files: {load_progress['resumed_files']}; "
            f"current session loading: {current_load_time:.3f} seconds"
        )
    else:
        print(f"Load time: {load_time:.3f} seconds")

    if len(graph) != 12000:
        print("WARNING: Expected 12,000 pages.")

    start = time.perf_counter()

    incoming_stats, outgoing_stats = compute_degree_stats(graph)

    degree_time = time.perf_counter() - start

    print_stats("INCOMING LINKS", incoming_stats)
    print_stats("OUTGOING LINKS", outgoing_stats)

    print(
        f"\nDegree-statistics time: "
        f"{degree_time:.3f} seconds"
    )

    start = time.perf_counter()

    ranks, iterations = pagerank(graph)

    pagerank_time = time.perf_counter() - start

    top5 = sorted(
        ranks.items(),
        key=lambda item: (-item[1], item[0])
    )[:5]

    print("\nTOP 5 PAGES BY PAGERANK")

    for position, (page, score) in enumerate(top5, 1):
        print(
            f"{position}. "
            f"{page}.html -> "
            f"{score:.10f}"
        )

    print(f"PageRank iterations: {iterations}")
    print(f"PageRank time: {pagerank_time:.3f} seconds")

    closeness_time = 0.0

    if not args.skip_closeness:
        start = time.perf_counter()

        _, best_node, best_score = closeness_centrality(graph)

        closeness_time = time.perf_counter() - start

        print("\nBEST CLOSENESS CENTRALITY")

        print(
            f"{best_node}.html -> "
            f"{best_score:.10f}"
        )

        print(
            f"Closeness time: "
            f"{closeness_time:.3f} seconds"
        )

    current_total_time = time.perf_counter() - total_start
    total_time = (
        current_total_time - current_load_time + load_time
        if args.checkpoint else current_total_time
    )

    print("\n========== TIMING SUMMARY ==========")
    print(f"Graph loading:     {load_time:.3f} seconds")
    print(f"Degree statistics: {degree_time:.3f} seconds")
    print(f"PageRank:          {pagerank_time:.3f} seconds")

    if not args.skip_closeness:
        print(f"Closeness:         {closeness_time:.3f} seconds")

    print(f"Total runtime:     {total_time:.3f} seconds")
    if args.checkpoint:
        print(
            "Timing note: graph loading and total runtime include saved "
            "work from prior sessions; unfinished work after the last "
            "checkpoint is excluded."
        )
        print(
            f"Current invocation wall time: {current_total_time:.3f} seconds"
        )
    print("====================================")


if __name__ == "__main__":
    main()

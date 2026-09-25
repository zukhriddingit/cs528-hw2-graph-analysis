import unittest
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from hw2 import pagerank, closeness_centrality, load_graph


class TestPageRank(unittest.TestCase):

    def test_pagerank_known_graph(self):
        graph = {
            0: [1],
            1: [0, 2],
            2: [0],
        }

        ranks, iterations = pagerank(
            graph,
            tolerance=0.005,
            max_iterations=1000,
            verbose=False
        )

        self.assertGreater(ranks[0], ranks[2])
        self.assertGreater(ranks[1], ranks[2])

        self.assertGreater(iterations, 0)

    def test_pagerank_converges_to_known_numeric_scores(self):
        graph = {
            0: [1],
            1: [0, 2],
            2: [0],
        }
        ranks, iterations = pagerank(
            graph,
            tolerance=1e-10,
            max_iterations=1000,
            verbose=False,
        )

        # Solve the three PageRank equations directly for this graph.
        expected_zero = 0.1318125 / 0.3316875
        expected_one = 0.05 + 0.85 * expected_zero
        expected_two = 0.05 + 0.425 * expected_one
        expected = {0: expected_zero, 1: expected_one, 2: expected_two}

        self.assertGreater(iterations, 1)
        for node, score in expected.items():
            self.assertAlmostEqual(ranks[node], score, delta=1e-10)


class TestClosenessCentrality(unittest.TestCase):

    @staticmethod
    def reference_closeness(graph, start):
        distances = {start: 0}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbor in graph[node]:
                if neighbor in graph and neighbor not in distances:
                    distances[neighbor] = distances[node] + 1
                    queue.append(neighbor)

        if len(distances) != len(graph):
            return 0.0
        total_distance = sum(distances.values())
        return (len(graph) - 1) / total_distance if total_distance else 0.0

    def test_closeness_known_graph(self):
        graph = {
            0: [1, 2, 3],
            1: [0],
            2: [0],
            3: [0],
        }

        scores, best_node, best_score = closeness_centrality(
            graph,
            verbose=False
        )

        self.assertEqual(best_node, 0)
        self.assertAlmostEqual(best_score, 1.0)

        self.assertAlmostEqual(scores[1], 0.6)
        self.assertAlmostEqual(scores[2], 0.6)
        self.assertAlmostEqual(scores[3], 0.6)

    def test_bitset_closeness_matches_reference_on_directed_graph(self):
        graph = {
            0: [1, 2, 2, 99],
            1: [0, 3],
            2: [0],
            3: [2, 4],
            4: [],
            5: [0],
        }
        scores, best_node, best_score = closeness_centrality(
            graph, verbose=False
        )
        for node in graph:
            self.assertAlmostEqual(
                scores[node], self.reference_closeness(graph, node)
            )

        self.assertEqual(best_node, 5)
        self.assertAlmostEqual(best_score, 5 / 12)


class TestCheckpointResume(unittest.TestCase):

    def test_resume_skips_saved_files_and_finishes_graph(self):
        blobs = [SimpleNamespace(name=f"pages/{i}.html") for i in range(4)]
        client = SimpleNamespace(list_blobs=lambda *args, **kwargs: blobs)
        calls = []

        def interrupt_after_checkpoint(blob):
            calls.append(blob.name)
            if blob.name == "pages/2.html":
                raise RuntimeError("interrupted")
            return '<a HREF="1.html">link</a>'

        with TemporaryDirectory() as directory:
            checkpoint = str(Path(directory) / "graph.pkl")
            with patch("hw2.get_storage_client", return_value=client), patch(
                "hw2.download_public_blob", side_effect=interrupt_after_checkpoint
            ):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    load_graph(
                        "bucket", public_http=True, checkpoint_path=checkpoint,
                        checkpoint_every=2
                    )

            self.assertTrue(Path(checkpoint).is_file())
            calls.clear()
            progress = {}
            with patch("hw2.get_storage_client", return_value=client), patch(
                "hw2.download_public_blob",
                side_effect=lambda blob: calls.append(blob.name) or
                '<a HREF="1.html">link</a>'
            ):
                graph = load_graph(
                    "bucket", public_http=True, checkpoint_path=checkpoint,
                    checkpoint_every=2, progress=progress
                )

            self.assertEqual(progress["resumed_files"], 2)
            self.assertGreater(progress["load_seconds"], 0)
            self.assertEqual(calls, ["pages/2.html", "pages/3.html"])
            self.assertEqual(graph, {i: [1] for i in range(4)})


if __name__ == "__main__":
    unittest.main()

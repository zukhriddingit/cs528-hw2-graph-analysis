import unittest
from collections import deque

from hw2 import pagerank, closeness_centrality


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


if __name__ == "__main__":
    unittest.main()

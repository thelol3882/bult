"""Tests of the pure parts of bench/lb.py: python3 -m unittest discover -s bench"""

import unittest

import lb

CSV = """response-time,DNS+dialup,DNS,Request-write,Response-delay,Response-read,status-code,offset
0.010,0.001,0.000,0.000,0.009,0.000,200,0.010
0.020,0.001,0.000,0.000,0.019,0.000,200,0.020
0.030,0.001,0.000,0.000,0.029,0.000,200,0.030
0.040,0.001,0.000,0.000,0.039,0.000,200,0.040
0.500,0.001,0.000,0.000,0.499,0.000,502,0.500
"""


class Percentile(unittest.TestCase):
    def test_interpolates(self):
        values = [10.0, 20.0, 30.0, 40.0]
        self.assertEqual(lb.percentile(values, 0), 10.0)
        self.assertEqual(lb.percentile(values, 1), 40.0)
        self.assertAlmostEqual(lb.percentile(values, 0.5), 25.0)

    def test_single_value(self):
        self.assertEqual(lb.percentile([7.0], 0.99), 7.0)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            lb.percentile([], 0.5)


class Summary(unittest.TestCase):
    def test_parse_csv(self):
        rows = lb.parse_hey_csv(CSV)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0], (0.010, 200))

    def test_errors_are_counted_not_measured(self):
        s = lb.summarize(lb.parse_hey_csv(CSV), seconds=2)
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["requests"], 5)
        self.assertAlmostEqual(s["throughput"], 2.0)
        self.assertAlmostEqual(s["max"], 40.0)  # the 502 (500 ms) is not a latency sample
        self.assertLessEqual(s["p50"], s["p95"])
        self.assertLessEqual(s["p95"], s["p99"])

    def test_no_successes(self):
        s = lb.summarize([(0.1, 500)], seconds=1)
        self.assertEqual(s, {"requests": 1, "errors": 1, "throughput": 0.0})


class Order(unittest.TestCase):
    def test_alternates(self):
        order = lb.run_order(["round_robin", "least_conn"], 3)
        self.assertEqual([a for _, a in order], ["round_robin", "least_conn"] * 3)
        self.assertEqual([r for r, _ in order], [1, 1, 2, 2, 3, 3])


def run(scenario, algorithm, p95):
    stream = {"p50": 10.0, "p95": p95, "p99": p95 + 1, "max": p95 + 2, "throughput": 50.0, "errors": 0}
    return {"scenario": scenario, "algorithm": algorithm, "repeat": 1, "fast": dict(stream), "heavy": dict(stream)}


class Aggregate(unittest.TestCase):
    def test_median_and_range(self):
        runs = [run("mixed", "least_conn", v) for v in (30.0, 10.0, 20.0)]
        agg = lb.aggregate(runs)["mixed"]["least_conn"]["fast"]["p95"]
        self.assertEqual((agg["median"], agg["min"], agg["max"], agg["n"]), (20.0, 10.0, 30.0, 3))

    def test_groups_by_scenario_and_algorithm(self):
        runs = [run("mixed", "round_robin", 5.0), run("slow-replica", "round_robin", 9.0)]
        agg = lb.aggregate(runs)
        self.assertEqual(set(agg), {"mixed", "slow-replica"})
        self.assertEqual(agg["slow-replica"]["round_robin"]["fast"]["p95"]["median"], 9.0)

    def test_summary_has_a_row_per_algorithm(self):
        runs = [run("mixed", "round_robin", 5.0), run("mixed", "least_conn", 4.0)]
        meta = {"app": "load", "duration": 60, "warmup": 15, "repeats": 1,
                "fast_c": 12, "fast_ms": 10, "heavy_c": 3, "heavy_ms": 300}
        text = lb.render_summary(lb.aggregate(runs), meta)
        self.assertIn("| round_robin |", text)
        self.assertIn("| least_conn |", text)


class Args(unittest.TestCase):
    def test_defaults(self):
        a = lb.parse_args([])
        self.assertEqual(a.algorithms, ["round_robin", "least_conn"])
        self.assertEqual(a.scenarios, ["mixed"])
        self.assertEqual((a.duration, a.warmup, a.repeats), (60, 15, 3))
        self.assertIn("bench/results/", a.out)

    def test_both_scenarios(self):
        self.assertEqual(lb.parse_args(["--scenario", "both"]).scenarios, ["mixed", "slow-replica"])

    def test_no_switch_needs_one_algorithm(self):
        with self.assertRaises(SystemExit):
            lb.parse_args(["--no-switch"])
        self.assertEqual(lb.parse_args(["--no-switch", "--algorithms", "least_conn"]).algorithms, ["least_conn"])


if __name__ == "__main__":
    unittest.main()

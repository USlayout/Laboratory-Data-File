import json
import tempfile
import unittest
from pathlib import Path

from tools.benchmark_analysis import analysis_filename, analyze_folder, common_metrics, describe, load_analysis, parse_file, save_analysis


class AnalysisTests(unittest.TestCase):
    def test_analysis_filenames(self):
        for keys, expected in (
            (["sysbench.cpu.events"], "sysbench_cpu_benchmark.json"),
            (["sysbench.memory.read", "sysbench.memory.write"], "sysbench_memory_benchmark.json"),
            (["fio.rand_read.iops", "fio.seq_write.throughput"], "fio_benchmark.json"),
            (["iperf3.tcp.throughput", "iperf3.udp.loss"], "iperf3_benchmark.json"),
            (["sysbench.memory.read", "sysbench.cpu.events"], "sysbench_cpu_memory_benchmark.json"),
            (["fio.rand_read.iops", "sysbench.cpu.events"], "sysbench_cpu_fio_benchmark.json"),
        ):
            with self.subTest(keys=keys):
                self.assertEqual(analysis_filename({"metrics": [{"key": key} for key in keys]}), expected)

    def test_environment_in_analysis_filename(self):
        for environment in ("Host", "KVM", "Docker", "DOK"):
            report = {"environment": environment, "metrics": [{"key": "sysbench.cpu.events"}]}
            self.assertEqual(analysis_filename(report), f"sysbench_cpu_benchmark_{environment}.json")
        report["environment"] = "KVM上Docker"
        self.assertEqual(analysis_filename(report), "sysbench_cpu_benchmark_DOK.json")

    def test_sample_stddev_and_small_samples(self):
        self.assertEqual(describe([1, 2, 3])["stddev"], 1)
        self.assertIsNone(describe([5])["stddev"])
        self.assertEqual(describe([5])["outlier_indices"], [])

    def test_outliers_are_not_removed(self):
        result = describe([10] * 8 + [100, 200])
        self.assertEqual(result["outlier_indices"], [8, 9])
        self.assertEqual(result["n"], 10)
        self.assertEqual(result["mean"], 38)
        self.assertEqual(result["filtered"]["mean"], 10)
        self.assertTrue(any("多い" in w for w in result["warnings"]))

    def test_real_data(self):
        report = analyze_folder((Path(__file__).resolve().parents[2] / "sample/2026-11-25-sysbench-cpu"), "Host")
        self.assertEqual(report["metrics"][0]["n"], 10)
        report = analyze_folder((Path(__file__).resolve().parents[2] / "2026-11-10-18-17-56"), "Host")
        self.assertEqual(len(report["metrics"]), 15)
        self.assertTrue(all(m["n"] == 10 for m in report["metrics"]))

    def test_round_trip_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "sysbench_cpu_result.txt").write_text("events per second: 123.45")
            report = analyze_folder(folder, "Host")
            destination = folder / "report.json"
            save_analysis(report, destination)
            loaded = load_analysis(destination)
            self.assertEqual(loaded["metrics"], report["metrics"])
            self.assertTrue(destination.with_suffix(".csv").exists())
            self.assertTrue((folder / "report_samples.csv").exists())

    def test_invalid_files_and_retry_do_not_pollute_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "sysbench_cpu_result.txt").write_text("events per second: 5")
            (folder / "iperf3_tcp.json").write_text('{"error":"server busy"}')
            (folder / "iperf3_udp.json").write_text('{broken')
            (folder / "iperf3_tcp.attempt1.json").write_text('{"end":{}}')
            report = analyze_folder(folder, "test")
            self.assertEqual(len(report["metrics"]), 1)
            self.assertEqual(len(report["warnings"]), 3)

    def test_iperf_receiver_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "iperf3_udp.json"
            path.write_text(json.dumps({"end": {"sum_sent": {"bits_per_second": 1000000000},
                            "sum_received": {"bits_per_second": 800000000, "jitter_ms": .5, "lost_percent": 20}}}))
            self.assertEqual(parse_file(path)[0][2], 800)
            self.assertEqual(len(parse_file(path)), 3)
            path.write_text(json.dumps({"end": {"sum": {"sender": True, "bits_per_second": 100}}}))
            with self.assertRaises(ValueError):
                parse_file(path)

    def test_fio_multijob_units_and_weighted_latency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fio_rand_read.json"
            path.write_text(json.dumps({"jobs": [
                {"read": {"bw": 1024, "iops": 100, "total_ios": 10, "lat_ns": {"mean": 1000}}},
                {"read": {"bw_bytes": 1048576, "iops": 200, "total_ios": 30, "lat_ns": {"mean": 3000}}}]}))
            values = {k: v for k, _, v in parse_file(path)}
            self.assertEqual(values["fio.rand_read.throughput"], 2)
            self.assertEqual(values["fio.rand_read.iops"], 300)
            self.assertEqual(values["fio.rand_read.latency"], 2.5)

    def test_common_metrics_require_matching_units(self):
        reports = [{"metrics": [{"key": "a", "unit": "ms"}, {"key": "b", "unit": "IOPS"}]},
                   {"metrics": [{"key": "a", "unit": "µs"}, {"key": "b", "unit": "IOPS"}]}]
        self.assertEqual(common_metrics(reports), [("b", "IOPS")])

    def test_empty_and_invalid_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                analyze_folder(Path(directory), "test")
            with self.assertRaises(ValueError):
                analyze_folder(Path(directory), "test", float("nan"))


if __name__ == "__main__":
    unittest.main()

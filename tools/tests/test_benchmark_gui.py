"""Tk events, worker rendering, cache, export and persistent history."""
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.benchmark_analysis import analyze_folder, describe
from tools.benchmark_gui import BenchmarkApp
from tools.history import History
from tools.plotting import comparison_figure, graph_filename
from tools.environments import ENVIRONMENTS


class HistoryTests(unittest.TestCase):
    def test_persistent_snapshot_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            measurement = folder / "sysbench_cpu_result.txt"
            measurement.write_text("events per second: 123")
            report = analyze_folder(folder, "Host")
            path = folder / "state/history.sqlite3"
            identity = History(path).add(report)
            measurement.unlink()
            reopened = History(path)
            self.assertEqual(reopened.load(identity), report)
            self.assertEqual(reopened.entries()[0][0], identity)
            reopened.delete(identity)
            self.assertEqual(reopened.entries(), [])
            with self.assertRaises(ValueError):
                reopened.load(identity)


class GuiTests(unittest.TestCase):
    def wait_for(self, root, predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        self.assertTrue(predicate(), "Async task did not complete")

    def test_async_preview_cache_export_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            run = folder / "run01"
            run.mkdir()
            (run / "sysbench_cpu_result.txt").write_text("events per second: 123")
            (run / "sysbench_memory_read.txt").write_text("10240 MiB transferred (500 MiB/sec)")
            root = tk.Tk()
            root.withdraw()
            app = BenchmarkApp(root, history_path=folder / "history.sqlite3")
            try:
                self.assertEqual(str(app.environment_box["state"]), "readonly")
                self.assertEqual(tuple(app.environment_box["values"]), ENVIRONMENTS)
                self.assertEqual([label.get() for label in app.labels], list(ENVIRONMENTS))
                app.folder.set(str(folder))
                app.analyze()
                self.assertEqual(str(app.analyze_button["state"]), "disabled")
                self.wait_for(root, lambda: app.report is not None and bool(app.history_table.get_children()))
                self.assertEqual(len(app.table.get_children()), 2)
                with patch("tools.benchmark_gui.filedialog.asksaveasfilename", return_value="") as dialog:
                    app.save()
                    self.assertEqual(dialog.call_args.kwargs["initialfile"], "sysbench_cpu_memory_benchmark_Host.json")
                app.table.selection_set("0")
                app.show_detail()
                self.assertIn("run01", app.details.get("1.0", "end"))
                app.comparisons = [app.report] * 4
                app.refresh_metrics()
                app.draw()
                ticks = []
                root.after(1, lambda: ticks.append(1))
                self.wait_for(root, lambda: app.image is not None)
                self.assertTrue(ticks)
                self.assertEqual(len(app.graph_cache), 1)
                app.draw()
                self.assertIsNotNone(app.image)
                self.assertIn("キャッシュ", app.status.get())
                app.events.put(("graph", True, b"not an image", (app.graph_generation - 1, "old")))
                root.update()
                with patch("tools.benchmark_gui.filedialog.asksaveasfilename", return_value="") as dialog:
                    app.export_graph()
                    self.assertEqual(dialog.call_args.kwargs["initialfile"], "sysbench_cpu_events_Host_KVM_Docker_DOK.png")
                svg = folder / "comparison.svg"
                with patch("tools.benchmark_gui.filedialog.asksaveasfilename", return_value=str(svg)):
                    app.export_graph()
                self.wait_for(root, lambda: svg.exists() and svg.stat().st_size > 1000)
                with patch("tools.benchmark_gui.filedialog.askdirectory", return_value=str(folder)):
                    app.export_all()
                self.wait_for(root, lambda: app.batch_done == app.batch_total)
                self.assertEqual(app.batch_errors, [])
                for identity in app.identities:
                    self.assertGreater((folder / graph_filename(identity, environments=ENVIRONMENTS)).stat().st_size, 1000)
                identity = app.history_table.get_children()[0]
                app.report = None
                app.history_table.selection_set(identity)
                app.open_history()
                self.wait_for(root, lambda: app.report is not None)
                app.clear_report(0)
                self.assertIsNone(app.image)
            finally:
                futures = list(app.pending)
                app.close()
                for future in futures:
                    if not future.cancelled():
                        future.result(timeout=30)

    def test_filename_and_single_sample_graph(self):
        self.assertEqual(graph_filename(("fio.rand_read.iops", "IOPS")), "fio_rand_read_iops.png")
        self.assertEqual(graph_filename(("iperf3.tcp.throughput", "Mbit/s"), True, "svg"), "iperf3_tcp_throughput_filtered.svg")
        self.assertEqual(graph_filename(("fio.rand_read.iops", "IOPS"), environments=("Host", "KVM")), "fio_rand_read_iops_Host_KVM.png")
        self.assertEqual(graph_filename(("fio.rand_read.iops", "IOPS"), True, "svg", ("Docker", "KVM上Docker")), "fio_rand_read_iops_Docker_DOK_filtered.svg")
        report = {"metrics": [{"key": "test", "unit": "IOPS", **describe([10])}]}
        figure = comparison_figure([report] * 2, ["Host", "KVM"], ("test", "IOPS"), True)
        self.assertEqual(figure.axes[2].texts[0].get_text(), "N/A")


if __name__ == "__main__":
    unittest.main()

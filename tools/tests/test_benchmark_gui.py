"""GUI smoke tests; require a desktop-capable Tk installation."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from tools.benchmark_analysis import analyze_folder
from tools.benchmark_gui import BenchmarkApp, comparison_figure


class GuiTests(unittest.TestCase):
    def test_layout_preview_and_export(self):
        root = tk.Tk()
        root.withdraw()
        app = BenchmarkApp(root)
        try:
            report = analyze_folder((Path(__file__).resolve().parents[2] / "2026-11-25-sysbench-cpu"), "Host")
            app.events.put((True, report))
            app.poll()
            self.assertEqual(len(app.table.get_children()), 1)
            self.assertEqual(str(app.save_button["state"]), "normal")
            app.table.selection_set("0")
            app.show_detail()
            self.assertIn("run01", app.details.get("1.0", "end"))
            app.comparisons = [report] * 4
            app.refresh_metrics()
            app.draw()
            root.update_idletasks()
            self.assertIsNotNone(app.canvas)
            self.assertEqual(len(app.figure.axes), 3)
            with tempfile.TemporaryDirectory() as directory:
                for extension in ("png", "svg"):
                    path = Path(directory) / ("comparison." + extension)
                    app.figure.savefig(path)
                    self.assertGreater(path.stat().st_size, 1000)
            app.clear_report(0)
            self.assertIsNone(app.figure)
        finally:
            root.destroy()

    def test_single_sample_graph_and_filtered_view(self):
        from tools.benchmark_analysis import describe
        report = {"metrics": [{"key": "test", "unit": "IOPS", **describe([10])}]}
        figure = comparison_figure([report] * 2, ["Host", "KVM"], ("test", "IOPS"), True)
        self.assertEqual(figure.axes[2].texts[0].get_text(), "N/A")


if __name__ == "__main__":
    unittest.main()

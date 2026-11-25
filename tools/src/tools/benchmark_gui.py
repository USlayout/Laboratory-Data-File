"""Tkinter desktop application. Run from tools directory with: uv run tools"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .benchmark_analysis import analyze_folder, common_metrics, load_analysis, save_analysis


def number(value):
    return "算出不可" if value is None else f"{value:,.6g}"


def comparison_figure(reports, labels, identity, filtered=False):
    from matplotlib.figure import Figure
    from matplotlib import font_manager
    font = next((n for n in ("Meiryo", "Yu Gothic", "Noto Sans CJK JP", "DejaVu Sans")
                 if n in {f.name for f in font_manager.fontManager.ttflist}), "DejaVu Sans")
    figure = Figure(figsize=(11, 6), dpi=100)
    axes = figure.subplots(1, 3)
    for ax, (stat, title) in zip(axes, (("median", "中央値"), ("mean", "平均値"), ("stddev", "標本標準偏差"))):
        plotted_values = []
        for i, (report, label) in enumerate(zip(reports, labels)):
            m = next(m for m in report["metrics"] if (m["key"], m["unit"]) == identity)
            selected = m["filtered"] if filtered else m
            value = selected[stat]
            plotted_values.append(value or 0)
            ax.bar(i, value if value is not None else 0, color=("#2678b6", "#40a688", "#e4a43a", "#a579bc")[i])
            caption = "N/A" if value is None else (f"{value:,.0f}" if value >= 1000 else f"{value:.3g}")
            ax.annotate(caption, (i, value or 0), xytext=(0, 5),
                        textcoords="offset points", ha="center", fontsize=8)
        ax.set_title(title, fontfamily=font)
        ax.set_xticks(range(len(labels)), labels, rotation=20, ha="right", fontfamily=font)
        ax.set_ylabel(identity[1], fontfamily=font)
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
        ax.set_ylim(0, max(plotted_values) * 1.18 if max(plotted_values) > 0 else 1)
    mode = "外れ値除外・参考値" if filtered else "全測定値"
    figure.suptitle(f"{identity[0]}  [{mode}]", fontfamily=font)
    counts = []
    for report, label in zip(reports, labels):
        m = next(m for m in report["metrics"] if (m["key"], m["unit"]) == identity)
        n = m["filtered"]["n"] if filtered else m["n"]
        counts.append(f"{label}: n={n}, 外れ値={len(m['outlier_indices'])}")
    figure.text(.5, .02, " / ".join(counts), ha="center", fontfamily=font, fontsize=9)
    figure.tight_layout(rect=(0, .08, 1, .92))
    return figure


class BenchmarkApp(ttk.Frame):
    def __init__(self, root):
        super().__init__(root, padding=16)
        self.pack(fill="both", expand=True)
        root.title("Benchmark Analyzer | 測定データ解析")
        root.geometry("1180x800")
        root.minsize(900, 620)
        self.report = None
        self.events = queue.Queue()
        self.comparisons = [None] * 4
        self.figure = self.canvas = self.toolbar = None
        self.identities = []
        self.status = tk.StringVar(value="測定フォルダを選択してください。元データは変更しません。")
        ttk.Label(self, text="Benchmark Analyzer", font=("Segoe UI", 21, "bold")).pack(anchor="w")
        ttk.Label(self, text="測定フォルダの集計 → 解析JSONを保存 → 4環境を比較").pack(anchor="w", pady=(0, 12))
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        analysis = ttk.Frame(notebook, padding=12)
        comparison = ttk.Frame(notebook, padding=12)
        notebook.add(analysis, text="  1. データ解析  ")
        notebook.add(comparison, text="  2. 環境比較グラフ  ")
        self.build_analysis(analysis)
        self.build_comparison(comparison)
        ttk.Label(self, textvariable=self.status, wraplength=1100).pack(anchor="w", pady=(10, 0))
        self.after(100, self.poll)

    def build_analysis(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x")
        self.folder = tk.StringVar()
        ttk.Label(row, text="測定フォルダ").pack(side="left")
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="フォルダ選択", command=self.pick_folder).pack(side="left")
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=10)
        self.environment = tk.StringVar(value="Host")
        ttk.Label(row, text="環境名").pack(side="left")
        ttk.Entry(row, textvariable=self.environment, width=22).pack(side="left", padx=8)
        ttk.Label(row, text="外れ値が多いとする割合 (%)").pack(side="left")
        self.threshold = tk.StringVar(value="20")
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.threshold, width=6).pack(side="left", padx=8)
        self.analyze_button = ttk.Button(row, text="解析する", command=self.analyze)
        self.analyze_button.pack(side="left", padx=8)
        self.save_button = ttk.Button(row, text="JSON・CSV保存", command=self.save, state="disabled")
        self.save_button.pack(side="left")
        ttk.Label(parent, text="同じ環境・測定条件のフォルダを選択。CPU用・メモリ用などは個別に解析できます。\n"
                  "外れ値: 1.5×IQR / 全件を集計 / 標準偏差: ddof=1 / 1件では算出不可").pack(anchor="w", pady=(0, 8))
        columns = ("metric", "unit", "n", "median", "mean", "stddev", "outliers", "warning")
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for col, title, width in zip(columns, ("指標", "単位", "件数", "中央値", "平均値", "標準偏差", "外れ値", "注意"),
                                     (245, 70, 45, 100, 100, 100, 65, 230)):
            self.table.heading(col, text=title)
            self.table.column(col, width=width, minwidth=40, stretch=col in {"metric", "warning"})
        self.table.tag_configure("warning", background="#fff1d6")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.bind("<<TreeviewSelect>>", self.show_detail)
        self.details = tk.Text(parent, height=8, wrap="word", state="disabled")
        self.details.pack(fill="x", pady=(8, 0))

    def pick_folder(self):
        folder = filedialog.askdirectory(title="同じ環境・測定条件のデータフォルダ")
        if folder:
            self.folder.set(folder)

    def analyze(self):
        try:
            folder = Path(self.folder.get())
            if not self.folder.get():
                raise ValueError("測定フォルダを選択してください")
            threshold = float(self.threshold.get())
        except ValueError as exc:
            messagebox.showerror("入力を確認", str(exc))
            return
        environment = self.environment.get()
        self.analyze_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.status.set("解析中…")
        def work():
            try:
                self.events.put((True, analyze_folder(folder, environment, threshold)))
            except Exception as exc:
                self.events.put((False, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            ok, result = self.events.get_nowait()
            self.analyze_button.configure(state="normal")
            if ok:
                self.report = result
                self.table.delete(*self.table.get_children())
                for i, m in enumerate(result["metrics"]):
                    self.table.insert("", "end", iid=str(i), values=(m["key"], m["unit"], m["n"], number(m["median"]),
                                      number(m["mean"]), number(m["stddev"]), len(m["outlier_indices"]), " / ".join(m["warnings"])),
                                      tags=("warning",) if m["warnings"] else ())
                self.save_button.configure(state="normal")
                self.set_detail("\n".join(result["warnings"]) or "読み込みエラーなし。指標を選択すると測定値と外れ値の出典を確認できます。")
                self.status.set(f"解析完了: {len(result['metrics'])}指標 / 読み込み注意 {len(result['warnings'])}件")
            else:
                self.report = None
                self.table.delete(*self.table.get_children())
                self.set_detail(str(result))
                self.status.set("解析に失敗しました。フォルダとデータを確認してください。")
                messagebox.showerror("解析エラー", result)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def set_detail(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def show_detail(self, event=None):
        if not self.report or not self.table.selection():
            return
        m = self.report["metrics"][int(self.table.selection()[0])]
        f = m["filtered"]
        lines = [f"{m['key']} / 外れ値を除いた参考値: n={f['n']}, 中央値={number(f['median'])}, 平均={number(f['mean'])}, 標準偏差={number(f['stddev'])}"]
        lines += [f"{'[外れ値] ' if i in m['outlier_indices'] else ''}{s['source']}: {number(s['value'])} {m['unit']}"
                  for i, s in enumerate(m["samples"])]
        lines += ["\n読み込み注意:", *self.report["warnings"]]
        self.set_detail("\n".join(lines))

    def save(self):
        if not self.report:
            return
        path = filedialog.asksaveasfilename(title="解析結果を保存（同名CSVと測定値CSVも保存）", defaultextension=".json",
                                          initialfile="benchmark_analysis.json", filetypes=[("解析JSON", "*.json")])
        if path:
            try:
                destination = Path(path)
                companions = [destination.with_suffix(".csv"), destination.with_name(destination.stem + "_samples.csv")]
                if any(p.exists() for p in companions) and not messagebox.askyesno("上書き確認", "同名のCSVファイルも上書きしますか？"):
                    return
                save_analysis(self.report, destination)
                self.status.set(f"保存完了: {destination} と集計CSV・測定値CSV")
            except Exception as exc:
                messagebox.showerror("保存エラー", str(exc))

    def build_comparison(self, parent):
        ttk.Label(parent, text="このツールで保存した解析JSONを各環境に指定してください。単位が一致する共通指標を比較します。").pack(anchor="w")
        self.labels, self.paths = [], []
        for i, label in enumerate(("Host", "KVM", "Docker", "KVM上Docker")):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=3)
            name, path = tk.StringVar(value=label), tk.StringVar(value="未選択")
            self.labels.append(name)
            self.paths.append(path)
            ttk.Entry(row, textvariable=name, width=18).pack(side="left")
            ttk.Button(row, text="解析JSONを選択", command=lambda index=i: self.pick_report(index)).pack(side="left", padx=8)
            ttk.Label(row, textvariable=path).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="解除", command=lambda index=i: self.clear_report(index)).pack(side="right")
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=8)
        self.metric = tk.StringVar()
        self.metric_box = ttk.Combobox(row, textvariable=self.metric, state="readonly", width=44)
        self.metric_box.pack(side="left")
        self.filtered = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="外れ値除外の参考値", variable=self.filtered).pack(side="left", padx=8)
        ttk.Button(row, text="グラフ表示", command=self.draw).pack(side="left")
        ttk.Button(row, text="PNG / SVG保存", command=self.export_graph).pack(side="left", padx=8)
        self.compare_notice = tk.StringVar(value="2～4環境に対応。4環境すべて選択すると4環境比較になります。")
        ttk.Label(parent, textvariable=self.compare_notice, wraplength=1050).pack(anchor="w")
        self.plot_frame = ttk.Frame(parent)
        self.plot_frame.pack(fill="both", expand=True)

    def pick_report(self, index):
        path = filedialog.askopenfilename(title="保存した解析JSONを選択", filetypes=[("解析JSON", "*.json")])
        if path:
            try:
                report = load_analysis(Path(path))
                self.comparisons[index] = report
                self.paths[index].set(path)
                self.refresh_metrics()
            except Exception as exc:
                messagebox.showerror("解析JSONを読み込めません", str(exc))

    def clear_report(self, index):
        self.comparisons[index] = None
        self.paths[index].set("未選択")
        self.refresh_metrics()

    def refresh_metrics(self):
        selected = [r for r in self.comparisons if r]
        self.identities = common_metrics(selected)
        values = [f"{key} [{unit}]" for key, unit in self.identities]
        self.metric_box.configure(values=values)
        self.metric.set(values[0] if values else "")
        missing = len(set.union(*[{(m['key'], m['unit']) for m in r['metrics']} for r in selected])) - len(values) if selected else 0
        warnings = sum(len(r["warnings"]) + sum(bool(m["warnings"]) for m in r["metrics"]) for r in selected)
        duplicate = len({r.get("source") for r in selected}) < len(selected)
        extra = " 同じ元フォルダが複数行に指定されています。" if duplicate else ""
        self.compare_notice.set(f"選択 {len(selected)}/4環境 / 共通指標 {len(values)} / 共通でない指標 {missing} / 注意 {warnings}件。測定条件・CPU割当・測定時間は元データで確認してください。" + extra)
        self.discard_plot()

    def discard_plot(self):
        for widget in self.plot_frame.winfo_children():
            widget.destroy()
        self.figure = self.canvas = self.toolbar = None

    def draw(self):
        selected = [(r, label.get().strip()) for r, label in zip(self.comparisons, self.labels) if r]
        if len(selected) < 2 or not self.metric.get():
            messagebox.showerror("比較データを確認", "2～4環境と共通指標を選択してください。")
            return
        labels = [label for _, label in selected]
        if any(not label for label in labels) or len(set(labels)) != len(labels):
            messagebox.showerror("環境名を確認", "空欄や重複がない環境名を入力してください。")
            return
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
            figure = comparison_figure([r for r, _ in selected], labels, self.identities[self.metric_box.current()], self.filtered.get())
            self.discard_plot()
            self.figure = figure
            self.canvas = FigureCanvasTkAgg(figure, master=self.plot_frame)
            self.canvas.draw()
            self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_frame, pack_toolbar=False)
            self.toolbar.pack(side="bottom", fill="x")
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
        except Exception as exc:
            messagebox.showerror("グラフ作成エラー", str(exc))

    def export_graph(self):
        if self.figure is None:
            messagebox.showinfo("先にグラフを表示", "保存するグラフを表示してください。")
            return
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png"), ("SVG", "*.svg")])
        if path:
            try:
                self.figure.savefig(path, dpi=180, bbox_inches="tight")
                self.status.set(f"グラフ保存完了: {path}")
            except Exception as exc:
                messagebox.showerror("保存エラー", str(exc))


def main():
    root = tk.Tk()
    ttk.Style(root).theme_use("clam")
    BenchmarkApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

"""Tkinter desktop application. Run from tools directory with: uv run tools"""
from __future__ import annotations

import queue
import os
import io
import copy
import multiprocessing
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .benchmark_analysis import analyze_folder, common_metrics, load_analysis, save_analysis
from .history import History
from .plotting import graph_filename, render_graph, export_graph_file


def number(value):
    return "算出不可" if value is None else f"{value:,.6g}"


class BenchmarkApp(ttk.Frame):
    def __init__(self, root, history_path=None):
        super().__init__(root, padding=16)
        self.pack(fill="both", expand=True)
        root.title("Benchmark Analyzer | 測定データ解析")
        root.geometry("1180x800")
        root.minsize(900, 620)
        self.report = None
        self.events = queue.Queue()
        self.io_pool = ThreadPoolExecutor(max_workers=4)
        self.graph_workers = min(4, max(1, (os.cpu_count() or 2) - 1))
        self.graph_pool = ProcessPoolExecutor(max_workers=self.graph_workers,
                                             mp_context=multiprocessing.get_context("spawn"))
        self.history = History(history_path or Path(__file__).resolve().parents[2] / ".gui_state" / "history.sqlite3")
        self.graph_cache = OrderedDict()
        self.graph_generation = 0
        self.graph_request = None
        self.graph_future = None
        self.image = None
        self.closed = False
        self.pending = set()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.comparisons = [None] * 4
        self.report_versions = [0] * 4
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
        history_tab = ttk.Frame(notebook, padding=12)
        notebook.add(history_tab, text="  3. 解析履歴  ")
        self.notebook = notebook
        self.build_analysis(analysis)
        self.build_comparison(comparison)
        self.build_history(history_tab)
        ttk.Label(self, textvariable=self.status, wraplength=1100).pack(anchor="w", pady=(10, 0))
        self.poll_id = self.after(50, self.poll)

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
        self.submit(self.io_pool, "analysis", analyze_folder, folder, environment, threshold)

    def submit(self, pool, kind, function, *args, context=None):
        try:
            future = pool.submit(function, *args)
        except Exception as exc:
            self.events.put((kind, False, str(exc), context))
            return None
        self.pending.add(future)
        def done(result):
            try:
                self.events.put((kind, True, result.result(), context))
            except Exception as exc:
                self.events.put((kind, False, str(exc), context))
        future.add_done_callback(done)
        return future

    def display_report(self, report):
        self.report = report
        self.table.delete(*self.table.get_children())
        for i, m in enumerate(report["metrics"]):
            self.table.insert("", "end", iid=str(i), values=(m["key"], m["unit"], m["n"], number(m["median"]),
                              number(m["mean"]), number(m["stddev"]), len(m["outlier_indices"]), " / ".join(m["warnings"])),
                              tags=("warning",) if m["warnings"] else ())
        self.save_button.configure(state="normal")
        self.set_detail("\n".join(report["warnings"]) or "読み込みエラーなし。指標を選択すると測定値と外れ値の出典を確認できます。")

    def poll(self):
        for _ in range(30):
            try:
                kind, ok, result, context = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "graph" and context[0] != self.graph_generation:
                continue
            if kind == "report_loaded" and context[1] != self.report_versions[context[0]]:
                continue
            if kind == "analysis":
                self.analyze_button.configure(state="normal")
            if kind == "batch":
                self.batch_done += 1
                if not ok:
                    self.batch_errors.append(str(result))
                self.submit_next_batch()
                self.status.set(f"一括保存: {self.batch_done}/{self.batch_total} 完了 / エラー {len(self.batch_errors)}件")
                if self.batch_done == self.batch_total:
                    self.batch_button.configure(state="normal")
                    if self.batch_errors:
                        messagebox.showerror("一括保存のエラー", "\n".join(self.batch_errors))
                continue
            if not ok:
                if kind in {"analysis", "analysis_export"} and self.report:
                    self.save_button.configure(state="normal")
                if kind == "report_loaded":
                    self.paths[context[0]].set("読み込み失敗（再選択してください）")
                self.status.set(f"処理に失敗: {result}")
                messagebox.showerror("処理エラー", str(result))
                continue
            if kind == "analysis":
                self.display_report(result)
                self.status.set(f"解析完了: {len(result['metrics'])}指標 / 読み込み注意 {len(result['warnings'])}件")
                self.submit(self.io_pool, "history_saved", self.history.add, result)
            elif kind == "history_saved":
                self.refresh_history()
            elif kind == "history_list":
                self.history_table.delete(*self.history_table.get_children())
                for identity, created, environment, source in result:
                    self.history_table.insert("", "end", iid=str(identity), values=(created, environment, source))
            elif kind == "history_open":
                self.display_report(result)
                self.folder.set(result["source"])
                self.environment.set(result["environment"])
                self.threshold.set(str(result["policy"]["warning_percent"]))
                self.notebook.select(0)
                self.status.set("履歴の保存時点の解析結果を復元しました。最新データを反映するには再解析してください。")
            elif kind == "report_loaded":
                index, _, path = context
                self.comparisons[index] = result
                self.paths[index].set(path)
                self.refresh_metrics()
            elif kind == "analysis_export":
                self.save_button.configure(state="normal")
                self.status.set(f"保存完了: {context} と集計CSV・測定値CSV")
            elif kind == "graph":
                self.graph_cache[context[1]] = result
                if len(self.graph_cache) > 16:
                    self.graph_cache.popitem(last=False)
                self.show_graph_image(result)
                self.status.set("グラフ表示完了。PNG / SVG保存、または全指標PNG一括保存ができます。")
            elif kind == "export":
                self.status.set(f"グラフ保存完了: {result}")
        self.pending = {future for future in self.pending if not future.done()}
        if not self.closed:
            self.poll_id = self.after(50, self.poll)

    def build_history(self, parent):
        ttk.Label(parent, text="解析成功時に結果を自動保存します。元フォルダを移動しても、保存時点の結果を開けます。").pack(anchor="w")
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="履歴を開く", command=self.open_history).pack(side="left")
        ttk.Button(row, text="更新", command=self.refresh_history).pack(side="left", padx=8)
        ttk.Button(row, text="選択履歴を削除", command=self.delete_history).pack(side="left")
        ttk.Label(parent, text=f"保存場所: {self.history.path}").pack(anchor="w")
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=8)
        self.history_table = ttk.Treeview(frame, columns=("created", "environment", "source"), show="headings", selectmode="browse")
        for col, title, width in (("created", "解析日時", 210), ("environment", "環境", 140), ("source", "測定フォルダ", 650)):
            self.history_table.heading(col, text=title)
            self.history_table.column(col, width=width)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.history_table.yview)
        self.history_table.configure(yscrollcommand=scroll.set)
        self.history_table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.history_table.bind("<Double-1>", lambda event: self.open_history())
        self.refresh_history()

    def refresh_history(self):
        self.submit(self.io_pool, "history_list", self.history.entries)

    def open_history(self):
        selection = self.history_table.selection()
        if selection:
            self.submit(self.io_pool, "history_open", self.history.load, int(selection[0]))

    def delete_history(self):
        selection = self.history_table.selection()
        if selection and messagebox.askyesno("履歴の削除", "選択した履歴を削除しますか？元データは削除されません。"):
            self.submit(self.io_pool, "history_saved", self.history.delete, int(selection[0]))

    def close(self):
        self.closed = True
        self.after_cancel(self.poll_id)
        for future in self.pending:
            future.cancel()
        self.io_pool.shutdown(wait=False, cancel_futures=True)
        self.graph_pool.shutdown(wait=False, cancel_futures=True)
        self.winfo_toplevel().destroy()

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
                self.save_button.configure(state="disabled")
                self.status.set("解析JSON・CSV保存中…")
                self.submit(self.io_pool, "analysis_export", save_analysis, copy.deepcopy(self.report), destination, context=str(destination))
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
        self.batch_button = ttk.Button(row, text="全指標PNG一括保存", command=self.export_all)
        self.batch_button.pack(side="left")
        self.compare_notice = tk.StringVar(value="2～4環境に対応。4環境すべて選択すると4環境比較になります。")
        ttk.Label(parent, textvariable=self.compare_notice, wraplength=1050).pack(anchor="w")
        self.plot_frame = ttk.Frame(parent)
        self.plot_frame.pack(fill="both", expand=True)

    def pick_report(self, index):
        path = filedialog.askopenfilename(title="保存した解析JSONを選択", filetypes=[("解析JSON", "*.json")])
        if path:
            self.report_versions[index] += 1
            self.comparisons[index] = None
            self.paths[index].set(f"読み込み中: {path}")
            self.refresh_metrics()
            self.submit(self.io_pool, "report_loaded", load_analysis, Path(path), context=(index, self.report_versions[index], path))

    def clear_report(self, index):
        self.report_versions[index] += 1
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
        self.graph_generation += 1
        if self.graph_future is not None:
            self.graph_future.cancel()
            self.graph_future = None
        for widget in self.plot_frame.winfo_children():
            widget.destroy()
        self.image = None
        self.graph_request = None

    def graph_inputs(self):
        selected = [(r, label.get().strip()) for r, label in zip(self.comparisons, self.labels) if r]
        if len(selected) < 2 or not self.metric.get():
            messagebox.showerror("比較データを確認", "2～4環境と共通指標を選択してください。")
            return None
        labels = [label for _, label in selected]
        if any(not label for label in labels) or len(set(labels)) != len(labels):
            messagebox.showerror("環境名を確認", "空欄や重複がない環境名を入力してください。")
            return None
        return copy.deepcopy([r for r, _ in selected]), labels

    def draw(self):
        inputs = self.graph_inputs()
        if inputs is None:
            return
        identity = self.identities[self.metric_box.current()]
        request = (*inputs, identity, self.filtered.get())
        import json
        key = json.dumps(request, sort_keys=True, ensure_ascii=False)
        self.discard_plot()
        self.graph_request = request
        if key in self.graph_cache:
            self.show_graph_image(self.graph_cache[key])
            self.status.set("キャッシュからグラフを表示しました。")
            return
        self.status.set("グラフ生成中…（他の操作を続けられます）")
        self.graph_future = self.submit(self.graph_pool, "graph", render_graph, *request, context=(self.graph_generation, key))

    def show_graph_image(self, data):
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            self.preview_source = image.copy()
        self.plot_frame.update_idletasks()
        for widget in self.plot_frame.winfo_children():
            widget.destroy()
        controls = ttk.Frame(self.plot_frame)
        controls.pack(side="bottom", fill="x")
        ttk.Label(controls, text="表示倍率").pack(side="left")
        self.zoom = ttk.Combobox(controls, values=("全体", "50%", "100%", "150%", "200%"), state="readonly", width=8)
        self.zoom.set("全体")
        self.zoom.pack(side="left", padx=8)
        self.zoom.bind("<<ComboboxSelected>>", lambda event: self.resize_preview())
        frame = ttk.Frame(self.plot_frame)
        frame.pack(fill="both", expand=True)
        self.preview_canvas = tk.Canvas(frame, background="white", highlightthickness=0)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.preview_canvas.xview)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.preview_canvas.yview)
        self.preview_canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.preview_canvas.bind("<ButtonPress-1>", lambda event: self.preview_canvas.scan_mark(event.x, event.y))
        self.preview_canvas.bind("<B1-Motion>", lambda event: self.preview_canvas.scan_dragto(event.x, event.y, gain=1))
        self.resize_preview()

    def resize_preview(self):
        from PIL import Image, ImageTk
        image = self.preview_source.copy()
        if self.zoom.get() == "全体":
            image.thumbnail((max(600, self.plot_frame.winfo_width() - 24), max(200, self.plot_frame.winfo_height() - 50)), Image.Resampling.LANCZOS)
        else:
            scale = int(self.zoom.get().rstrip("%")) / 100
            image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
        self.image = ImageTk.PhotoImage(image, master=self)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self.image)
        self.preview_canvas.configure(scrollregion=(0, 0, image.width, image.height))

    def export_graph(self):
        if self.image is None or self.graph_request is None:
            messagebox.showinfo("先にグラフを表示", "保存するグラフを表示してください。")
            return
        reports, labels, identity, filtered = self.graph_request
        path = filedialog.asksaveasfilename(initialfile=graph_filename(identity, filtered), defaultextension=".png",
                                          filetypes=[("PNG", "*.png"), ("SVG", "*.svg")])
        if path:
            if Path(path).suffix.lower() not in {".png", ".svg"}:
                messagebox.showerror("拡張子を確認", ".pngまたは.svgを指定してください。")
                return
            self.status.set("グラフ保存中…")
            self.submit(self.graph_pool, "export", export_graph_file, reports, labels, identity, filtered, path)

    def export_all(self):
        inputs = self.graph_inputs()
        if inputs is None:
            return
        folder = filedialog.askdirectory(title="全共通指標のPNG保存先")
        if not folder:
            return
        filtered = self.filtered.get()
        destinations = [Path(folder) / graph_filename(identity, filtered) for identity in self.identities]
        if any(path.exists() for path in destinations) and not messagebox.askyesno("上書き確認", "同名のグラフを上書きしますか？"):
            return
        self.batch_done, self.batch_total, self.batch_errors = 0, len(destinations), []
        self.batch_button.configure(state="disabled")
        self.status.set(f"一括保存中: 0/{self.batch_total}")
        self.batch_jobs = iter([(*inputs, identity, filtered, str(path)) for identity, path in zip(self.identities, destinations)])
        for _ in range(max(1, self.graph_workers - 1)):
            self.submit_next_batch()

    def submit_next_batch(self):
        job = next(self.batch_jobs, None)
        if job is not None:
            self.submit(self.graph_pool, "batch", export_graph_file, *job)


def main():
    multiprocessing.freeze_support()
    root = tk.Tk()
    ttk.Style(root).theme_use("clam")
    BenchmarkApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

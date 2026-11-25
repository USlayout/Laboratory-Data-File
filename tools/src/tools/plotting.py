"""Process-safe Matplotlib rendering. No Tk objects cross worker boundaries."""
import io
import re
from functools import lru_cache


def graph_filename(identity, filtered=False, extension="png"):
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", identity[0]).strip("_") or "comparison"
    return stem + ("_filtered" if filtered else "") + "." + extension


@lru_cache(maxsize=1)
def graph_font():
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    return next((n for n in ("Meiryo", "Yu Gothic", "Noto Sans CJK JP", "DejaVu Sans") if n in available), "DejaVu Sans")


def comparison_figure(reports, labels, identity, filtered=False):
    from matplotlib.figure import Figure
    font = graph_font()
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



def render_graph(reports, labels, identity, filtered=False, extension="png", dpi=140):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure = comparison_figure(reports, labels, identity, filtered)
    FigureCanvasAgg(figure)
    stream = io.BytesIO()
    figure.savefig(stream, format=extension, dpi=dpi, bbox_inches="tight")
    return stream.getvalue()


def export_graph_file(reports, labels, identity, filtered, destination):
    from pathlib import Path
    destination = Path(destination)
    data = render_graph(reports, labels, identity, filtered, destination.suffix.lstrip(".").lower(), 180)
    destination.write_bytes(data)
    return str(destination)

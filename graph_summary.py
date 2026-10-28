#!/usr/bin/env python3
"""Create graphs from benchmark *_summary_avg_median.txt files."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

JAPANESE_FONT = next(
    (
        font
        for font in ("Meiryo", "Yu Gothic", "MS Gothic", "Noto Sans CJK JP")
        if any(entry.name == font for entry in font_manager.fontManager.ttflist)
    ),
    None,
)
if JAPANESE_FONT:
    plt.rcParams["font.family"] = JAPANESE_FONT
plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class Summary:
    source: Path
    title: str
    columns: list[str]
    rows: list[dict[str, str]]
    environment: str
    host: str
    os: str


def parse_summary(path: Path) -> Summary:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    table_start = next(
        (index for index, line in enumerate(lines) if line.startswith("|")),
        None,
    )
    if table_start is None or table_start + 2 >= len(lines):
        raise ValueError(f"No Markdown table found in {path}")

    columns = [cell.strip() for cell in lines[table_start].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[table_start + 2 :]:
        if not line.startswith("|"):
            break
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) != len(columns):
            raise ValueError(f"Invalid table row in {path}: {line}")
        rows.append(dict(zip(columns, values)))

    if not rows:
        raise ValueError(f"No data rows found in {path}")
    dataset_root = next(
        (parent for parent in [path.parent, *path.parents] if (parent / "metadata.txt").exists()),
        path.parent,
    )
    metadata = (
        (dataset_root / "metadata.txt").read_text(encoding="utf-8")
        if (dataset_root / "metadata.txt").exists()
        else ""
    )
    host = re.search(r"^ホスト名\s*:\s*(.+)$", metadata, re.MULTILINE)
    os_info_path = dataset_root / "system_info" / "os_info.txt"
    os_info = os_info_path.read_text(encoding="utf-8") if os_info_path.exists() else ""
    os_name = re.search(r'^PRETTY_NAME="([^"]+)"$', os_info, re.MULTILINE)
    environment = next(
        (
            label
            for token, label in (
                ("kvm-docker", "KVM上のDocker"),
                ("docker", "Docker"),
                ("kvm", "KVM"),
                ("host", "ホスト"),
            )
            if token in str(path).lower()
        ),
        "Unknown",
    )
    if not host:
        host_by_environment = {
            "Host": "kitalab",
            "KVM": "ubuntu-bench",
            "Docker": "99ba92c336df",
            "KVM-Docker": "85f7f1633967",
        }
        fallback_host = host_by_environment.get(environment, "Unknown")
    else:
        fallback_host = host.group(1).strip()
    return Summary(
        path,
        lines[0] if lines else path.stem,
        columns,
        rows,
        environment,
        fallback_host,
        os_name.group(1).strip() if os_name else "Ubuntu 26.04.1 LTS",
    )


def metric_columns(summary: Summary) -> list[tuple[str, str, str, str | None]]:
    metrics: list[tuple[str, str, str, str | None]] = []
    for column in summary.columns:
        if column in {"average", "median"}:
            base, statistic = "value", column
        else:
            match = re.fullmatch(r"(.+)_(avg|average|median)(?:_.+)?", column)
            if not match:
                continue
            base, statistic = match.group(1), match.group(2)
        if statistic == "average":
            statistic = "avg"
        stddev = f"{base}_stddev"
        suffix = column.removeprefix(f"{base}_{'average' if statistic == 'avg' else statistic}")
        if suffix:
            stddev += suffix
        metrics.append((base, statistic, column, stddev if stddev in summary.columns else None))
    return metrics


def display_name(column: str) -> str:
    names = {
        "iops": "IOPS",
        "throughput_mib_s": "スループット (MiB/s)",
        "latency_us": "レイテンシ (μs)",
        "throughput": "スループット (Mbps)",
        "latency": "レイテンシ (ms)",
        "value": "測定値",
        "cpu": "CPU",
        "memory_read": "メモリ読み込み",
        "memory_write": "メモリ書き込み",
    }
    return names.get(column, column.replace("_", " "))


def safe_filename(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", "__".join(relative.parts))


def plot_summary(summary: Summary, output_path: Path) -> None:
    metrics = metric_columns(summary)
    if not metrics:
        raise ValueError(f"No average/median metrics found in {summary.source}")

    labels = [row[summary.columns[0]] for row in summary.rows]
    metric_names = list(dict.fromkeys(metric[0] for metric in metrics))
    figure, axes = plt.subplots(
        len(metric_names),
        1,
        figsize=(max(8, len(labels) * 1.5), 4.2 * len(metric_names)),
        squeeze=False,
    )
    x = np.arange(len(labels))
    width = 0.34

    for axis, base in zip(axes[:, 0], metric_names):
        selected = [metric for metric in metrics if metric[0] == base]
        values_by_stat: dict[str, list[float]] = {}
        errors_by_stat: dict[str, list[float] | None] = {}
        for _, statistic, column, stddev_column in selected:
            values_by_stat[statistic] = [float(row[column]) for row in summary.rows]
            errors_by_stat[statistic] = (
                [float(row[stddev_column]) for row in summary.rows]
                if stddev_column
                else None
            )

        offsets = np.linspace(
            -width * (len(values_by_stat) - 1) / 2,
            width * (len(values_by_stat) - 1) / 2,
            len(values_by_stat),
        )
        for offset, (statistic, values) in zip(offsets, values_by_stat.items()):
            axis.bar(
                x + offset,
                values,
                width,
                yerr=errors_by_stat[statistic],
                capsize=3,
                label=statistic.title(),
            )
        axis.set_title(display_name(base))
        axis.set_xticks(x, labels, rotation=25, ha="right")
        axis.set_ylabel("値")
        axis.grid(axis="y", alpha=0.25)
        axis.legend()

    figure.suptitle(summary.title, fontsize=14)
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def benchmark_name(summary: Summary) -> str:
    return re.sub(r"_summary_avg_median(?:_[^.]*)?\.txt$", "", summary.source.name)


def benchmark_display_name(name: str) -> str:
    return {
        "fio": "ストレージ (fio)",
        "sysbench": "CPU・メモリ (sysbench)",
        "iperf3": "ネットワーク (iperf3)",
    }.get(name, name)


def plot_comparison(summaries: list[Summary], output_path: Path) -> None:
    summaries = sorted(summaries, key=lambda summary: summary.environment)
    first = summaries[0]
    metrics = metric_columns(first)
    if not metrics:
        raise ValueError(f"No median metrics found in {first.source}")

    metric_names = list(dict.fromkeys(metric[0] for metric in metrics))
    figure, axes = plt.subplots(
        len(metric_names),
        1,
        figsize=(max(9, len(first.rows) * 2.2), 4.2 * len(metric_names)),
        squeeze=False,
    )
    category_column = first.columns[0]
    categories = [row[category_column] for row in first.rows]
    x = np.arange(len(categories))
    width = 0.75 / len(summaries)
    labels = [
        f"{summary.environment}\nホスト: {summary.host}\nOS: {summary.os.replace(' LTS', '')}"
        for summary in summaries
    ]

    for axis, base in zip(axes[:, 0], metric_names):
        for offset, summary in zip(
            np.linspace(
                -width * (len(summaries) - 1) / 2,
                width * (len(summaries) - 1) / 2,
                len(summaries),
            ),
            summaries,
        ):
            metric = next(
                metric
                for metric in metric_columns(summary)
                if metric[0] == base and metric[1] == "median"
            )
            _, _, column, stddev_column = metric
            row_by_category = {row[category_column]: row for row in summary.rows}
            values = [float(row_by_category[category][column]) for category in categories]
            errors = (
                [
                    float(row_by_category[category][stddev_column])
                    for category in categories
                ]
                if stddev_column
                else None
            )
            axis.bar(
                x + offset,
                values,
                width,
                yerr=errors,
                capsize=3,
                label=summary.environment,
            )
        axis.set_title(display_name(base))
        axis.set_xticks(x, categories, rotation=20, ha="right")
        axis.set_ylabel("中央値")
        axis.grid(axis="y", alpha=0.25)
        axis.legend(
            labels=labels,
            title="環境 / ホスト / OS",
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            fontsize=9,
            title_fontsize=10,
        )

    figure.suptitle(
        f"{benchmark_display_name(benchmark_name(first))}：環境別の中央値比較",
        fontsize=14,
    )
    figure.tight_layout(rect=(0, 0, 0.76, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def write_comparison_index(output_dir: Path, graphs: list[tuple[str, Path]]) -> None:
    with (output_dir / "comparison_index.csv").open(
        "w", newline="", encoding="utf-8"
    ) as output:
        writer = csv.writer(output)
        writer.writerow(["benchmark", "graph_file"])
        writer.writerows(graphs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Graph all benchmark summary_avg_median text files."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory to search recursively (default: repository root).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Graph output directory (default: <root>/Graph).",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = (args.output_dir or root / "Graph").resolve()
    paths = sorted(root.rglob("*_summary_avg_median*.txt"))
    if not paths:
        raise FileNotFoundError(f"No *_summary_avg_median.txt files found under {root}")

    summaries = [parse_summary(path) for path in paths]
    comparison_graphs: list[tuple[str, Path]] = []
    for benchmark, benchmark_summaries in _group_by_benchmark(summaries).items():
        if len(benchmark_summaries) < 2:
            continue
        graph_path = output_dir / f"comparison_{benchmark}.png"
        plot_comparison(benchmark_summaries, graph_path)
        comparison_graphs.append((benchmark, graph_path))
        print(f"Created: {graph_path}")
    write_comparison_index(output_dir, comparison_graphs)
    print(f"Created: {output_dir / 'comparison_index.csv'}")


def _group_by_benchmark(summaries: list[Summary]) -> dict[str, list[Summary]]:
    grouped: dict[str, list[Summary]] = {}
    for summary in summaries:
        grouped.setdefault(benchmark_name(summary), []).append(summary)
    return grouped


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Extract FIO calculation values and reproduce the summary statistics."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median, pstdev


FIELDS = [
    "run",
    "file",
    "test",
    "direction",
    "iops",
    "throughput_bytes_per_second",
    "throughput_mib_s",
    "latency_raw_ns",
    "latency_us",
]


def extract_values(input_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(input_dir.glob("run*/fio_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        test = path.stem.removeprefix("fio_")
        direction = "read" if "read" in test else "write"
        metrics = data["jobs"][0][direction]
        rows.append(
            {
                "run": path.parent.name,
                "file": path.name,
                "test": test,
                "direction": direction,
                "iops": metrics["iops"],
                "throughput_bytes_per_second": metrics["bw_bytes"],
                "throughput_mib_s": metrics["bw_bytes"] / 1024 / 1024,
                "latency_raw_ns": metrics["lat_ns"]["mean"],
                "latency_us": metrics["lat_ns"]["mean"] / 1000,
            }
        )
    if not rows:
        raise FileNotFoundError(f"{input_dir} にFIO JSONが見つかりません。")
    return rows


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def statistics(rows: list[dict[str, object]], field: str) -> tuple[float, float, float]:
    values = [float(row[field]) for row in rows]
    return mean(values), median(values), pstdev(values)


def write_summary(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "FIO summary (run01-run10)",
        "",
        "| test | count | metric | average | median | stddev | unit |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for test in sorted({str(row["test"]) for row in rows}):
        test_rows = [row for row in rows if row["test"] == test]
        metrics = (
            ("iops", "IOPS", "IOPS"),
            ("throughput_mib_s", "throughput", "MiB/sec"),
            ("latency_us", "latency", "us"),
        )
        for field, label, unit in metrics:
            average, middle, deviation = statistics(test_rows, field)
            lines.append(
                f"| {test} | {len(test_rows)} | {label} | "
                f"{average:.2f} | {middle:.2f} | {deviation:.2f} | {unit} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_explanation(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "FIO values used for summary calculation",
        "",
        "Source: run*/fio_*.json, jobs[0].read or jobs[0].write",
        "- IOPS: iops (used directly for the IOPS average, median, and stddev)",
        "- throughput: bw_bytes / 1024 / 1024 -> MiB/sec "
        "(used for the throughput average, median, and stddev)",
        "- latency: lat_ns.mean / 1000 -> us "
        "(used for the latency average, median, and stddev)",
        "",
        "Values in each test are grouped by metric; values from different tests are not mixed.",
        "- average = sum(values) / count",
        "- median = middle value after sorting (or average of the two middle values)",
        "- population standard deviation = sqrt(sum((x - average)^2) / count)",
        "",
        f"Extracted measurements: {len(rows)}",
        "",
        "| run | file | test | IOPS | throughput (MiB/sec) | latency (us) |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['run']} | {row['file']} | {row['test']} | "
            f"{float(row['iops']):.6f} | {float(row['throughput_mib_s']):.6f} | "
            f"{float(row['latency_us']):.6f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    input_dir = args.input_dir.resolve()
    rows = extract_values(input_dir)
    write_csv(rows, input_dir / "fio_values_used.csv")
    write_explanation(rows, input_dir / "fio_values_used.txt")
    write_summary(rows, input_dir / "fio_summary_avg_median.txt")
    print(f"Extracted {len(rows)} measurements.")


if __name__ == "__main__":
    main()
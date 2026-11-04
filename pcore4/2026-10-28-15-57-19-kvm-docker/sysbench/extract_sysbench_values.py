#!/usr/bin/env python3
"""Extract and summarize sysbench values from the KVM-Docker benchmark."""

from __future__ import annotations

import argparse
import csv
import re
import statistics
from pathlib import Path


TESTS = {
    "cpu": (
        "cpu/sysbench_cpu_result.txt",
        re.compile(r"events per second:\s+([0-9.]+)"),
        "events/sec",
        "CPU speed: events per second",
    ),
    "memory_read": (
        "memory/sysbench_memory_read.txt",
        re.compile(r"transferred \(([0-9.]+) MiB/sec\)"),
        "MiB/sec",
        "MiB transferred: read",
    ),
    "memory_write": (
        "memory/sysbench_memory_write.txt",
        re.compile(r"transferred \(([0-9.]+) MiB/sec\)"),
        "MiB/sec",
        "MiB transferred: write",
    ),
}

FIELDS = ["run", "test", "source_file", "source_metric", "value", "unit"]


def extract_values(input_dir: Path) -> list[dict[str, object]]:
    rows = []
    for test, (relative_path, pattern, unit, source_metric) in TESTS.items():
        for path in sorted(input_dir.glob(f"run*/{relative_path}")):
            match = pattern.search(path.read_text(encoding="utf-8"))
            if match is None:
                raise ValueError(f"Could not find {source_metric} in {path}")
            rows.append(
                {
                    "run": path.parent.parent.name,
                    "test": test,
                    "source_file": str(path.relative_to(input_dir)),
                    "source_metric": source_metric,
                    "value": float(match.group(1)),
                    "unit": unit,
                }
            )
    if not rows:
        raise FileNotFoundError(f"No sysbench result files found under {input_dir}")
    return sorted(rows, key=lambda row: (str(row["run"]), str(row["test"])))


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "sysbench summary (KVM-Docker run01-run10)",
        "",
        "| test | count | average | median | stddev | unit |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for test in TESTS:
        values = [float(row["value"]) for row in rows if row["test"] == test]
        unit = next(row["unit"] for row in rows if row["test"] == test)
        lines.append(
            f"| {test} | {len(values)} | {statistics.mean(values):.2f} | "
            f"{statistics.median(values):.2f} | {statistics.pstdev(values):.2f} | "
            f"{unit} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_explanation(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "sysbench KVM-Docker values used for summary calculation",
        "",
        "Each result TXT file contributes one measurement for its test.",
        "",
        "Value source:",
        "- cpu: CPU speed -> events per second",
        "- memory_read: MiB transferred -> MiB/sec",
        "- memory_write: MiB transferred -> MiB/sec",
        "",
        "The value column is used for each test's:",
        "- average = sum of the 10 measurements / 10",
        "- median = average of the 5th and 6th values after sorting",
        "- population standard deviation = sqrt(sum((value - average)^2) / 10)",
        "",
        f"Extracted measurements: {len(rows)}",
        "",
        "| run | test | value | unit | source metric |",
        "|---|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['run']} | {row['test']} | {float(row['value']):.6f} | "
            f"{row['unit']} | {row['source_metric']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract values used by the KVM-Docker sysbench summary."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing the sysbench run directories.",
    )
    args = parser.parse_args()
    input_dir = args.input_dir.resolve()
    rows = extract_values(input_dir)
    write_csv(rows, input_dir / "sysbench_values_used.csv")
    write_summary(rows, input_dir / "sysbench_summary_avg_median.txt")
    write_explanation(rows, input_dir / "sysbench_values_used.txt")
    print(f"Extracted {len(rows)} measurements.")


if __name__ == "__main__":
    main()

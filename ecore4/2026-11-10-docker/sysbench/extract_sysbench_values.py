#!/usr/bin/env python3
"""Extract sysbench values and reproduce the summary statistics."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from statistics import mean, median, pstdev


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
    rows: list[dict[str, object]] = []
    for test, (relative_path, pattern, unit, source_metric) in TESTS.items():
        for path in sorted(input_dir.glob(f"run*/{relative_path}")):
            match = pattern.search(path.read_text(encoding="utf-8"))
            if match is None:
                raise ValueError(f"{path} から {source_metric} を取得できません。")
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
        raise FileNotFoundError(f"{input_dir} にsysbench結果TXTが見つかりません。")
    return sorted(rows, key=lambda row: (str(row["run"]), str(row["test"])))


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "sysbench summary (run01-run10)",
        "",
        "| test | count | average | median | stddev | unit |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for test in TESTS:
        test_rows = [float(row["value"]) for row in rows if row["test"] == test]
        if not test_rows:
            raise ValueError(f"{test} の測定値がありません。")
        lines.append(
            f"| {test} | {len(test_rows)} | {mean(test_rows):.2f} | "
            f"{median(test_rows):.2f} | {pstdev(test_rows):.2f} | "
            f"{TESTS[test][2]} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_explanation(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "sysbench values used for summary calculation",
        "",
        "Source files and values:",
        "- cpu: CPU speed -> events per second",
        "- memory_read: MiB transferred -> MiB/sec",
        "- memory_write: MiB transferred -> MiB/sec",
        "",
        "For each test, only its value column is used; different tests are not mixed.",
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    input_dir = args.input_dir.resolve()
    rows = extract_values(input_dir)
    write_csv(rows, input_dir / "sysbench_values_used.csv")
    write_explanation(rows, input_dir / "sysbench_values_used.txt")
    write_summary(rows, input_dir / "sysbench_summary_avg_median.txt")
    print(f"Extracted {len(rows)} measurements.")


if __name__ == "__main__":
    main()
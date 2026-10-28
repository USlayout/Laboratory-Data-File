#!/usr/bin/env python3
"""Extract and summarize FIO values from the KVM-Docker benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


SOURCE_DIR = Path(
    r"C:\Users\soeno\GitHub\Laboratory-Data-File\2026-10-28-15-57-19-kvm-docker\fio"
)
FIELDS = [
    "run",
    "file",
    "direction",
    "source_file",
    "iops_source",
    "iops",
    "throughput_source",
    "throughput_bytes_per_second",
    "throughput_mib_s",
    "latency_source",
    "latency_raw_ns",
    "latency_us",
]
METRICS = ("iops", "throughput_mib_s", "latency_us")


def extract_values(input_dir: Path) -> list[dict[str, object]]:
    rows = []
    for path in sorted(input_dir.glob("run*/fio_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        file_name = path.name
        direction = "read" if "read" in file_name else "write"
        metrics = data["jobs"][0][direction]
        rows.append(
            {
                "run": path.parent.name,
                "file": file_name,
                "direction": direction,
                "source_file": str(path),
                "iops_source": f"jobs[0].{direction}.iops",
                "iops": metrics["iops"],
                "throughput_source": f"jobs[0].{direction}.bw_bytes",
                "throughput_bytes_per_second": metrics["bw_bytes"],
                "throughput_mib_s": metrics["bw_bytes"] / 1024 / 1024,
                "latency_source": f"jobs[0].{direction}.lat_ns.mean",
                "latency_raw_ns": metrics["lat_ns"]["mean"],
                "latency_us": metrics["lat_ns"]["mean"] / 1000,
            }
        )
    if not rows:
        raise FileNotFoundError(f"No FIO JSON files found under {input_dir}")
    return rows


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "fio summary (KVM-Docker run01-run10)",
        "",
        "| file | count | iops_avg | iops_median | iops_stddev | throughput_mib_s_avg | throughput_mib_s_median | throughput_mib_s_stddev | latency_us_avg | latency_us_median | latency_us_stddev |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for file_name in sorted({str(row["file"]) for row in rows}):
        file_rows = [row for row in rows if row["file"] == file_name]
        values = [
            (
                statistics.mean(float(row[metric]) for row in file_rows),
                statistics.median(float(row[metric]) for row in file_rows),
                statistics.pstdev(float(row[metric]) for row in file_rows),
            )
            for metric in METRICS
        ]
        lines.append(
            f"| {file_name} | {len(file_rows)} | "
            f"{values[0][0]:.2f} | {values[0][1]:.2f} | {values[0][2]:.2f} | "
            f"{values[1][0]:.2f} | {values[1][1]:.2f} | {values[1][2]:.2f} | "
            f"{values[2][0]:.2f} | {values[2][1]:.2f} | {values[2][2]:.2f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_explanation(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "FIO KVM-Docker values used for summary calculation",
        "",
        f"Source directory: {SOURCE_DIR}",
        "Each JSON file contributes one measurement for its FIO test.",
        "",
        "Value source and conversion:",
        "- IOPS: jobs[0].read/write.iops -> iops",
        "- throughput: jobs[0].read/write.bw_bytes / 1024 / 1024 -> throughput_mib_s",
        "- latency: jobs[0].read/write.lat_ns.mean / 1,000 -> latency_us",
        "",
        "For each FIO file, these columns are used to calculate:",
        "- average = sum of the 10 measurements / 10",
        "- median = average of the 5th and 6th values after sorting",
        "- population standard deviation = sqrt(sum((value - average)^2) / 10)",
        "",
        f"Extracted measurements: {len(rows)}",
        "",
        "| run | file | IOPS | throughput (MiB/s) | latency (us) |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['run']} | {row['file']} | {float(row['iops']):.6f} | "
            f"{float(row['throughput_mib_s']):.6f} | {float(row['latency_us']):.6f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract values used by the KVM-Docker FIO summary."
    )
    parser.add_argument("--input-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    args = parser.parse_args()
    rows = extract_values(args.input_dir.resolve())
    output_dir = args.output_dir.resolve()
    write_csv(rows, output_dir / "fio_values_used_kvm_docker.csv")
    write_summary(rows, output_dir / "fio_summary_avg_median_kvm_docker.txt")
    write_explanation(rows, output_dir / "fio_values_used_kvm_docker.txt")
    print(f"Extracted {len(rows)} measurements.")


if __name__ == "__main__":
    main()

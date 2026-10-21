#!/usr/bin/env python3
"""Extract the FIO values used by the summary calculation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


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
                "source_file": str(path.relative_to(input_dir)),
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


def write_explanation(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "FIO host values used for summary calculation",
        "",
        "Each JSON file contributes one measurement for its FIO test.",
        "",
        "Value source and conversion:",
        "- IOPS: jobs[0].read/write.iops -> iops",
        "- throughput: jobs[0].read/write.bw_bytes / 1024 / 1024 -> throughput_mib_s",
        "- latency: jobs[0].read/write.lat_ns.mean / 1,000 -> latency_us",
        "",
        "For each FIO file, the iops, throughput_mib_s, and latency_us columns are used to calculate:",
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
            f"| {row['run']} | {row['file']} | {row['iops']:.6f} | "
            f"{row['throughput_mib_s']:.6f} | {row['latency_us']:.6f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract values used by the host FIO summary."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing the FIO run directories.",
    )
    args = parser.parse_args()
    input_dir = args.input_dir.resolve()
    rows = extract_values(input_dir)
    csv_path = input_dir / "fio_values_used.csv"
    txt_path = input_dir / "fio_values_used.txt"
    write_csv(rows, csv_path)
    write_explanation(rows, txt_path)
    print(f"Extracted {len(rows)} measurements.")
    print(f"CSV: {csv_path}")
    print(f"Explanation: {txt_path}")


if __name__ == "__main__":
    main()

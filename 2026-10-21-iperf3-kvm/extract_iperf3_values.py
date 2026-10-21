#!/usr/bin/env python3
"""Extract the iperf3 values used by the summary calculation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def extract_values(input_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for json_path in sorted(input_dir.glob("**/iperf3/iperf3_*.json")):
        data = json.loads(json_path.read_text(encoding="utf-8"))
        end = data["end"]
        protocol = json_path.stem.removeprefix("iperf3_").upper()

        if protocol == "TCP":
            throughput_bps = end["sum_sent"]["bits_per_second"]
            latency_raw = end["streams"][0]["sender"]["mean_rtt"]
            latency_metric = "mean_rtt"
            latency_unit = "us"
            latency_ms = latency_raw / 1000
            throughput_source = "end.sum_sent.bits_per_second"
            latency_source = "end.streams[0].sender.mean_rtt"
        elif protocol == "UDP":
            throughput_bps = end["sum"]["bits_per_second"]
            latency_raw = end["sum"]["jitter_ms"]
            latency_metric = "jitter_ms"
            latency_unit = "ms"
            latency_ms = latency_raw
            throughput_source = "end.sum.bits_per_second"
            latency_source = "end.sum.jitter_ms"
        else:
            raise ValueError(f"Unsupported protocol in {json_path}: {protocol}")

        rows.append(
            {
                "run": json_path.parent.parent.name,
                "protocol": protocol,
                "source_file": str(json_path.relative_to(input_dir)),
                "throughput_source": throughput_source,
                "throughput_bits_per_second": throughput_bps,
                "throughput_mbps": throughput_bps / 1_000_000,
                "latency_source": latency_source,
                "latency_metric": latency_metric,
                "latency_raw": latency_raw,
                "latency_raw_unit": latency_unit,
                "latency_ms": latency_ms,
            }
        )

    if not rows:
        raise FileNotFoundError(f"No iperf3 JSON files found under {input_dir}")
    return rows


def write_values_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    fieldnames = [
        "run",
        "protocol",
        "source_file",
        "throughput_source",
        "throughput_bits_per_second",
        "throughput_mbps",
        "latency_source",
        "latency_metric",
        "latency_raw",
        "latency_raw_unit",
        "latency_ms",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_explanation(rows: list[dict[str, object]], output_path: Path) -> None:
    lines = [
        "iperf3 values used for summary calculation",
        "",
        "Each JSON file contributes one measurement for its protocol.",
        "",
        "Value source and calculation use:",
        "- TCP throughput: end.sum_sent.bits_per_second / 1,000,000 -> throughput_mbps",
        "- UDP throughput: end.sum.bits_per_second / 1,000,000 -> throughput_mbps",
        "- TCP latency: end.streams[0].sender.mean_rtt / 1,000 -> latency_ms",
        "- UDP latency: end.sum.jitter_ms -> latency_ms (already in milliseconds)",
        "",
        "For each protocol, the *_mbps and latency_ms columns are used to calculate:",
        "- average = sum of the 10 measurements / 10",
        "- median = middle value after sorting the 10 measurements",
        "- population standard deviation = sqrt(sum((value - average)^2) / 10)",
        "",
        f"Extracted measurements: {len(rows)}",
        "",
        "Raw and converted values:",
        "",
        "| run | protocol | throughput (Mbps) | latency metric | latency (ms) |",
        "|---|---|---:|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['run']} | {row['protocol']} | "
            f"{row['throughput_mbps']:.6f} | {row['latency_metric']} | "
            f"{row['latency_ms']:.6f} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the iperf3 JSON values used for summary statistics."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing the iperf3 run directories.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="CSV output path (default: <input-dir>/iperf3_values_used.csv).",
    )
    parser.add_argument(
        "--output-txt",
        type=Path,
        default=None,
        help="Explanation output path (default: <input-dir>/iperf3_values_used.txt).",
    )
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_csv = args.output_csv or input_dir / "iperf3_values_used.csv"
    output_txt = args.output_txt or input_dir / "iperf3_values_used.txt"
    rows = extract_values(input_dir)
    write_values_csv(rows, output_csv)
    write_explanation(rows, output_txt)
    print(f"Extracted {len(rows)} measurements.")
    print(f"CSV: {output_csv}")
    print(f"Explanation: {output_txt}")


if __name__ == "__main__":
    main()

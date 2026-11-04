#!/usr/bin/env python3
"""Extract and summarize iperf3 values from the KVM-Docker benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


FIELDS = [
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


def extract_values(input_dir: Path) -> list[dict[str, object]]:
    rows = []
    for path in sorted(input_dir.glob("**/iperf3/iperf3_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        end = data["end"]
        protocol = path.stem.removeprefix("iperf3_").upper()
        if protocol == "TCP":
            throughput_source = "end.sum_sent.bits_per_second"
            throughput_bps = end["sum_sent"]["bits_per_second"]
            latency_source = "end.streams[0].sender.mean_rtt"
            latency_metric = "mean_rtt"
            latency_raw = end["streams"][0]["sender"]["mean_rtt"]
            latency_unit = "us"
            latency_ms = latency_raw / 1000
        elif protocol == "UDP":
            throughput_source = "end.sum.bits_per_second"
            throughput_bps = end["sum"]["bits_per_second"]
            latency_source = "end.sum.jitter_ms"
            latency_metric = "jitter_ms"
            latency_raw = end["sum"]["jitter_ms"]
            latency_unit = "ms"
            latency_ms = latency_raw
        else:
            raise ValueError(f"Unsupported protocol in {path}: {protocol}")
        rows.append(
            {
                "run": path.parent.parent.name,
                "protocol": protocol,
                "source_file": str(path.relative_to(input_dir)),
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


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "iperf3 summary (KVM-Docker run01-run10)",
        "",
        "| protocol | count | throughput_avg_mbps | throughput_median_mbps | throughput_stddev_mbps | latency_metric | latency_avg_ms | latency_median_ms | latency_stddev_ms |",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|",
    ]
    for protocol in ("TCP", "UDP"):
        protocol_rows = [row for row in rows if row["protocol"] == protocol]
        throughput = [float(row["throughput_mbps"]) for row in protocol_rows]
        latency = [float(row["latency_ms"]) for row in protocol_rows]
        lines.append(
            f"| {protocol} | {len(protocol_rows)} | {statistics.mean(throughput):.3f} | "
            f"{statistics.median(throughput):.3f} | {statistics.pstdev(throughput):.3f} | "
            f"{protocol_rows[0]['latency_metric']} | {statistics.mean(latency):.6f} | "
            f"{statistics.median(latency):.6f} | {statistics.pstdev(latency):.6f} |"
        )
    lines.append("")
    lines.append(
        "Note: TCP latency uses `mean_rtt` from the sender side. "
        "UDP latency uses `jitter_ms`."
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_explanation(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        "iperf3 KVM-Docker values used for summary calculation",
        "",
        "Each JSON file contributes one measurement for its protocol.",
        "",
        "Value source and conversion:",
        "- TCP throughput: end.sum_sent.bits_per_second / 1,000,000 -> throughput_mbps",
        "- UDP throughput: end.sum.bits_per_second / 1,000,000 -> throughput_mbps",
        "- TCP latency: end.streams[0].sender.mean_rtt / 1,000 -> latency_ms",
        "- UDP latency: end.sum.jitter_ms -> latency_ms (already milliseconds)",
        "",
        "The throughput_mbps and latency_ms columns are used for each protocol's:",
        "- average = sum of the 10 measurements / 10",
        "- median = average of the 5th and 6th values after sorting",
        "- population standard deviation = sqrt(sum((value - average)^2) / 10)",
        "",
        f"Extracted measurements: {len(rows)}",
        "",
        "| run | protocol | throughput (Mbps) | latency metric | latency (ms) |",
        "|---|---|---:|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['run']} | {row['protocol']} | {float(row['throughput_mbps']):.6f} | "
            f"{row['latency_metric']} | {float(row['latency_ms']):.6f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract values used by the KVM-Docker iperf3 summary."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing the iperf3 run directories.",
    )
    args = parser.parse_args()
    input_dir = args.input_dir.resolve()
    rows = extract_values(input_dir)
    write_csv(rows, input_dir / "iperf3_values_used.csv")
    write_summary(rows, input_dir / "iperf3_summary_avg_median.txt")
    write_explanation(rows, input_dir / "iperf3_values_used.txt")
    print(f"Extracted {len(rows)} measurements.")


if __name__ == "__main__":
    main()

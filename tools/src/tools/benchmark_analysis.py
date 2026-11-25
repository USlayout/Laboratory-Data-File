"""Benchmark parsers and reproducible statistics; no GUI dependencies."""
from __future__ import annotations

import csv
import json
import math
import re
import statistics as st
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCHEMA = "benchmark-analysis-v1"


def describe(values: list[float], warning_percent: float = 20) -> dict:
    if not values or any(not math.isfinite(x) for x in values):
        raise ValueError("有限の測定値が必要です")
    q1 = q3 = None
    indices = []
    if len(values) >= 4:
        q1, _, q3 = st.quantiles(values, n=4, method="inclusive")
        iqr = q3 - q1
        indices = [i for i, x in enumerate(values) if x < q1 - 1.5 * iqr or x > q3 + 1.5 * iqr]
    clean = [x for i, x in enumerate(values) if i not in indices]
    warnings = []
    if len(values) < 4:
        warnings.append("4件未満のため外れ値判定なし")
    percent = len(indices) / len(values) * 100
    if indices:
        warnings.append(f"外れ値 {len(indices)}/{len(values)}件 ({percent:.1f}%)")
    if indices and percent >= warning_percent:
        warnings.append("外れ値が多いため測定条件を確認してください")
    return dict(n=len(values), mean=st.mean(values), median=st.median(values),
                stddev=st.stdev(values) if len(values) > 1 else None,
                minimum=min(values), maximum=max(values), q1=q1, q3=q3,
                outlier_indices=indices, outlier_percent=percent, warnings=warnings,
                filtered=dict(n=len(clean), mean=st.mean(clean), median=st.median(clean),
                              stddev=st.stdev(clean) if len(clean) > 1 else None))


def parse_file(path: Path) -> list[tuple[str, str, float]]:
    name = path.name
    text = path.read_text(encoding="utf-8-sig")
    if name.startswith("sysbench_"):
        if name == "sysbench_cpu_result.txt":
            match = re.search(r"events per second:\s*([\d.]+)", text)
            key, unit = "sysbench.cpu.events", "events/s"
        else:
            match = re.search(r"\(([\d.]+)\s+MiB/sec\)", text)
            key, unit = f"sysbench.memory.{('read' if 'read' in name else 'write')}", "MiB/s"
        if not match:
            raise ValueError("測定結果の数値がありません")
        return [(key, unit, float(match[1]))]
    data = json.loads(text)
    if data.get("error"):
        raise ValueError(str(data["error"]))
    if name.startswith("fio_"):
        jobs = data["jobs"]
        if not jobs or any(j.get("error", 0) for j in jobs):
            raise ValueError("fioジョブが失敗しています")
        operation = "read" if "read" in name else "write"
        rows = [j[operation] for j in jobs]
        prefix = "fio." + path.stem.removeprefix("fio_")
        result = [(prefix + ".throughput", "MiB/s", sum(r["bw_bytes"] if "bw_bytes" in r else r["bw"] * 1024 for r in rows) / 1048576),
                  (prefix + ".iops", "IOPS", sum(r["iops"] for r in rows))]
        # 複数ジョブはI/O件数で重み付け。fioのgroup_reportingも1結果として扱う。
        weighted = []
        for row in rows:
            latency = next(((row[k]["mean"] / scale) for k, scale in
                            (("lat_ns", 1000), ("lat_us", 1), ("lat_ms", .001)) if k in row), None)
            if latency is not None and row.get("total_ios", 0) > 0:
                weighted.append((latency, row["total_ios"]))
        if len(weighted) == len(rows):
            result.append((prefix + ".latency", "µs", sum(x * n for x, n in weighted) / sum(n for _, n in weighted)))
        return result
    protocol = "udp" if "udp" in name else "tcp"
    end = data["end"]
    # 送信側を受信側として扱わない。
    received = end.get("sum_received")
    if received is None and end.get("sum", {}).get("sender") is False:
        received = end["sum"]
    if received is None:
        raise ValueError("受信側の集計がありません")
    result = [(f"iperf3.{protocol}.throughput", "Mbit/s", received["bits_per_second"] / 1e6)]
    if protocol == "udp":
        for field, metric, unit in (("jitter_ms", "jitter", "ms"), ("lost_percent", "loss", "%")):
            if field in received:
                result.append((f"iperf3.udp.{metric}", unit, received[field]))
    return result


def analyze_folder(folder: Path, environment: str, warning_percent: float = 20) -> dict:
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError("測定フォルダを選択してください")
    if not 0 <= warning_percent <= 100 or not math.isfinite(warning_percent):
        raise ValueError("注意閾値は0～100%にしてください")
    grouped = defaultdict(list)
    warnings, metadata = [], {}
    names = {"sysbench_cpu_result.txt", "sysbench_memory_read.txt", "sysbench_memory_write.txt",
             "fio_seq_read.json", "fio_seq_write.json", "fio_rand_read.json", "fio_rand_write.json",
             "iperf3_tcp.json", "iperf3_udp.json"}
    import os
    for directory, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in {"venv", ".venv", ".git", "__pycache__", "analysis_output"})
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(folder).as_posix()
            if name == "metadata.txt":
                metadata[relative] = path.read_text(encoding="utf-8-sig", errors="replace")
            if name == "FAILED.txt" or (name.startswith("iperf3_") and ".attempt" in name and name.endswith(".json")):
                warnings.append(f"失敗・再試行の記録: {relative}")
            if name not in names:
                continue
            try:
                parsed = parse_file(path)
                if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for _, _, v in parsed):
                    raise ValueError("負数・非有限の測定値です")
                for key, unit, value in parsed:
                    grouped[key, unit].append(dict(value=value, source=relative))
            except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
                warnings.append(f"読み込み除外: {relative}: {exc}")
    if not grouped:
        raise ValueError("対応する有効な測定データがありません。\n" + "\n".join(warnings[:8]))
    metrics = []
    for (key, unit), samples in sorted(grouped.items()):
        metrics.append(dict(key=key, unit=unit, samples=samples,
                            **describe([s["value"] for s in samples], warning_percent)))
    if len(metadata) > 1:
        warnings.append("複数のmetadata.txtがあります。同じ環境・同じ測定条件のフォルダだけを選んだか確認してください。")
    return dict(schema=SCHEMA, environment=environment.strip() or folder.name, source=str(folder),
                created=datetime.now().astimezone().isoformat(timespec="seconds"),
                policy=dict(stddev="sample (ddof=1)", outliers="Tukey 1.5 IQR; inclusive quartiles; n>=4",
                            warning_percent=warning_percent, excluded_automatically=False),
                metadata=metadata, warnings=warnings, metrics=metrics)


def save_analysis(report: dict, destination: Path) -> None:
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    with destination.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as out:
        fields = ["key", "unit", "n", "mean", "median", "stddev", "minimum", "maximum", "outlier_percent", "warnings"]
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for metric in report["metrics"]:
            writer.writerow({**metric, "warnings": "; ".join(metric["warnings"])})
    with destination.with_name(destination.stem + "_samples.csv").open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["metric", "unit", "source", "value", "outlier"])
        for metric in report["metrics"]:
            for i, sample in enumerate(metric["samples"]):
                writer.writerow([metric["key"], metric["unit"], sample["source"], sample["value"], i in metric["outlier_indices"]])


def load_analysis(path: Path) -> dict:
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if report.get("schema") != SCHEMA or not isinstance(report.get("metrics"), list) or not report["metrics"]:
        raise ValueError("このツールで保存した解析JSONを選択してください")
    seen = set()
    for m in report["metrics"]:
        identity = (m["key"], m["unit"])
        if identity in seen:
            raise ValueError("指標が重複しています")
        seen.add(identity)
        values = [s["value"] for s in m["samples"]]
        # 保存された集計値を信頼せず、生データから同じ規則で再計算。
        m.update(describe(values, report["policy"]["warning_percent"]))
    return report


def common_metrics(reports: list[dict]) -> list[tuple[str, str]]:
    if not reports:
        return []
    keys = [{(m["key"], m["unit"]) for m in r["metrics"]} for r in reports]
    return sorted(set.intersection(*keys))

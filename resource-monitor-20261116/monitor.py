#!/usr/bin/env python3
"""Small Linux web monitor. Python standard library only; no background sampler."""
import argparse
import json
import math
import os
import re
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    import pwd
except ImportError:  # Allows fixture tests on Windows.
    pwd = None


def natural_key(value):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", str(value))]


def process_stat(value):
    """comm may contain spaces and ')' so splitting the whole line is unsafe."""
    start, end = value.find("("), value.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("Invalid process stat")
    fields = value[end + 1:].split()
    return {"name": value[start + 1:end][:160], "state": fields[0],
            "ticks": int(fields[11]) + int(fields[12]),
            "priority": int(fields[15]), "nice": int(fields[16]),
            "threads": int(fields[17]), "start": int(fields[19]),
            "virtual": int(fields[20]), "rss_pages": int(fields[21])}


def read(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return default


def number(path):
    try:
        return int(read(path))
    except ValueError:
        return None


def cpulist(value):
    result = set()
    if not value.strip():
        return result
    for part in value.split(","):
        if not re.fullmatch(r"\d+(?:-\d+)?", part.strip()):
            raise ValueError("CPU list must look like 0-7,20-23")
        ends = [int(x) for x in part.split("-")]
        start, end = ends[0], ends[-1]
        if start > end or end > 65535:
            raise ValueError("Invalid CPU range")
        result.update(range(start, end + 1))
    return result


def cpu_times(proc):
    result = {}
    for line in read(proc / "stat").splitlines():
        fields = line.split()
        if fields and re.fullmatch(r"cpu\d*", fields[0]):
            # guest and guest_nice are already included in user and nice.
            values = [int(x) for x in fields[1:9]]
            values += [0] * (8 - len(values))
            result[fields[0]] = values
    return result


def utilization(before, after):
    if before is None:
        return {"usage": None, "user": 0, "system": 0, "wait": 0}
    delta = [max(0, b - a) for a, b in zip(before, after)]
    total = sum(delta)
    if not total:
        return {"usage": None, "user": 0, "system": 0, "wait": 0}
    percent = lambda n: round(100 * n / total, 1)
    return {"usage": percent(total - delta[3] - delta[4]),
            "user": percent(delta[0] + delta[1]),
            "system": percent(delta[2] + delta[5] + delta[6] + delta[7]),
            "wait": percent(delta[4])}


class Monitor:
    def __init__(self, proc=Path("/proc"), sysfs=Path("/sys"), interval=2,
                 pcores=None, ecores=None, processes=True):
        self.proc, self.sysfs, self.interval = proc, sysfs, interval
        self.manual = pcores is not None or ecores is not None
        self.pcores, self.ecores = pcores or set(), ecores or set()
        self.previous = cpu_times(proc)
        self.energy = {}
        self.cached = None
        self.sampled = time.monotonic()
        self.discovered = float("-inf")
        self.sensors = []
        self.rapl = []
        self.processes_enabled = processes
        self.process_previous = {}
        self.process_time = None
        self.users = {}
        self.clock_ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self.page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        self.model = next((line.split(":", 1)[1].strip()
                           for line in read(proc / "cpuinfo").splitlines()
                           if line.startswith("model name")), "Linux CPU")
        self.hostname = socket.gethostname()
        self.discover(self.sampled)
        self.power(self.sampled)  # Prime energy counters without a sleeping thread.
        if processes:
            self.processes(self.sampled, 0)

    def discover(self, now):
        if now - self.discovered < 30:
            return
        self.discovered = now
        if not self.manual:
            pmu = self.sysfs / "bus/event_source/devices"
            self.pcores = cpulist(read(pmu / "cpu_core/cpus"))
            self.ecores = cpulist(read(pmu / "cpu_atom/cpus"))
        self.sensors = []
        for hw in sorted((self.sysfs / "class/hwmon").glob("hwmon*"), key=natural_key):
            name = read(hw / "name", hw.name)
            for kind, pattern in (("temperature", "temp*_input"),
                                  ("power", "power*_input"),
                                  ("power", "power*_average")):
                for path in sorted(hw.glob(pattern), key=natural_key):
                    stem = path.name.rsplit("_", 1)[0]
                    if path.name.endswith("_average") and (hw / (stem + "_input")).exists():
                        continue
                    label = read(hw / (stem + "_label"), stem)
                    self.sensors.append((kind, name + " · " + label, path))
        if not any(s[0] == "temperature" for s in self.sensors):
            for zone in sorted((self.sysfs / "class/thermal").glob("thermal_zone*")):
                self.sensors.append(("temperature", read(zone / "type", zone.name), zone / "temp"))
        # Resolve class symlinks; enumerate real hierarchy too for nested RAPL zones.
        paths = set()
        for root in (self.sysfs / "class/powercap", self.sysfs / "devices/virtual/powercap"):
            for path in root.glob("*/energy_uj"):
                paths.add(path.resolve())
            for path in root.rglob("energy_uj"):
                paths.add(path.resolve())
        self.rapl = sorted(paths)
        self.energy = {key: value for key, value in self.energy.items() if key in paths}

    def temperatures(self, cores):
        result = []
        for kind, label, path in self.sensors:
            if kind != "temperature":
                continue
            value = number(path)
            item = {"label": label, "celsius": round(value / 1000, 1) if value is not None else None}
            order = (1, natural_key(label))
            if label.startswith("coretemp · "):
                package_label = read(path.parent / "temp1_label")
                package = re.fullmatch(r"Package id (\d+)", package_label)
                core = re.fullmatch(r"coretemp · Core (\d+)", label)
                if package:
                    package_id = package[1]
                    matches = [c for c in cores if c["package"] == package_id
                               and core and c["core"] == core[1]]
                    ids = sorted(c["id"] for c in matches)
                    groups = {c["group"] for c in matches}
                    group = next(iter(groups)) if len(groups) == 1 else "U"
                    if core:
                        if ids:
                            item["label"] = (f"{group if group != 'U' else '未判別'} · CPU "
                                             + ",".join(map(str, ids))
                                             + f" · Core {core[1]} / package {package_id}")
                        order = (0, int(package_id), 1, {"P": 0, "E": 1, "U": 2}[group], int(core[1]))
                    else:
                        order = (0, int(package_id), 0, 0, 0)
                    item.update({"package": int(package_id), "cpus": ids, "group": group})
            item["_order"] = order
            result.append(item)
        result.sort(key=lambda item: item["_order"])
        for item in result:
            del item["_order"]
        return result

    def processes(self, now, memory_total):
        if not self.processes_enabled:
            return {"enabled": False, "items": [], "total": 0, "running": 0, "unreadable": 0}
        previous, current, items, users = self.process_previous, {}, [], {}
        elapsed = now - self.process_time if self.process_time is not None else 0
        unreadable = 0
        with os.scandir(self.proc) as entries:
            for entry in entries:
                if not entry.name.isdigit():
                    continue
                try:
                    stat = process_stat(read(Path(entry.path) / "stat"))
                    uid = entry.stat(follow_symlinks=False).st_uid
                    if uid not in users:
                        username = self.users.get(uid)
                        if username is None:
                            try:
                                username = pwd.getpwuid(uid).pw_name if pwd else str(uid)
                            except KeyError:
                                username = str(uid)
                        users[uid] = username
                    pid = int(entry.name)
                    old = previous.get(pid)
                    cpu = None
                    if old and old[0] == stat["start"] and elapsed > 0:
                        cpu = round(max(0, stat["ticks"] - old[1]) / self.clock_ticks / elapsed * 100, 1)
                    current[pid] = (stat["start"], stat["ticks"])
                    rss = max(0, stat["rss_pages"]) * self.page_size
                    items.append({"pid": pid, "user": users[uid], "state": stat["state"],
                                  "cpu": cpu, "memory": round(rss / memory_total * 100, 2) if memory_total else 0,
                                  "rss": rss, "virtual": stat["virtual"], "priority": stat["priority"],
                                  "nice": stat["nice"], "threads": stat["threads"],
                                  "seconds": round(stat["ticks"] / self.clock_ticks, 2), "name": stat["name"]})
                except (OSError, ValueError, IndexError):
                    # Processes may exit or become unreadable during collection.
                    unreadable += 1
        self.process_previous, self.process_time, self.users = current, now, users
        return {"enabled": True, "items": items, "total": len(items),
                "running": sum(p["state"] == "R" for p in items), "unreadable": unreadable}

    def power(self, now):
        result = []
        for path in self.rapl:
            current = number(path)
            label = read(path.parent / "name", path.parent.name)
            watts, status = None, "取得不可（権限・ドライバーを確認）"
            if current is not None:
                previous = self.energy.get(path)
                status = "次の更新で表示"
                if previous and now > previous[1]:
                    diff = current - previous[0]
                    if diff < 0:
                        maximum = number(path.parent / "max_energy_range_uj")
                        diff = diff + maximum if maximum else -1
                    # Long gaps may span multiple wraps: re-prime instead of guessing.
                    if diff >= 0 and now - previous[1] <= max(30, self.interval * 3):
                        watts = round(diff / (now - previous[1]) / 1_000_000, 2)
                        status = "RAPL / 区間平均"
                self.energy[path] = (current, now)
            else:
                self.energy.pop(path, None)
            result.append({"label": label, "watts": watts, "status": status})
        for kind, label, path in self.sensors:
            if kind == "power":
                value = number(path)
                result.append({"label": label, "watts": round(value / 1e6, 2) if value is not None else None,
                               "status": "hwmon" if value is not None else "取得不可"})
        return result

    def sample(self):
        now = time.monotonic()
        if self.cached is not None and now - self.sampled < self.interval:
            return self.cached
        self.discover(now)
        times = cpu_times(self.proc)
        if "cpu" not in times:
            raise RuntimeError("/proc/stat is unavailable; run this monitor on Ubuntu/Linux")
        cores = []
        for key, counters in times.items():
            if key == "cpu":
                continue
            index = int(key[3:])
            topology = self.sysfs / f"devices/system/cpu/cpu{index}/topology"
            cores.append({"id": index,
                          "group": "P" if index in self.pcores else "E" if index in self.ecores else "U",
                          "core": read(topology / "core_id", "?"),
                          "package": read(topology / "physical_package_id", "?"),
                          **utilization(self.previous.get(key), counters)})
        mem = {}
        for line in read(self.proc / "meminfo").splitlines():
            key, value = line.split(":", 1)
            mem[key] = int(value.split()[0]) * 1024
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", mem.get("MemFree", 0))
        self.cached = {"hostname": self.hostname, "model": self.model, "timestamp": time.time(),
                       "interval": self.interval, "classification": "manual" if self.manual else "Intel hybrid PMU",
                       "cpu": utilization(self.previous.get("cpu"), times["cpu"]),
                       "cores": sorted(cores, key=lambda c: c["id"]),
                       "memory": {"total": total, "used": max(0, total - available),
                                  "available": available, "swap_total": mem.get("SwapTotal", 0),
                                  "swap_used": max(0, mem.get("SwapTotal", 0) - mem.get("SwapFree", 0))},
                       "temperatures": self.temperatures(cores), "power": self.power(now),
                       "processes": self.processes(now, total)}
        self.previous, self.sampled = times, now
        return self.cached


def make_handler(monitor):
    page = Path(__file__).with_name("index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            try:
                if path == "/":
                    body, content_type = page, "text/html; charset=utf-8"
                elif path == "/api/metrics":
                    body = json.dumps(monitor.sample(), ensure_ascii=False, allow_nan=False).encode()
                    content_type = "application/json; charset=utf-8"
                elif path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                    return
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except (OSError, ValueError, RuntimeError) as error:
                print(f"Metrics error: {error}", file=sys.stderr)
                self.send_error(503, "Metrics unavailable")

        def log_message(self, *_):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=float, default=2, help="Sampling interval in seconds (>= 0.5)")
    parser.add_argument("--p-cores", help="Logical CPU IDs, e.g. 0-7")
    parser.add_argument("--e-cores", help="Logical CPU IDs, e.g. 8-19")
    parser.add_argument("--no-processes", action="store_true", help="Disable process collection to reduce overhead")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("Run this program on Ubuntu/Linux (/proc and /sys required)")
    if not math.isfinite(args.interval) or args.interval < 0.5:
        parser.error("--interval must be a finite number >= 0.5")
    try:
        p = cpulist(args.p_cores) if args.p_cores is not None else None
        e = cpulist(args.e_cores) if args.e_cores is not None else None
        if (p or set()) & (e or set()):
            raise ValueError("P/E CPU lists must not overlap")
    except ValueError as error:
        parser.error(str(error))
    monitor = Monitor(interval=args.interval, pcores=p, ecores=e, processes=not args.no_processes)
    server = HTTPServer((args.host, args.port), make_handler(monitor))
    print(f"Monitor: http://{args.host}:{args.port} (interval: {args.interval}s)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

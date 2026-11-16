import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
from http.server import HTTPServer

spec = importlib.util.spec_from_file_location("monitor", Path(__file__).parents[1] / "monitor.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent, prefix="fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proc, self.sysfs = self.root / "proc", self.root / "sys"
        self.write("proc/stat", "cpu 100 0 20 800 10 0 0 0 50 0\ncpu0 100 0 20 800 10 0 0 0 50 0\ncpu1 0 0 0 900 0 0 0 0 0 0\n")
        self.write("proc/cpuinfo", "model name : Fixture CPU\n")
        self.write("proc/meminfo", "MemTotal: 1000 kB\nMemAvailable: 600 kB\nSwapTotal: 100 kB\nSwapFree: 80 kB\n")
        self.write("sys/bus/event_source/devices/cpu_core/cpus", "0")
        self.write("sys/bus/event_source/devices/cpu_atom/cpus", "1")
        self.write("sys/class/hwmon/hwmon0/name", "coretemp")
        self.write("sys/class/hwmon/hwmon0/temp1_input", "55000")
        self.write("sys/class/hwmon/hwmon0/temp1_label", "Package id 0")
        self.write("sys/class/powercap/intel-rapl-0/name", "package-0")
        self.write("sys/class/powercap/intel-rapl-0/energy_uj", "9000000")
        self.write("sys/class/powercap/intel-rapl-0/max_energy_range_uj", "10000000")

    def write(self, path, value):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def monitor(self, **kwargs):
        return m.Monitor(self.proc, self.sysfs, **kwargs)

    def test_cpu_guest_not_counted_twice(self):
        before = m.cpu_times(self.proc)["cpu"]
        after = [150, 0, 40, 820, 20, 0, 0, 0]
        usage = m.utilization(before, after)
        self.assertEqual(usage, {"usage": 70.0, "user": 50.0, "system": 20.0, "wait": 10.0})
        self.assertIsNone(m.utilization(None, after)["usage"])

    def test_classification_memory_and_temperature(self):
        data = self.monitor().sample()
        self.assertEqual([c["group"] for c in data["cores"]], ["P", "E"])
        self.assertEqual(data["memory"]["used"], 400 * 1024)
        self.assertEqual(data["memory"]["swap_used"], 20 * 1024)
        self.assertEqual(data["temperatures"][0]["celsius"], 55.0)
        manual = self.monitor(pcores={1}).sample()
        self.assertEqual([c["group"] for c in manual["cores"]], ["U", "P"])

    def test_cache_shared_and_power_wrap(self):
        with patch.object(m.time, "monotonic", return_value=100):
            monitor = self.monitor()
        self.write("sys/class/powercap/intel-rapl-0/energy_uj", "1000000")
        with patch.object(m.time, "monotonic", return_value=102):
            first = monitor.sample()
        self.assertEqual(first["power"][0]["watts"], 1.0)
        with patch.object(m.time, "monotonic", return_value=103):
            self.assertIs(first, monitor.sample())
        with patch.object(m.time, "monotonic", return_value=200):
            self.assertIsNone(monitor.sample()["power"][0]["watts"])

    def test_missing_sensors_and_recovery(self):
        monitor = self.monitor()
        energy = self.root / "sys/class/powercap/intel-rapl-0/energy_uj"
        energy.unlink()
        self.assertIsNone(monitor.power(monitor.sampled + 2)[0]["watts"])
        energy.write_text("100")
        self.assertIsNone(monitor.power(monitor.sampled + 4)[0]["watts"])
        energy.write_text("2000100")
        self.assertEqual(monitor.power(monitor.sampled + 6)[0]["watts"], 1)
        (self.root / "sys/class/hwmon/hwmon0/temp1_input").unlink()
        self.assertIsNone(monitor.sample()["temperatures"][0]["celsius"])

    def test_ranges(self):
        self.assertEqual(m.cpulist("0-2,5"), {0, 1, 2, 5})
        for value in ("3-1", "0-999999999", "abc", "0,,1"):
            with self.assertRaises(ValueError):
                m.cpulist(value)

    def put_process(self, pid=123, ticks=100, start=1000, name="worker (a) )", rss=10):
        fields = ["0"] * 40
        fields[0], fields[11], fields[12] = "R", str(ticks), "0"
        fields[15:18] = ["20", "0", "4"]
        fields[19:22] = [str(start), "10485760", str(rss)]
        self.write(f"proc/{pid}/stat", f"{pid} ({name}) " + " ".join(fields))

    def test_process_cpu_rss_and_pid_reuse(self):
        self.put_process()
        with patch.object(m.time, "monotonic", return_value=100):
            monitor = self.monitor()
        self.put_process(ticks=100 + monitor.clock_ticks * 3)
        with patch.object(m.time, "monotonic", return_value=102):
            item = monitor.sample()["processes"]["items"][0]
        self.assertEqual(item["name"], "worker (a) )")
        self.assertEqual(item["cpu"], 150)
        self.assertEqual(item["rss"], 10 * monitor.page_size)
        self.assertEqual(item["threads"], 4)
        self.assertAlmostEqual(item["memory"], round(item["rss"] / (1000 * 1024) * 100, 2))
        self.put_process(ticks=1, start=2000)
        with patch.object(m.time, "monotonic", return_value=104):
            self.assertIsNone(monitor.sample()["processes"]["items"][0]["cpu"])
        (self.proc / "123/stat").unlink()
        with patch.object(m.time, "monotonic", return_value=106):
            data = monitor.sample()["processes"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["unreadable"], 1)
        self.assertEqual(monitor.process_previous, {})

    def test_process_collection_disabled(self):
        self.put_process()
        data = self.monitor(processes=False).sample()["processes"]
        self.assertFalse(data["enabled"])
        self.assertEqual(data["items"], [])

    def test_temperature_numeric_order_and_logical_mapping(self):
        # Lexical temp14-before-temp6 order must not dictate the displayed order.
        for sensor, core in (("temp14", 12), ("temp6", 4)):
            self.write(f"sys/class/hwmon/hwmon0/{sensor}_input", "42000")
            self.write(f"sys/class/hwmon/hwmon0/{sensor}_label", f"Core {core}")
        for cpu, core in ((0, 4), (1, 12)):
            self.write(f"sys/devices/system/cpu/cpu{cpu}/topology/core_id", str(core))
            self.write(f"sys/devices/system/cpu/cpu{cpu}/topology/physical_package_id", "0")
        data = self.monitor().sample()["temperatures"]
        self.assertIn("Package id 0", data[0]["label"])
        self.assertIn("Core 4", data[1]["label"])
        self.assertEqual(data[1]["cpus"], [0])
        self.assertEqual(data[1]["group"], "P")
        self.assertIn("Core 12", data[2]["label"])
        self.assertEqual(data[2]["group"], "E")
        # Same physical ID in another package must not be falsely mapped.
        self.write("sys/devices/system/cpu/cpu1/topology/physical_package_id", "1")
        data = self.monitor().sample()["temperatures"]
        unmatched = next(t for t in data if "Core 12" in t["label"])
        self.assertEqual(unmatched["cpus"], [])

    def test_temperature_same_group_numeric_order(self):
        for sensor, core in (("temp14", 12), ("temp6", 4)):
            self.write(f"sys/class/hwmon/hwmon0/{sensor}_input", "42000")
            self.write(f"sys/class/hwmon/hwmon0/{sensor}_label", f"Core {core}")
        data = self.monitor().sample()["temperatures"]
        self.assertIn("Core 4", data[1]["label"])
        self.assertIn("Core 12", data[2]["label"])

    @unittest.skipUnless(shutil.which("node"), "Optional JS syntax check requires Node.js on development host")
    def test_frontend_syntax(self):
        page = (Path(__file__).parents[1] / "index.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        result = subprocess.run([shutil.which("node"), "--check", "--input-type=commonjs"],
                                input=script, text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_http_routes(self):
        server = HTTPServer(("127.0.0.1", 0), m.make_handler(self.monitor()))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base + "/", timeout=3) as response:
                self.assertIn(b"Core / resource monitor", response.read())
            with urlopen(base + "/api/metrics", timeout=3) as response:
                self.assertEqual(json.load(response)["model"], "Fixture CPU")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/monitor.py", timeout=3)
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()

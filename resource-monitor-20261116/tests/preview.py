"""Synthetic browser QA only. Run: python tests/preview.py (Ctrl+C to stop)."""
from http.server import HTTPServer
from test_monitor import MonitorTest, m

fixture = MonitorTest()
fixture.setUp()
for pid in range(100, 220):
    fixture.put_process(pid=pid, ticks=pid * 100, name=f"fixture-worker-{pid}", rss=pid * 20)
fixture.write("proc/meminfo", "MemTotal: 16000000 kB\nMemAvailable: 10000000 kB\nSwapTotal: 2000000 kB\nSwapFree: 1500000 kB\n")
for sensor, core in (("temp14", 12), ("temp6", 4)):
    fixture.write(f"sys/class/hwmon/hwmon0/{sensor}_input", "42000")
    fixture.write(f"sys/class/hwmon/hwmon0/{sensor}_label", f"Core {core}")
for cpu, core in ((0, 4), (1, 12)):
    fixture.write(f"sys/devices/system/cpu/cpu{cpu}/topology/core_id", str(core))
    fixture.write(f"sys/devices/system/cpu/cpu{cpu}/topology/physical_package_id", "0")
monitor = fixture.monitor()
monitor.hostname = "DEMO / synthetic data"
server = HTTPServer(("127.0.0.1", 8876), m.make_handler(monitor))
print("Synthetic QA preview: http://127.0.0.1:8876", flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
    fixture.doCleanups()

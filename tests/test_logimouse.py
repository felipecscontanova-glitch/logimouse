"""Testes com o mouse simulado. Rode com: python3 -m unittest discover -s tests"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from logimouse import config  # noqa: E402
from logimouse import demo as D  # noqa: E402
from logimouse import hidpp as H  # noqa: E402
from logimouse.tray import Monitor  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def new_mouse():
    fake = D.FakeMouse()
    devs = H.probe_transport(fake, fake.bus)
    return fake, devs[0]


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "XDG_RUNTIME_DIR")}
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name, "config")
        os.environ["XDG_RUNTIME_DIR"] = self.tmp.name
        config.DRY_RUN = False

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()


class ProtocolTests(unittest.TestCase):
    def test_dpi_list_with_range(self):
        raw = bytes([0x00, 0xC8, 0xE0, 0x32, 0x1F, 0x40, 0, 0])  # 200, passo 50 ate 8000
        lst = H.parse_dpi_list(raw)
        self.assertEqual(lst[0], 200)
        self.assertEqual(lst[-1], 8000)
        self.assertEqual(len(lst), (8000 - 200) // 50 + 1)

    def test_dpi_list_plain_values(self):
        raw = bytes([0x01, 0x90, 0x03, 0x20, 0x06, 0x40, 0, 0])
        self.assertEqual(H.parse_dpi_list(raw), [400, 800, 1600])

    def test_volt_to_percent(self):
        self.assertEqual(H.volt_to_percent(4200), 100)
        self.assertEqual(H.volt_to_percent(3400), 0)
        self.assertEqual(H.volt_to_percent(3811), 50)

    def test_discover_and_identity(self):
        fake, dev = new_mouse()
        self.assertEqual(dev.index, 1)
        self.assertEqual(dev.name, "MX Master 3S (demo)")
        self.assertTrue(dev.is_pointer)
        self.assertEqual(dev.protocol, (4, 5))

    def test_read_and_write_everything(self):
        fake, dev = new_mouse()
        s = H.read_all(dev)
        self.assertEqual(s["battery"]["percent"], 73)
        self.assertEqual(s["dpi"][1], 1000)
        self.assertEqual(dev.set_dpi(1600), 1600)
        self.assertEqual(dev.set_report_rate(1000), 1000)
        self.assertEqual(fake.rate_ms, 1)
        self.assertEqual(dev.set_smartshift(2, 30), (2, 30))
        self.assertEqual(dev.set_smartshift(1, None)[0], 1)
        self.assertTrue(dev.set_hires_wheel(invert=True)["invert"])
        self.assertTrue(dev.set_host_mode(True))
        self.assertIsNone(s["pointer_speed"])  # o simulado nao tem essa feature

    def test_unsupported_feature(self):
        fake, dev = new_mouse()
        with self.assertRaises(H.NotSupported):
            dev.pointer_speed()

    def test_offline_device_errors(self):
        fake, dev = new_mouse()
        fake.online = False
        with self.assertRaises(H.HidppError):
            dev.ping()

    def test_apply_settings(self):
        fake, dev = new_mouse()
        saved = dict(host_mode=True, dpi=2400, report_rate=500, smartshift=[2, 20],
                     hires=False, invert=True, pointer_speed=300)
        done, failed = H.apply_settings(dev, saved)
        self.assertEqual((fake.dpi, fake.rate_ms, fake.ss, fake.onboard), (2400, 2, [2, 20], 2))
        self.assertEqual(fake.wheel & 0x06, 0x04)
        self.assertEqual(failed, ["velocidade"])  # sem suporte no simulado
        self.assertIn("DPI", done)


class ConfigTests(TempHome):
    def test_remember_and_forget(self):
        config.remember("Mouse X", dpi=1600)
        config.remember("Mouse X", report_rate=1000)
        self.assertEqual(config.device_settings("Mouse X"), {"dpi": 1600, "report_rate": 1000})
        config.forget("Mouse X")
        self.assertEqual(config.device_settings("Mouse X"), {})

    def test_corrupt_file_falls_back_to_defaults(self):
        os.makedirs(config.config_dir(), exist_ok=True)
        with open(config.config_file(), "w") as fh:
            fh.write("{nao e json")
        self.assertTrue(config.get_option("reapply"))

    def test_autostart_file(self):
        self.assertFalse(config.autostart_enabled())
        config.set_autostart(True)
        with open(config.autostart_file()) as fh:
            txt = fh.read()
        self.assertIn("--tray", txt)
        self.assertIn("[Desktop Entry]", txt)
        config.set_autostart(False)
        self.assertFalse(config.autostart_enabled())

    def test_single_tray_lock(self):
        self.assertFalse(config.tray_running())
        lock = config.acquire_tray_lock()
        self.assertIsNotNone(lock)
        self.assertTrue(config.tray_running())
        self.assertIsNone(config.acquire_tray_lock())
        lock.close()
        self.assertFalse(config.tray_running())


class MonitorTests(TempHome):
    def make(self):
        self.fake = D.FakeMouse()
        self.clock = FakeClock()
        self.snaps, self.lows = [], []
        disc = lambda: (H.probe_transport(self.fake, self.fake.bus), [])  # noqa: E731
        m = Monitor(disc, D.demo_nodes, on_change=self.snaps.append,
                    on_low_battery=lambda n, p: self.lows.append((n, p)), clock=self.clock)
        return m

    def run_for(self, m, seconds, step=0.5):
        end = self.clock.t + seconds
        while self.clock.t < end:
            m.step(0)
            self.clock.t += step

    def test_reapplies_on_start(self):
        config.remember("MX Master 3S (demo)", dpi=2000, smartshift=[1, None])
        m = self.make()
        self.run_for(m, 2)
        self.assertEqual(self.fake.dpi, 2000)
        self.assertEqual(self.fake.ss[0], 1)
        self.assertEqual(self.snaps[-1][0]["battery"]["percent"], 73)

    def test_reapplies_after_power_cycle(self):
        config.remember("MX Master 3S (demo)", dpi=2400, report_rate=1000)
        m = self.make()
        self.run_for(m, 2)
        self.assertEqual(self.fake.dpi, 2400)
        self.fake.power_off()
        self.run_for(m, 1)
        self.assertFalse(m.snapshot()[0]["online"])
        self.assertEqual(self.fake.dpi, 1000)  # o mouse "esqueceu"
        self.fake.power_on()
        self.run_for(m, 3)
        self.assertTrue(m.snapshot()[0]["online"])
        self.assertEqual(self.fake.dpi, 2400)
        self.assertEqual(self.fake.rate_ms, 1)

    def test_power_cycle_without_notifications_is_retried(self):
        config.remember("MX Master 3S (demo)", dpi=1800)
        m = self.make()
        self.run_for(m, 2)
        self.fake.online = False  # some sem avisar
        self.fake.reset()
        self.clock.t += Monitor.BATTERY
        self.run_for(m, 1)
        self.assertFalse(m.snapshot()[0]["online"])
        self.fake.online = True  # volta sem avisar
        self.run_for(m, Monitor.RETRY_OFFLINE + 2)
        self.assertEqual(self.fake.dpi, 1800)

    def test_reapply_can_be_turned_off(self):
        config.remember("MX Master 3S (demo)", dpi=2400)
        config.set_option("reapply", False)
        m = self.make()
        self.run_for(m, 2)
        self.assertEqual(self.fake.dpi, 1000)
        m.reapply_now()  # mas o botao manual ainda funciona
        self.run_for(m, 1)
        self.assertEqual(self.fake.dpi, 2400)

    def test_battery_event_and_low_warning(self):
        m = self.make()
        self.run_for(m, 2)
        self.fake.battery_event(12)
        self.run_for(m, 1)
        self.assertEqual(m.snapshot()[0]["battery"]["percent"], 12)
        self.assertEqual(self.lows, [("MX Master 3S (demo)", 12)])
        self.fake.battery_event(10)
        self.run_for(m, 1)
        self.assertEqual(len(self.lows), 1)  # avisa uma vez so


if __name__ == "__main__":
    unittest.main()

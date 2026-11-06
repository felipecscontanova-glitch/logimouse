"""Testes do headset MCHOSE e do UPower, sem hardware."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from logimouse import config  # noqa: E402
from logimouse import demo as D  # noqa: E402
from logimouse import headset as HS  # noqa: E402
from logimouse.tray import HeadsetWatcher  # noqa: E402

# Descriptor real do receptor de um MCHOSE V9 Pro (291d:385d), do --diagnostico de um usuário.
V9PRO_DESCRIPTOR = bytes.fromhex(
    "06 21 ff 09 01 a1 01 15 00 26 ff 00 85 ed 75 08 95 01 09 00 81 02 09 00 91 02 09 00 95 0f b2 02 "
    "01 c0 06 22 ff 09 01 a1 01 15 00 26 ff 00 85 aa 75 08 09 00 95 3f b2 02 01 c0 05 0c 09 01 a1 01 "
    "85 06 15 00 25 01 09 e9 09 ea 09 e2 09 cd 09 b5 09 b6 09 b1 09 b7 75 01 95 08 81 42 75 01 95 08 "
    "81 03 c0 05 0b 09 01 a1 01 85 07 15 00 25 01 09 20 09 97 75 01 95 02 81 23 75 06 95 01 81 03 09 "
    "21 09 2f 09 50 75 01 95 03 81 07 09 06 a1 02 19 b0 29 bb 15 00 25 0c 75 04 95 01 81 40 c0 09 07 "
    "05 09 75 01 95 01 81 02 05 08 15 00 25 01 09 08 09 17 09 18 09 19 09 1a 09 1e 09 1f 09 20 09 21 "
    "09 22 09 23 09 24 09 25 09 26 09 09 75 01 95 0f 91 02 75 01 95 01 91 03 c0 06 90 ff 09 01 a1 01 "
    "09 03 85 55 15 00 26 ff 00 75 08 95 3f 82 02 01 09 04 15 00 25 01 75 08 95 3f 91 01 c0 06 82 ff "
    "09 01 a1 01 09 03 85 41 15 00 26 ff 00 75 08 95 3f 81 02 09 04 15 00 26 ff 00 75 08 95 3f 91 02 c0"
)

UPOWER_BT = """  native-path:          /org/bluez/hci0/dev_11_22_33_44_55_66
  vendor:               MCHOSE
  model:                MCHOSE V9 Pro
  power supply:         no
  updated:              sex 06 nov 2026 14:50:00
  has history:          yes
  headset
    present:             yes
    state:               discharging
    warning-level:       none
    percentage:          64%
"""
UPOWER_MOUSE = """  native-path:          hidpp_battery_0
  model:                MX Master 3S
  mouse
    percentage:          73%
"""


def fake_upower(devices):
    def run(cmd):
        if cmd[:2] == ["upower", "-e"]:
            return "\n".join(list(devices) + ["/org/freedesktop/UPower/devices/DisplayDevice"])
        return devices.get(cmd[2], "")
    return run


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class DescriptorTests(unittest.TestCase):
    def test_finds_vendor_report_and_length(self):
        reports = HS.parse_report_descriptor(D.MCHOSE_DESCRIPTOR)
        self.assertEqual(reports[("out", 0x55)]["bits"], 63 * 8)
        self.assertIn(0xFF90, reports[("in", 0x55)]["pages"])
        self.assertEqual(HS.mchose_endpoint(D.MCHOSE_DESCRIPTOR), (True, 64))

    def test_real_v9_pro_descriptor(self):
        reports = HS.parse_report_descriptor(V9PRO_DESCRIPTOR)
        # o mesmo que o --diagnostico do usuário listou
        self.assertEqual(reports[("in", 0x55)], {"bits": 63 * 8, "pages": {0xFF90}})
        self.assertEqual(reports[("out", 0x55)], {"bits": 63 * 8, "pages": {0xFF90}})
        self.assertEqual(reports[("feat", 0xED)]["bits"], 15 * 8)
        self.assertEqual(reports[("in", 0x07)]["pages"], {0x09, 0x0B})
        self.assertEqual(HS.mchose_endpoint(V9PRO_DESCRIPTOR), (True, 64))

    def test_ignores_normal_audio_controls(self):
        consumer = bytes([0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x55, 0x75, 0x01, 0x95, 0x08,
                          0x81, 0x02, 0xC0])  # report 0x55 mas na pagina de controles de midia
        self.assertFalse(HS.mchose_endpoint(consumer)[0])
        self.assertFalse(HS.mchose_endpoint(b"")[0])

    def test_long_items_and_push_pop(self):
        desc = bytes([0xFE, 0x01, 0x00, 0xAA, 0x06, 0x00, 0xFF, 0xA4, 0x05, 0x01, 0xB4,
                      0x85, 0x55, 0x75, 0x08, 0x95, 0x20, 0x91, 0x02])
        reports = HS.parse_report_descriptor(desc)
        self.assertEqual(reports[("out", 0x55)]["pages"], {0xFF00})
        self.assertEqual(HS.mchose_endpoint(desc), (True, 33))


class MchoseTests(unittest.TestCase):
    def make(self, battery=58):
        self.fake = D.FakeMchose(battery)
        return HS.MchoseHeadset(self.fake, "MCHOSE V9 Pro", 0x6046)

    def test_battery_skips_heartbeat_and_other_fields(self):
        h = self.make(58)
        self.assertEqual(h.battery()["percent"], 58)
        self.assertEqual(self.fake.writes[-1][:4], bytes([0x55, 0x65, 0x01, 0x00]))
        self.assertEqual(len(self.fake.writes[-1]), 64)

    def test_headset_off_is_not_zero_percent(self):
        h = self.make()
        self.fake.online = False
        with self.assertRaises(HS.HeadsetTimeout):
            h.battery()

    def test_no_answer_times_out(self):
        h = HS.MchoseHeadset(D.FakeMchose(), "x")
        h.t.write = lambda m: None
        with self.assertRaises(HS.HeadsetTimeout):
            h.battery(timeout=0.2)

    def test_parse(self):
        h = self.make()
        self.assertEqual(h.parse(bytes([0x55, 0x65, 41, 0x02]))["percent"], 41)
        self.assertIsNone(h.parse(bytes([0x55, 0x65, 41, 0x05])))
        self.assertIsNone(h.parse(bytes([0x55, 0x65, 200, 0x02])))
        self.assertIsNone(h.parse(bytes([0x11, 0x65, 41, 0x02])))
        self.assertIsNone(h.parse(b""))

    def test_model_names(self):
        self.assertEqual(HS.model_name(dict(name="C-Media Electronics Inc MCHOSE V9 PRO", vid=0x291D,
                                            pid=0x385D)), "MCHOSE V9 PRO")
        self.assertEqual(HS.model_name(dict(name="", vid=0x291D, pid=0x385D)), "MCHOSE V9 Pro")
        self.assertEqual(HS.model_name(dict(name="", pid=0x6045)), "MCHOSE X9")
        self.assertEqual(HS.model_name(dict(name="MCHOSE V9 Pro", pid=0x6046)), "MCHOSE V9 Pro")
        self.assertEqual(HS.model_name(dict(name="V9 Pro Dongle", pid=0x6046)), "MCHOSE V9 Pro Dongle")
        self.assertEqual(HS.model_name(dict(name="C-Media USB Headphone Set", pid=0x6046)),
                         "Headset MCHOSE (3837:6046)")


class SysfsDiscoveryTests(unittest.TestCase):
    """Monta um /sys/class/hidraw falso e confere a escolha da interface certa."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "class", "hidraw")
        os.makedirs(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, n, hid_id, name, desc, parent="usb1/1-2/1-2:1.3"):
        dev = os.path.join(self.tmp.name, "devices", parent, f"{hid_id.replace(':', '_')}.{n:04X}")
        os.makedirs(dev)
        with open(os.path.join(dev, "uevent"), "w") as fh:
            fh.write(f"HID_ID={hid_id}\nHID_NAME={name}\n")
        with open(os.path.join(dev, "report_descriptor"), "wb") as fh:
            fh.write(desc)
        link = os.path.join(self.root, f"hidraw{n}")
        os.makedirs(link)
        os.symlink(dev, os.path.join(link, "device"))

    def test_picks_vendor_interface(self):
        media = bytes([0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0xC0])
        self.add(3, "0003:00003837:00006046", "MCHOSE V9 Pro", media)
        self.add(4, "0003:00003837:00006046", "MCHOSE V9 Pro", D.MCHOSE_DESCRIPTOR)
        self.add(5, "0003:0000046D:0000C548", "Logitech USB Receiver", D.MCHOSE_DESCRIPTOR)
        nodes = HS.hid_nodes(HS.MCHOSE_VID, root=self.root)
        self.assertEqual([n["path"] for n in nodes], ["/dev/hidraw3", "/dev/hidraw4"])
        opened = []

        class Port:
            def __init__(self, path):
                opened.append(path)

        real = HS.HidrawPort
        HS.HidrawPort = Port
        try:
            found, problems = HS.discover_mchose(nodes)
        finally:
            HS.HidrawPort = real
        self.assertEqual(opened, ["/dev/hidraw4"])
        self.assertEqual(found[0].name, "MCHOSE V9 Pro")
        self.assertEqual(problems, [])

    def test_finds_real_v9_pro_receiver(self):
        self.add(6, "0003:0000291D:0000385D", "C-Media Electronics Inc MCHOSE V9 PRO", V9PRO_DESCRIPTOR)
        self.add(7, "0003:0000046D:0000C53F", "Logitech USB Receiver", D.MCHOSE_DESCRIPTOR)
        nodes = HS.mchose_nodes(root=self.root)
        self.assertEqual([n["path"] for n in nodes], ["/dev/hidraw6"])
        ports = {}

        class Port:
            def __init__(self, path):
                ports[path] = D.FakeMchose(81)

            def __getattr__(self, name):
                return getattr(next(iter(ports.values())), name)

        real = HS.HidrawPort
        HS.HidrawPort = Port
        try:
            found, problems = HS.discover_mchose(nodes)
        finally:
            HS.HidrawPort = real
        h = found[0]
        self.assertEqual((h.name, h.vid, h.pid, h.write_len), ("MCHOSE V9 PRO", 0x291D, 0x385D, 64))
        self.assertEqual(h.detail, "Headset · Receptor 2.4 GHz · 291d:385d")
        self.assertEqual(h.battery()["percent"], 81)

    def test_permission_problem_is_reported(self):
        self.add(4, "0003:00003837:00006046", "MCHOSE V9 Pro", D.MCHOSE_DESCRIPTOR)

        def denied(path):
            raise PermissionError(13, "Permission denied")
        real = HS.HidrawPort
        HS.HidrawPort = denied
        try:
            found, problems = HS.discover_mchose(HS.hid_nodes(HS.MCHOSE_VID, root=self.root))
        finally:
            HS.HidrawPort = real
        self.assertEqual(found, [])
        self.assertIn("instalar.sh", problems[0])


class UPowerTests(unittest.TestCase):
    def test_bluetooth_headset_only(self):
        run = fake_upower({"/org/freedesktop/UPower/devices/headset_dev_11": UPOWER_BT,
                           "/org/freedesktop/UPower/devices/mouse_hidpp": UPOWER_MOUSE})
        hs = HS.upower_headsets(run)
        self.assertEqual([h.name for h in hs], ["MCHOSE V9 Pro"])
        self.assertEqual(hs[0].connection, "Bluetooth")
        b = hs[0].battery()
        self.assertEqual((b["percent"], b["status"]), (64, "Descarregando"))

    def test_parse_info(self):
        info = HS.parse_upower_info(UPOWER_BT)
        self.assertEqual(info["type"], "headset")
        self.assertEqual(info["model"], "MCHOSE V9 Pro")


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        config.DRY_RUN = False
        self.fake = D.FakeMchose(58)
        self.clock = Clock()
        self.lows, self.snaps = [], []
        self.w = HeadsetWatcher(lambda: ([HS.MchoseHeadset(self.fake, "MCHOSE V9 Pro", 0x6046)], []),
                                lambda: [], on_change=self.snaps.append,
                                on_low_battery=lambda n, p: self.lows.append((n, p)), clock=self.clock)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.old
        self.tmp.cleanup()

    def run_for(self, seconds, step=1.0):
        end = self.clock.t + seconds
        while self.clock.t < end:
            self.w.step(0)
            self.clock.t += step

    def test_reads_battery_and_pushed_updates(self):
        self.run_for(2)
        snap = self.w.snapshot()[0]
        self.assertEqual((snap["online"], snap["battery"]["percent"], snap["headset"]), (True, 58, True))
        self.fake.battery_event(57)  # o receptor manda sozinho
        self.run_for(1)
        self.assertEqual(self.w.snapshot()[0]["battery"]["percent"], 57)

    def test_off_and_back_on(self):
        self.run_for(2)
        self.fake.online = False
        self.clock.t += HeadsetWatcher.POLL
        self.run_for(1)
        self.assertFalse(self.w.snapshot()[0]["online"])
        self.fake.online = True
        self.run_for(HeadsetWatcher.OFF_POLL + 1)
        self.assertTrue(self.w.snapshot()[0]["online"])

    def test_low_battery_warning_once(self):
        self.run_for(2)
        self.fake.battery_event(12)
        self.run_for(1)
        self.fake.battery_event(11)
        self.run_for(1)
        self.assertEqual(self.lows, [("MCHOSE V9 Pro", 12)])


if __name__ == "__main__":
    unittest.main()

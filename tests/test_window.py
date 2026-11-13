"""Painel novo (GTK 4) com o mouse e o headset simulados. Precisa de tela (xvfb-run)."""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from logimouse import config  # noqa: E402
from logimouse import demo as D  # noqa: E402
from logimouse import gui  # noqa: E402

HAVE = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and gui.gtk_available()


@unittest.skipUnless(HAVE, "sem GTK 4 + libadwaita (+ cairo) ou sem tela")
class NewPanel(unittest.TestCase):
    app = None

    def setUp(self):
        from gi.repository import GLib
        from logimouse import window as W
        self.GLib, self.W = GLib, W
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        config.DRY_RUN = True
        config._memory = None
        D._shared = None
        D._shared_headset = None
        if NewPanel.app is None:  # um aplicativo por processo (ele se registra no D-Bus)
            NewPanel.app = W.LogiApp(demo=True)
            NewPanel.app.register(None)
        self.win = W.MainWindow(NewPanel.app, True)
        self.pump(lambda: self.win.mice and self.win.heads)

    def tearDown(self):
        self.win.destroy()
        D._shared = None
        config._memory = None
        if self.old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.old
        self.tmp.cleanup()

    def pump(self, cond, timeout=8.0):
        ctx = self.GLib.MainContext.default()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            while ctx.pending():
                ctx.iteration(False)
            if cond():
                return
            time.sleep(0.01)
        self.fail("o painel não respondeu a tempo")

    def test_every_section_builds(self):
        w = self.win
        w.open_device(w.mice[0])
        for key, _ in w.secs:
            w.show_section(key)
        w.open_device(w.heads[0])
        for key, _ in w.secs:
            w.show_section(key)
        w.go_home()
        self.assertEqual(w.stack.get_visible_child_name(), "home")

    def test_remap_button_writes_to_mouse(self):
        w = self.win
        w.open_device(w.mice[0])
        w.show_section("buttons")
        w.work["buttons"][4] = {"kind": "consumer", "value": 0xCD}
        w.work["dpis"][1] = 900
        w._mark()
        w.save_profile()
        fake = D.shared_mouse()
        self.pump(lambda: not w.dirty)
        from logimouse import onboard as O
        p = O.Profile(fake.sectors[1])
        self.assertTrue(p.crc_ok())
        self.assertEqual(p.button(4), {"kind": "consumer", "value": 0xCD})
        self.assertEqual(p.dpis[1], 900)
        from logimouse import profiles as P
        self.assertEqual(P.device_data(w.cur.name)["profiles"]["Padrão"]["dpis"][1], 900)

    def test_refuses_profile_without_left_click(self):
        w = self.win
        w.open_device(w.mice[0])
        before = D.shared_mouse().sectors[1]
        w.work["buttons"][0] = {"kind": "mouse", "value": 2}
        w.save_profile()
        self.pump(lambda: True, 0.3)
        self.assertEqual(D.shared_mouse().sectors[1], before)


if __name__ == "__main__":
    unittest.main()

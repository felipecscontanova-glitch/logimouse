"""Testes do painel com o mouse simulado. Precisam de uma tela (rodam com xvfb-run)."""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    import tkinter as tk
    from tkinter import ttk
    HAVE_TK = bool(os.environ.get("DISPLAY"))
except ImportError:
    HAVE_TK = False

from logimouse import config  # noqa: E402
from logimouse import demo as D  # noqa: E402

NAME = "MX Master 3S (demo)"


@unittest.skipUnless(HAVE_TK, "sem Tkinter ou sem tela (use xvfb-run)")
class PanelSavesWhatYouChose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cfg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        config.DRY_RUN = False
        D._shared = None
        self.fake = D.shared_mouse()
        from logimouse import gui
        self.app = gui.App(tk, ttk, demo=True)
        self.pump(lambda: self.app.state.get("dpi"))

    def tearDown(self):
        self.app.root.destroy()
        D._shared = None
        if self.old_cfg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.old_cfg
        self.tmp.cleanup()

    def pump(self, cond, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.root.update()
            if cond():
                return
            time.sleep(0.01)
        self.fail("o painel não respondeu a tempo")

    def status(self):
        return self.app.status.cget("text")

    def saved_dpi(self):
        return config.device_settings(NAME).get("dpi")

    def test_saves_even_after_another_callback_crashed(self):
        # antes da correção, este erro parava o painel e o DPI seguinte não era salvo
        self.app.worker.submit(lambda: 1, lambda r: 1 / 0)
        self.app._dpi_apply(1600)
        self.pump(lambda: "salvo" in self.status())
        self.assertEqual(self.saved_dpi(), 1600)
        self.assertEqual(self.fake.dpi, 1600)

    def test_saves_when_card_is_redrawn_meanwhile(self):
        self.app._dpi_apply(2000)
        self.app.build()  # destrói os widgets antigos antes da resposta chegar
        self.pump(lambda: "salvo" in self.status())
        self.assertEqual(self.saved_dpi(), 2000)

    def test_saves_choice_and_warns_when_mouse_keeps_other_value(self):
        self.fake.ignore_dpi = True
        self.app._dpi_apply(3200)
        self.pump(lambda: "respondeu" in self.status())
        self.assertEqual(self.saved_dpi(), 3200)
        self.assertIn("modo host", self.status().lower().replace("controlar pelo computador", "modo host"))

    def test_saves_choice_when_mouse_is_off(self):
        self.fake.online = False
        self.app._dpi_apply(400)
        self.pump(lambda: "Salvei" in self.status())
        self.assertEqual(self.saved_dpi(), 400)


if __name__ == "__main__":
    unittest.main()

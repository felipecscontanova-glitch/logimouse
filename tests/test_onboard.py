"""Memoria do mouse (perfis, botoes), macros, perfis no PC e som do headset."""

import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from logimouse import audio as AU  # noqa: E402
from logimouse import config  # noqa: E402
from logimouse import demo as D  # noqa: E402
from logimouse import macros as M  # noqa: E402
from logimouse import onboard as O  # noqa: E402
from logimouse import profiles as P  # noqa: E402


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        config.DRY_RUN = False
        D._shared = None

    def tearDown(self):
        D._shared = None
        if self.old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.old
        self.tmp.cleanup()


class ProfileFormat(unittest.TestCase):
    def test_real_g305_dump(self):
        p = O.Profile(D.G305_PROFILE)
        self.assertTrue(p.crc_ok())  # CRC lido de um G305 de verdade
        d = p.to_dict()
        self.assertEqual(d["dpis"], [400, 800, 1600, 3200])
        self.assertEqual(d["rate"], 1000)
        self.assertEqual(d["default_dpi"], 1)
        self.assertEqual(d["buttons"][0], {"kind": "mouse", "value": 1})
        self.assertEqual(d["buttons"][5], {"kind": "function", "value": 5})

    def test_button_round_trip(self):
        for a in ({"kind": "mouse", "value": 8}, {"kind": "key", "mods": 1, "value": 6},
                  {"kind": "consumer", "value": 0xCD}, {"kind": "function", "value": 7}, {"kind": "none"}):
            self.assertEqual(O.decode_button(O.encode_button(a)), a)

    def test_edit_and_seal(self):
        p = O.Profile(D.G305_PROFILE)
        p.apply_dict({"dpis": [400, 800, 1600, 3200, 6400], "rate": 500, "default_dpi": 4,
                      "buttons": [None, None, None, {"kind": "consumer", "value": 0xCD}]})
        data = p.seal()
        q = O.Profile(data)
        self.assertTrue(q.crc_ok())
        self.assertEqual(q.dpis, [400, 800, 1600, 3200, 6400])
        self.assertEqual(q.rate, 500)
        self.assertEqual(q.default_dpi, 4)
        self.assertEqual(q.button(3), {"kind": "consumer", "value": 0xCD})
        self.assertEqual(data[160:208], D.G305_PROFILE[160:208])  # resto do setor intacto

    def test_left_button_cannot_be_disabled(self):
        p = O.Profile(D.G305_PROFILE)
        with self.assertRaises(ValueError):
            p.set_button(0, {"kind": "none"})

    def test_bad_rate(self):
        with self.assertRaises(ValueError):
            O.Profile(D.G305_PROFILE).rate = 333


class OnboardOnFakeMouse(TempConfig):
    def mouse(self):
        devs, _ = D.discover_demo()
        return devs[0]

    def test_write_read_back_and_backup(self):
        dev = self.mouse()
        ob = O.Onboard(dev)
        self.assertEqual((ob.nbuttons, ob.sector_size), (6, 255))
        p = ob.read_profile()
        p.apply_dict({"dpis": [500, 1000], "buttons": [None, None, None, None, {"kind": "function", "value": 7}]})
        q = ob.write_profile(p)
        self.assertTrue(q.crc_ok())
        self.assertEqual(ob.read_profile().to_dict()["dpis"], [500, 1000])
        self.assertEqual(D.shared_mouse().sectors[1], bytes(q.raw))
        self.assertEqual(ob.mode(), O.MODE_ONBOARD)
        backups = os.listdir(O.backups_dir())
        self.assertEqual(len(backups), 1)

    def test_restore_factory(self):
        dev = self.mouse()
        ob = O.Onboard(dev)
        p = ob.read_profile()
        p.apply_dict({"dpis": [123 * 50]})
        ob.write_profile(p)
        r = ob.restore_factory()
        self.assertEqual(r.dpis[:4], [400, 800, 1600, 3200])
        self.assertTrue(r.crc_ok())

    def test_factory_sector_is_read_only(self):
        ob = O.Onboard(self.mouse())
        with self.assertRaises(O.OnboardError):
            ob.write_sector(0x0101, bytes(255))


class Macros(unittest.TestCase):
    def test_key_action_and_text(self):
        a = M.key_action(["Ctrl", "c"])
        self.assertEqual(a, {"kind": "key", "mods": 1, "value": 0x06})
        self.assertEqual(M.combo_text(a["mods"], a["value"]), "Ctrl+C")
        self.assertEqual(O.describe(a), "Tecla: Ctrl+C")
        with self.assertRaises(ValueError):
            M.key_action(["Ctrl"])

    def test_triggers(self):
        a = M.trigger_action(2)
        self.assertEqual(M.trigger_index(a["value"]), 2)
        self.assertIsNone(M.trigger_index(0x06))
        self.assertEqual(O.describe(a, [{"name": "a"}, {"name": "b"}, {"name": "Recarregar"}]), "Macro: Recarregar")

    def test_validate(self):
        held = M.validate({"mode": "hold", "steps": [{"t": "down", "k": "Ctrl"}, {"t": "wait", "ms": 20},
                                                    {"t": "down", "k": "c"}, {"t": "up", "k": "c"}]})
        self.assertEqual(held, ["Ctrl"])  # fica apertada: e solta no fim da macro
        with self.assertRaises(ValueError):
            M.validate({"steps": [{"t": "down", "k": "nada"}]})
        with self.assertRaises(ValueError):
            M.validate({"steps": [{"t": "wait", "ms": 99999}]})

    def test_play_releases_held_keys(self):
        class Kbd:
            def __init__(self):
                self.ev = []

            def emit(self, code, value):
                self.ev.append((code, value))
        k = Kbd()
        M.play(k, {"steps": [{"t": "down", "k": "Ctrl"}, {"t": "down", "k": "c"}, {"t": "up", "k": "c"}]})
        self.assertEqual(k.ev, [(29, 1), (46, 1), (46, 0), (29, 0)])


class PcProfiles(TempConfig):
    def test_profiles_and_rules(self):
        P.ensure_default("G305", {"dpis": [800], "rate": 1000})
        P.put_profile("G305", "Valorant", {"dpis": [400], "rate": 1000})
        data = P.set_rules("G305", [{"match": "valorant", "profile": "Valorant"}, {"match": " ", "profile": "x"}])
        self.assertEqual(len(data["rules"]), 1)
        self.assertEqual(P.wanted_profile(data, {"bash", "valorant.exe"}), "Valorant")
        self.assertEqual(P.wanted_profile(data, {"bash"}), "Padrão")
        with self.assertRaises(ValueError):
            P.delete_profile("G305", "Padrão")
        data = P.delete_profile("G305", "Valorant")
        self.assertEqual(data["rules"], [])

    def test_running_programs_from_proc(self):
        proc = os.path.join(self.tmp.name, "proc")
        os.makedirs(os.path.join(proc, "123"))
        with open(os.path.join(proc, "123", "comm"), "w") as fh:
            fh.write("wine64-preloader\n")
        with open(os.path.join(proc, "123", "cmdline"), "wb") as fh:
            fh.write(b"Z:\\Games\\VALORANT.exe\0-arg\0")
        names = P.running_programs(proc)
        self.assertIn("valorant.exe", names)
        self.assertIn("wine64-preloader", names)

    def test_macros_saved(self):
        P.save_macros([{"name": "a", "mode": "once", "steps": [{"t": "down", "k": "r"}, {"t": "up", "k": "r"}]}])
        self.assertEqual(P.macros()[0]["name"], "a")
        with self.assertRaises(ValueError):
            P.save_macros([{"name": "x", "mode": "?", "steps": []}])


class Audio(TempConfig):
    def test_nothing_on_means_no_service(self):
        self.assertIsNone(AU.build_conf(dict(AU.DEFAULTS)))

    def test_eq_surround_and_mic_chain(self):
        s = dict(AU.DEFAULTS, gains=AU.PRESETS["FPS"], surround=True, nr=True, voice="Clara", mic_gain=3,
                 sidetone=True, sink="alsa_output.usb-MCHOSE", source="alsa_input.usb-MCHOSE", label="V9 Pro")
        txt = AU.build_conf(s, hrir="/tmp/h.wav", rnnoise="/x/librnnoise_ladspa.so")
        self.assertIn('node.name = "logimouse_eq"', txt)
        self.assertIn('target.object = "alsa_output.usb-MCHOSE"', txt)
        self.assertIn('node.name = "logimouse_surround"', txt)
        self.assertIn('target.object = "logimouse_eq"', txt)  # surround -> EQ -> headset
        self.assertEqual(txt.count("label = convolver"), 16)
        self.assertIn("noise_suppressor_mono", txt)
        self.assertIn('"VAD Threshold (%)" = 75.0', txt)
        self.assertIn("libpipewire-module-loopback", txt)
        self.assertEqual(txt.count("{"), txt.count("}"))
        self.assertEqual(txt.count("["), txt.count("]"))

    def test_nr_without_plugin_is_skipped(self):
        s = dict(AU.DEFAULTS, nr=True)
        self.assertIsNone(AU.build_conf(s, rnnoise=None))

    def test_generated_hrir(self):
        path = AU.make_hrir(os.path.join(self.tmp.name, "h.wav"), room=40)
        with wave.open(path) as w:
            self.assertEqual((w.getnchannels(), w.getframerate(), w.getsampwidth()), (14, 48000, 4))
        # o ouvido do lado da caixa ouve antes e mais forte
        near = AU.ear_response(-90, "L", room=0)
        far = AU.ear_response(-90, "R", room=0)
        first = lambda r: next(i for i, v in enumerate(r) if abs(v) > 1e-6)  # noqa: E731
        self.assertLess(first(near), first(far))
        self.assertGreater(sum(v * v for v in near), sum(v * v for v in far))

    def test_find_headset(self):
        nodes = [dict(id=1, name="alsa_output.pci", desc="Interno", cls="Audio/Sink", vendor="0x8086", api="alsa", props={}),
                 dict(id=2, name="alsa_output.usb-C-Media_MCHOSE_V9_PRO", desc="MCHOSE V9 PRO", cls="Audio/Sink",
                      vendor="0x291d", api="alsa", props={}),
                 dict(id=3, name="alsa_input.usb-C-Media_MCHOSE_V9_PRO", desc="MCHOSE V9 PRO", cls="Audio/Source",
                      vendor="0x291d", api="alsa", props={})]
        sink, src = AU.find_headset(nodes)
        self.assertEqual((sink["id"], src["id"]), (2, 3))

    def test_settings_saved(self):
        AU.save_settings(preset="FPS", gains=AU.PRESETS["FPS"])
        self.assertEqual(AU.settings()["gains"], AU.PRESETS["FPS"])


if __name__ == "__main__":
    unittest.main()

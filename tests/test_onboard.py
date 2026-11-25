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


class LogitechHeadset(TempConfig):
    def headset(self):
        D._shared_logi_headset = None
        devs, _ = D.discover_demo()
        return next(d for d in devs if d.is_audio)

    def test_detected_as_headset(self):
        from logimouse import hidpp as H
        h = self.headset()
        self.assertEqual((h.kind_name, h.ui, h.index), ("Headset", "logi_headset", 0xFF))
        s = H.read_all(h)
        self.assertEqual(s["battery"]["source"], "HID++ 0x1F20 (estimado pela tensão)")
        self.assertEqual(s["battery"]["voltage"], 3880)
        self.assertEqual(s["eq_info"]["freqs"], [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000])
        self.assertEqual(s["eq"], [-4, -4, -3, -2, 0, 1, 0, 0, -2, -3])
        self.assertEqual([z["name"] for z in s["leds"]], ["Logo", "Principal"])
        self.assertIsNone(s["dpi"])  # chaves de mouse vazias (o --cli nao quebra)

    def test_battery_while_charging_is_not_exaggerated(self):
        from logimouse import hidpp as H
        h = self.headset()
        fake = D.shared_logi_headset()
        fake.mv, fake.flags = 4092, 0x03  # leitura real do G935 carregando
        b = h.battery()
        self.assertTrue(b["charging"])
        self.assertEqual(b["status"], "Carregando")
        self.assertTrue(b["approx"])
        self.assertLess(b["percent"], H.volt_to_percent(4092))  # 92% sem o desconto
        self.assertTrue(70 <= b["percent"] <= 85, b["percent"])
        self.assertTrue(H.battery_text(b).startswith("~"))
        fake.mv = 4400
        self.assertEqual(h.battery()["percent"], 99)  # carregando nunca mostra 100%
        fake.flags = 0x01
        b = h.battery()
        self.assertEqual((b["percent"], b["approx"], H.battery_text(b)), (100, False, "100%"))

    def test_eq_sidetone_and_lights(self):
        h = self.headset()
        self.assertEqual(h.set_eq_gains([12, -12, 0, 0, 0, 0, 0, 0, 0, 20]), [12, -12, 0, 0, 0, 0, 0, 0, 0, 12])
        with self.assertRaises(ValueError):
            h.set_eq_gains([0] * 5)
        self.assertEqual(h.set_sidetone(140), 100)
        h.set_led(1, 0x000A, (1, 2, 3), 3000)
        self.assertEqual(D.shared_logi_headset().leds[1], (0x000A, (1, 2, 3)))

    def test_reapplied_on_reconnect(self):
        from logimouse import hidpp as H
        h = self.headset()
        done, failed = H.apply_settings(h, {"sidetone": 30, "leds": {"0": {"effect": 0}}})
        self.assertEqual((done, failed), (["retorno da voz", "luzes"], []))
        self.assertEqual(D.shared_logi_headset().side, 30)
        self.assertEqual(D.shared_logi_headset().leds[0][0], 0)


class LightsOff(TempConfig):
    def test_option_turns_off_every_device_on_reconnect(self):
        from logimouse import hidpp as H
        D._shared_logi_headset = None
        devs, _ = D.discover_demo()
        config.set_option("lights_off", True)
        for d in devs:
            saved = config.settings_to_apply(d.name)
            self.assertEqual(saved["leds"], "off")
            done, failed = H.apply_settings(d, saved)
            self.assertIn("luzes", done)
        self.assertEqual(D.shared_mouse().mouse_leds[0][0], 0)
        self.assertEqual({z: v[0] for z, v in D.shared_logi_headset().leds.items()}, {0: 0, 1: 0})

    def test_option_off_keeps_saved_effects(self):
        config.set_option("lights_off", False)
        config.remember("x", leds={"0": {"effect": 1, "color": [1, 2, 3]}})
        self.assertEqual(config.settings_to_apply("x")["leds"]["0"]["effect"], 1)


class AnyDevice(unittest.TestCase):
    """Qualquer acessorio que informa bateria ao sistema (UPower)."""

    def upower(self, devices):
        import subprocess as sp

        def run(cmd, timeout=5):
            if cmd[1] == "-e":
                return "\n".join(devices) + "\n/org/freedesktop/UPower/devices/DisplayDevice\n"
            return devices[cmd[2]]
        return run

    def info(self, typ, model, path, pct, extra=""):
        return (f"  native-path:          {path}\n  model:                {model}\n  {extra}\n  {typ}\n"
                f"    present:             yes\n    state:               discharging\n"
                f"    percentage:          {pct}%\n")

    def test_lists_any_device_but_not_laptop_or_hidpp(self):
        from logimouse import headset as HS
        devs = {"/u/1": self.info("gaming-input", "Xbox Wireless Controller", "/org/bluez/hci0/dev_AA", 70),
                "/u/2": self.info("keyboard", "K380", "/org/bluez/hci0/dev_BB", 40),
                "/u/3": self.info("mouse", "Logitech G305", "hidpp_battery_0", 55),
                "/u/4": self.info("battery", "Notebook", "BAT0", 90, "power supply:         yes"),
                "/u/5": self.info("headphones", "WH-1000XM4", "/org/bluez/hci0/dev_CC", 30)}
        out = HS.upower_devices(self.upower(devs))
        self.assertEqual([(d.name, d.kind_name, d.audio) for d in out],
                         [("Xbox Wireless Controller", "Controle", False), ("K380", "Teclado", False),
                          ("WH-1000XM4", "Fone", True)])
        self.assertEqual(out[0].connection, "Bluetooth")
        self.assertEqual(out[1].battery()["percent"], 40)
        self.assertEqual([d.name for d in HS.upower_headsets(self.upower(devs))], ["WH-1000XM4"])

    def test_same_device(self):
        from logimouse import headset as HS
        self.assertTrue(HS.same_device("Logitech G305", "G305 Lightspeed Wireless Gaming Mouse"))
        self.assertTrue(HS.same_device("MCHOSE V9 PRO", "MCHOSE V9 Pro"))
        self.assertFalse(HS.same_device("Logitech G305", "G935 Gaming Headset"))


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
        # os filtros do proprio LogiMouse tem "MCHOSE" no nome, mas nao sao o fone
        # (antes, o equalizador podia ser apontado para ele mesmo)
        own = [dict(id=9, name="logimouse_eq", desc="MCHOSE V9 PRO · Equalizador", cls="Audio/Sink",
                    vendor="", api="", props={}),
               dict(id=8, name="logimouse_mic", desc="MCHOSE V9 PRO · sem ruído", cls="Audio/Source",
                    vendor="", api="", props={})]
        sink, src = AU.find_headset(own + nodes)
        self.assertEqual((sink["id"], src["id"]), (2, 3))
        self.assertEqual(AU.find_headset(own), (None, None))

    def test_no_fallback_only_with_target(self):
        # sem o fone, o equalizador nao pode cair na saida padrao (que pode ser ele mesmo)
        s = dict(AU.DEFAULTS, gains=AU.PRESETS["FPS"], sink="alsa_output.x.analog-stereo")
        self.assertIn("node.dont-fallback = true", AU.build_conf(s))
        s["sink"] = ""
        self.assertNotIn("node.dont-fallback", AU.build_conf(s))

    def test_follow_headset_when_output_mode_changes(self):
        analog = "alsa_output.usb-C-Media_MCHOSE_V9_PRO-01.analog-stereo"
        digital = "alsa_output.usb-C-Media_MCHOSE_V9_PRO-01.iec958-stereo"
        src = "alsa_input.usb-C-Media_MCHOSE_V9_PRO-01.mono-fallback"
        AU.save_settings(gains=AU.PRESETS["FPS"], sink=analog, source=src)
        for path in (AU.conf_path(), AU.unit_path()):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()

        def nodes(sink):
            return [dict(id=1, name=sink, desc="MCHOSE V9 PRO", cls="Audio/Sink", vendor="0x291d", api="alsa", props={}),
                    dict(id=2, name=src, desc="MCHOSE V9 PRO", cls="Audio/Source", vendor="0x291d", api="alsa", props={})]
        calls = []
        old = AU.apply
        AU.apply = lambda *a, **k: calls.append(1)
        try:
            self.assertFalse(AU.follow_headset(nodes(analog)))   # nada mudou
            self.assertFalse(AU.follow_headset([]))              # fone fora: espera
            self.assertTrue(AU.follow_headset(nodes(digital)))   # analogico -> digital
        finally:
            AU.apply = old
        self.assertEqual(len(calls), 1)

    AMIXER_V9 = """Simple mixer control 'PCM',0
  Capabilities: pvolume pswitch pswitch-joined
  Playback channels: Front Left - Front Right
  Limits: Playback 0 - 151
  Mono:
  Front Left: Playback 151 [100%] [-0.06dB] [on]
  Front Right: Playback 151 [100%] [-0.06dB] [on]
Simple mixer control 'PCM',1
  Capabilities: pvolume pvolume-joined
  Playback channels: Mono
  Limits: Playback 0 - 151
  Mono: Playback 44 [29%] [-20.13dB]
Simple mixer control 'Mic',0
  Capabilities: cvolume cvolume-joined cswitch cswitch-joined
  Capture channels: Mono
  Limits: Capture 0 - 151
  Mono: Capture 151 [100%] [-0.06dB] [on]
"""

    def test_parse_amixer_of_real_v9_pro(self):
        c = AU.parse_amixer(self.AMIXER_V9)
        self.assertEqual([(x["name"], x["index"], x["pct"]) for x in c], [("PCM", 0, 100), ("PCM", 1, 29)])
        self.assertAlmostEqual(c[1]["db"], -20.13)
        # so o controle que o sistema nao usa (PCM,1)
        self.assertEqual([(x["index"], x["pct"]) for x in AU.stuck_volumes(c)], [(1, 29)])

    def test_fix_hw_volume_lowers_system_first(self):
        import subprocess as sp
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            out = self.AMIXER_V9 if cmd[-1] == "scontents" else "Volume: 1.00\n" if cmd[1] == "get-volume" else ""
            return sp.CompletedProcess(cmd, 0, out, "")
        sink = dict(id=1, name="alsa_output.usb-MCHOSE", desc="MCHOSE V9 PRO", cls="Audio/Sink", vendor="0x291d",
                    api="alsa", props={"alsa.card": 1})
        old = AU.shutil.which
        AU.shutil.which = lambda n: "/usr/bin/" + n
        try:
            done = AU.fix_hw_volume([sink], run=run)
        finally:
            AU.shutil.which = old
        self.assertEqual([(c["index"], c["pct"]) for c in done], [(1, 29)])
        i_low = calls.index(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.40"])
        i_up = calls.index(["amixer", "-c", "1", "-q", "sset", "PCM,1", "100%"])
        self.assertLess(i_low, i_up)  # baixa o sistema ANTES de subir o fone
        self.assertNotIn(["amixer", "-c", "1", "-q", "sset", "PCM,0", "100%"], calls)  # o do sistema fica

    def test_settings_saved(self):
        AU.save_settings(preset="FPS", gains=AU.PRESETS["FPS"])
        self.assertEqual(AU.settings()["gains"], AU.PRESETS["FPS"])


if __name__ == "__main__":
    unittest.main()

"""Sincronizar ajustes entre PCs, luzes sincronizadas, regras por jogo, recursos e alvo do som."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from logimouse import audio as AU  # noqa: E402
from logimouse import config  # noqa: E402
from logimouse import demo as D  # noqa: E402
from logimouse import hidpp as H  # noqa: E402
from logimouse import profiles as P  # noqa: E402
from logimouse import sync as SY  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("XDG_CONFIG_HOME")
        self.old_host = SY.host_id
        config.DRY_RUN = False
        D._shared = None
        D._shared_logi_headset = None

    def tearDown(self):
        SY.host_id = self.old_host
        D._shared = None
        D._shared_logi_headset = None
        if self.old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.old
        self.tmp.cleanup()

    def pc(self, name):
        """Troca para o 'computador' name (pasta de config e identidade proprias)."""
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name, name)
        SY.host_id = lambda: name


class TwoComputers(Base):
    def test_settings_travel_between_computers(self):
        cloud = os.path.join(self.tmp.name, "Google Drive")
        os.makedirs(cloud)
        self.pc("casa")
        SY.connect(cloud)
        P.save_macros([{"name": "Recarregar", "mode": "once", "steps": [{"t": "down", "k": "r"}, {"t": "up", "k": "r"}]}])
        AU.save_settings(preset="FPS", gains=AU.PRESETS["FPS"], sink="alsa_output.casa")
        doc = json.load(open(os.path.join(cloud, SY.FILE)))
        self.assertEqual(doc["host"], "casa")
        self.assertNotIn("sink", doc["data"]["audio"])  # nome da saida e de cada PC

        self.pc("trabalho")
        AU.save_settings(sink="alsa_output.trabalho")
        changed = SY.connect(cloud)
        self.assertIn("macros", changed)
        self.assertEqual(P.macros()[0]["name"], "Recarregar")
        self.assertEqual(AU.settings()["preset"], "FPS")
        self.assertEqual(AU.settings()["sink"], "alsa_output.trabalho")  # a saida deste PC ficou

        config.set_option("lights_off", True)  # mudou no trabalho...
        self.pc("casa")
        self.assertIn("lights_off", SY.pull())  # ...e chega em casa
        self.assertTrue(config.get_option("lights_off"))
        self.assertEqual(SY.pull(), [])  # so uma vez

    def test_connect_reads_before_writing(self):
        cloud = os.path.join(self.tmp.name, "Dropbox")
        os.makedirs(cloud)
        self.pc("a")
        SY.connect(cloud)
        config.set_option("notify_low", False)
        self.pc("b")  # PC novo, com o padrao notify_low=True
        SY.connect(cloud)
        self.assertFalse(config.get_option("notify_low"))  # nao apagou o que o outro PC gravou

    def test_off_and_missing_folder(self):
        self.pc("a")
        self.assertEqual(SY.pull(), [])
        SY.connect(os.path.join(self.tmp.name, "nao-existe"))
        config.set_option("notify_low", False)  # nao quebra sem a pasta
        self.assertEqual(SY.status(), "A pasta não existe mais")


class SyncedLightsAndGameRules(Base):
    def test_synced_lights_on_every_zone(self):
        self.pc("a")
        devs, _ = D.discover_demo()
        config.set_option("lights_sync", {"effect": 1, "color": [9, 8, 7], "period": 3000})
        for d in devs:
            done, failed = H.apply_settings(d, config.settings_to_apply(d.name))
            self.assertEqual(failed, [])
        self.assertEqual(D.shared_mouse().mouse_leds[0], (1, (9, 8, 7)))
        self.assertEqual({v for v in D.shared_logi_headset().leds.values()}, {(1, (9, 8, 7))})

    def test_game_rule_switches_headset_eq_and_lights_and_back(self):
        from logimouse import tray as T
        self.pc("a")
        devs, _ = D.discover_demo()
        mouse = next(d for d in devs if d.ui == "mouse")
        P.ensure_default(mouse.name, {"dpis": [800], "rate": 1000})
        P.set_rules(mouse.name, [{"match": "valorant", "profile": "Padrão", "eq": "FPS", "lights": "off"}])

        class Mon:
            devices = devs
            info = {d: {"online": True} for d in devs}
        progs = {"value": {"bash"}}
        sw = T.ProfileSwitcher(Mon(), programs=lambda: progs["value"])
        head = D.shared_logi_headset()
        before = list(head.gains)
        progs["value"] = {"bash", "valorant.exe"}
        sw.step()
        self.assertEqual(head.gains, AU.PRESETS["FPS"])
        self.assertEqual({v[0] for v in head.leds.values()}, {0})
        progs["value"] = {"bash"}
        sw.step()
        self.assertEqual(head.gains, before)  # voltou como estava


class Capabilities(Base):
    def test_capabilities_from_the_device(self):
        from logimouse import window as W
        self.pc("a")
        devs, _ = D.discover_demo()
        head = next(d for d in devs if d.ui == "logi_headset")
        caps = {name: where for name, where, _ in W.capabilities(head, H.read_all(head))}
        self.assertEqual(caps["Equalizador gravado no fone"], "aparelho")
        self.assertEqual(caps["Retorno da voz"], "aparelho")
        self.assertEqual(caps["Luzes"], "aparelho")
        self.assertEqual(caps["Redução de ruído por IA (RNNoise)"], "LogiMouse")
        self.assertEqual(caps["Teclas G"], "ainda não")
        mouse = next(d for d in devs if d.ui == "mouse")
        s = H.read_all(mouse)
        s["onboard"] = {"x": 1}
        mcaps = {name for name, _, _ in W.capabilities(mouse, s)}
        self.assertTrue({"DPI", "Macros", "Memória de perfis (botões e DPI no mouse)"} <= mcaps)
        self.assertNotIn("Redução de ruído por IA (RNNoise)", mcaps)


class AudioTarget(Base):
    def nodes(self):
        def n(i, name, desc, cls, vid=""):
            return dict(id=i, name=name, desc=desc, cls=cls, vendor=vid, api="alsa", props={})
        return [n(1, "alsa_output.usb-MCHOSE", "MCHOSE V9 PRO", "Audio/Sink", "0x291d"),
                n(2, "alsa_output.usb-Logitech_G935", "G935 Gaming Headset Estéreo analógico", "Audio/Sink", "0x046d"),
                n(3, "alsa_input.usb-Logitech_G935", "G935 Gaming Headset Mono", "Audio/Source", "0x046d")]

    def test_any_headset_can_be_the_target(self):
        self.pc("a")
        self.assertEqual(AU.hints_for("G935 Gaming Headset"), ["g935"])
        self.assertEqual(AU.hints_for("MCHOSE V9 PRO"), AU.MCHOSE_HINTS)
        sink, src = AU.find_headset(self.nodes(), AU.hints_for("G935 Gaming Headset"))
        self.assertEqual((sink["id"], src["id"]), (2, 3))  # nao pega o MCHOSE pelo fabricante
        self.assertEqual(AU.find_headset(self.nodes())[0]["id"], 1)  # sem escolha: MCHOSE
        AU.save_settings(hints=["g935"])
        self.assertEqual(AU.find_headset(self.nodes())[0]["id"], 2)


if __name__ == "__main__":
    unittest.main()

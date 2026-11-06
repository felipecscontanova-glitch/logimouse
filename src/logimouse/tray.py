"""
Icone na bandeja: mostra a bateria e reaplica seus ajustes quando o mouse reconecta.

O Monitor roda numa thread propria e nao depende de GTK (da para testar sozinho).
O TrayApp e so a parte visual (AppIndicator).
"""

import os
import queue
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback

from . import APP_NAME, __version__
from . import config
from . import headset as HS
from . import hidpp as H
from . import update as U


def log(*args):
    print(time.strftime("%H:%M:%S"), "[logimouse]", *args, file=sys.stderr, flush=True)


class Monitor:
    RESCAN = 5          # s: confere se um receptor/mouse Bluetooth apareceu ou sumiu
    FULL_RETRY = 30     # s: procura de novo quando nao ha nenhum mouse
    RETRY_OFFLINE = 20  # s: tenta falar com um mouse desligado
    BATTERY = 120       # s: le a bateria (o mouse tambem avisa sozinho quando muda)
    SETTLE = 1.5        # s: espera o mouse terminar de conectar antes de reaplicar
    LOW = 15            # %: aviso de bateria baixa

    def __init__(self, discover_fn=H.discover, nodes_fn=H.hidpp_nodes,
                 on_change=None, on_low_battery=None, clock=time.monotonic):
        self.discover_fn = discover_fn
        self.nodes_fn = nodes_fn
        self.on_change = on_change or (lambda snap: None)
        self.on_low_battery = on_low_battery or (lambda name, pct: None)
        self.clock = clock
        self.devices = []
        self.info = {}
        self.pending = {}
        self.commands = queue.Queue()
        self.node_key = None
        self.need_rediscover = True
        self.next_rescan = 0.0
        self.next_full = 0.0
        self.next_battery = 0.0
        self._changed = False
        self._stop = threading.Event()

    # ---- interface publica ----
    def reapply_now(self):
        self.commands.put("reapply")

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                self.step(1.0)
            except Exception:  # noqa: BLE001 - a bandeja nao pode morrer por um erro de leitura
                log("erro inesperado:\n" + traceback.format_exc())
                self.need_rediscover = True
                self._stop.wait(2)

    def snapshot(self):
        out = []
        for d in self.devices:
            i = self.info[d]
            out.append(dict(name=d.name, kind=d.kind_name, pointer=d.is_pointer, connection=d.connection,
                            online=i["online"], battery=i["battery"], last_apply=i["last_apply"]))
        return out

    # ---- ciclo ----
    def step(self, timeout=1.0):
        now = self.clock()
        self._commands(now)

        if now >= self.next_rescan:
            self.next_rescan = now + self.RESCAN
            key = self._nodes_key()
            if key != self.node_key or (not self.devices and now >= self.next_full):
                self.need_rediscover = True
        if self.need_rediscover:
            self._rediscover(now)

        for dev, (due, reconnect) in list(self.pending.items()):
            if now >= due:
                self.pending.pop(dev, None)
                self._check(dev, reconnect)

        if now >= self.next_battery:
            self.next_battery = now + self.BATTERY
            for d in self.devices:
                if self.info[d]["online"]:
                    self._poll_battery(d)

        for d in self.devices:
            i = self.info[d]
            if not i["online"] and now >= i["next_retry"] and d not in self.pending:
                i["next_retry"] = now + self.RETRY_OFFLINE
                self._schedule(d, 0, reconnect=True)

        self._wait_events(timeout)

        if self._changed:
            self._changed = False
            self.on_change(self.snapshot())

    def _commands(self, now):
        while True:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                return
            if cmd == "reapply":
                for d in self.devices:
                    self._schedule(d, 0, reconnect=True, force=True)

    def _nodes_key(self):
        try:
            return tuple(sorted(n["path"] for n in self.nodes_fn()))
        except OSError:
            return ()

    def _rediscover(self, now):
        self.need_rediscover = False
        self.next_full = now + self.FULL_RETRY
        old_names = {d.name: self.info[d] for d in self.devices}
        for t in {id(d.t): d.t for d in self.devices}.values():
            t.close()
        try:
            devices, problems = self.discover_fn()
        except Exception as e:  # noqa: BLE001
            devices, problems = [], [str(e)]
        for p in problems:
            log(p)
        self.devices, self.info, self.pending = devices, {}, {}
        self.node_key = self._nodes_key()
        for d in devices:
            for fid in (H.F_WIRELESS_STATUS, H.F_UNIFIED_BATTERY, H.F_BATTERY_STATUS):
                try:
                    d.feature(fid)
                except H.DEVICE_ERRORS:
                    pass
            prev = old_names.get(d.name)
            self.info[d] = dict(online=True, battery=prev["battery"] if prev else None,
                                last_apply=prev["last_apply"] if prev else None,
                                next_retry=0.0, low_sent=prev["low_sent"] if prev else False)
            # acabou de aparecer (boot, receptor recolocado, Bluetooth reconectou): reaplica
            self._schedule(d, 0, reconnect=True)
        log("dispositivos:", ", ".join(d.name for d in devices) or "nenhum")
        self._changed = True

    def _schedule(self, dev, delay, reconnect=False, force=False):
        due = self.clock() + delay
        if dev in self.pending:
            old_due, old_rc = self.pending[dev]
            due, reconnect = min(due, old_due), reconnect or old_rc
        self.pending[dev] = (due, reconnect)
        if force:
            self.info[dev]["force"] = True

    def _set_offline(self, dev):
        i = self.info[dev]
        if i["online"]:
            log(f"{dev.name}: desligado / fora de alcance")
            self._changed = True
        i["online"] = False
        i["next_retry"] = self.clock() + self.RETRY_OFFLINE

    def _check(self, dev, reconnect):
        i = self.info[dev]
        try:
            dev.ping(timeout=1.0)
        except H.DEVICE_ERRORS:
            self._set_offline(dev)
            return
        was_online = i["online"]
        i["online"] = True
        force = i.pop("force", False)
        if force or ((reconnect or not was_online) and config.get_option("reapply")):
            saved = config.device_settings(dev.name)
            if saved:
                done, failed = H.apply_settings(dev, saved)
                i["last_apply"] = dict(at=time.time(), done=done, failed=failed)
                log(f"{dev.name}: reaplicado {', '.join(done) or 'nada'}"
                    + (f" (falhou: {', '.join(failed)})" if failed else ""))
        self._poll_battery(dev)
        self._changed = True

    def _poll_battery(self, dev):
        try:
            b = dev.battery()
        except H.HidppError as e:
            if e.hidpp10:
                self._set_offline(dev)
                return
            b = H.sysfs_battery(dev.name)
        except H.NotSupported:
            b = H.sysfs_battery(dev.name)
        except (H.HidppTimeout, OSError):
            self._set_offline(dev)
            return
        self._battery(dev, b)

    def _battery(self, dev, b):
        i = self.info[dev]
        if b != i["battery"]:
            i["battery"] = b
            self._changed = True
        v = H.battery_value(b)
        if v is None:
            return
        if b["charging"] or v > self.LOW + 10:
            i["low_sent"] = False
        elif v <= self.LOW and not i["low_sent"] and config.get_option("notify_low"):
            i["low_sent"] = True
            self.on_low_battery(dev.name, v)

    # ---- eventos que o receptor/mouse mandam sozinhos ----
    def _wait_events(self, timeout):
        import select
        now = self.clock()
        if self.pending:
            timeout = max(0.0, min(timeout, min(due for due, _ in self.pending.values()) - now))
        transports = {id(d.t): d.t for d in self.devices}
        fds = {}
        for t in transports.values():
            try:
                fds[t.fileno()] = t
            except (AttributeError, OSError):
                pass
        if not fds:
            self._stop.wait(timeout)
            return
        try:
            ready, _, _ = select.select(list(fds), [], [], timeout)
        except (OSError, ValueError):
            self.need_rediscover = True
            return
        for fd in ready:
            t = fds[fd]
            for _ in range(256):
                try:
                    pkt = t.read(0)
                except OSError:
                    self.need_rediscover = True  # receptor tirado da USB
                    break
                if pkt is None:
                    break
                self.handle_packet(t, pkt)

    def _find(self, t, idx):
        for d in self.devices:
            if d.t is t and (d.index == idx or d.index == (idx ^ 0xFF)):
                return d
        return None

    def handle_packet(self, t, r):
        if len(r) < 4:
            return
        rid, idx = r[0], r[1]
        dev = self._find(t, idx)
        if rid in (0x10, 0x11):
            if rid == 0x10 and r[2] == 0x41 and len(r) > 4:
                link_up = not (r[4] & 0x40)
                if dev is None:
                    if link_up and self.clock() >= self.next_full:
                        self.need_rediscover = True  # mouse que estava desligado quando procuramos
                elif link_up:
                    self._schedule(dev, self.SETTLE, reconnect=True)
                else:
                    self._set_offline(dev)
                return
            if dev is None:
                return
            if rid == 0x11 and (r[3] & 0x0F) == 0 and len(r) > 4:
                fi = r[2]
                if fi and fi == dev.cached_feature(H.F_WIRELESS_STATUS):
                    self._schedule(dev, self.SETTLE, reconnect=True)
                    return
                b = dev.battery_from_event(fi, bytes(r[4:]).ljust(16, b"\x00"))
                if b is not None:
                    self.info[dev]["online"] = True
                    self._battery(dev, b)
                    return
            if not self.info[dev]["online"]:
                self._schedule(dev, self.SETTLE, reconnect=True)
        elif rid in (0x20, 0x21) and dev is not None:
            if r[2] == 0x42:  # aviso do receptor: conexao do dispositivo mudou
                if r[3] == 0x01:
                    self._set_offline(dev)
                else:
                    self._schedule(dev, self.SETTLE, reconnect=True)
            elif not self.info[dev]["online"]:
                self._schedule(dev, self.SETTLE, reconnect=True)


class HeadsetWatcher:
    """Bateria dos headsets: pergunta de tempos em tempos e escuta o que o receptor manda sozinho."""

    POLL = 60       # s entre perguntas de bateria
    OFF_POLL = 30   # s entre tentativas quando o fone esta desligado
    RESCAN = 10     # s: confere se um receptor apareceu/sumiu
    LOW = 15

    def __init__(self, discover_fn=HS.discover, nodes_fn=HS.mchose_nodes,
                 on_change=None, on_low_battery=None, clock=time.monotonic):
        self.discover_fn = discover_fn
        self.nodes_fn = nodes_fn
        self.on_change = on_change or (lambda snap: None)
        self.on_low_battery = on_low_battery or (lambda name, pct: None)
        self.clock = clock
        self.headsets = []
        self.info = {}
        self.node_key = None
        self.next_rescan = 0.0
        self.next_full = 0.0
        self._changed = False
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                self.step(1.0)
            except Exception:  # noqa: BLE001
                log("erro inesperado (headset):\n" + traceback.format_exc())
                self.node_key = None
                self._stop.wait(5)

    def snapshot(self):
        return [dict(name=h.name, kind=h.kind_name, pointer=False, headset=True, connection=h.connection,
                     online=self.info[h]["online"], battery=self.info[h]["battery"], last_apply=None)
                for h in self.headsets]

    def _key(self):
        try:
            return tuple(sorted(n["path"] for n in self.nodes_fn()))
        except OSError:
            return ()

    def _rediscover(self, now):
        old = {h.name: self.info[h] for h in self.headsets}
        for h in self.headsets:
            h.close()
        try:
            self.headsets, problems = self.discover_fn()
        except Exception as e:  # noqa: BLE001
            self.headsets, problems = [], [str(e)]
        for p in problems:
            log(p)
        self.info = {}
        for h in self.headsets:
            prev = old.get(h.name)
            self.info[h] = dict(online=prev["online"] if prev else True,
                                battery=prev["battery"] if prev else None,
                                low_sent=prev["low_sent"] if prev else False, next_poll=now)
        self.node_key = self._key()
        self.next_full = now + 5 * self.POLL  # UPower: Bluetooth liga e desliga sem mudar os receptores
        if self.headsets or old:
            log("headsets:", ", ".join(h.name for h in self.headsets) or "nenhum")
        self._changed = True

    def step(self, timeout=1.0):
        now = self.clock()
        if now >= self.next_rescan:
            self.next_rescan = now + self.RESCAN
            if self._key() != self.node_key or now >= self.next_full:
                self._rediscover(now)
        for h in self.headsets:
            i = self.info[h]
            if now >= i["next_poll"]:
                self._poll(h, now)
        self._listen(timeout)
        if self._changed:
            self._changed = False
            self.on_change(self.snapshot())

    def _poll(self, h, now):
        i = self.info[h]
        try:
            b = h.battery()
        except HS.HeadsetError as e:
            if i["online"]:
                log(f"{h.name}: {e}")
                self._changed = True
            i["online"] = False
            i["next_poll"] = now + self.OFF_POLL
            if isinstance(e, HS.HeadsetTimeout):
                return
            self.node_key = None  # receptor tirado: procura de novo
            return
        i["next_poll"] = now + self.POLL
        self._battery(h, b)

    def _battery(self, h, b):
        i = self.info[h]
        if not i["online"] or b != i["battery"]:
            self._changed = True
        i["online"] = True
        i["battery"] = b
        v = H.battery_value(b)
        if v is None:
            return
        if b.get("charging") or v > self.LOW + 10:
            i["low_sent"] = False
        elif v <= self.LOW and not i["low_sent"] and config.get_option("notify_low"):
            i["low_sent"] = True
            self.on_low_battery(h.name, v)

    def _listen(self, timeout):
        ports = {}
        for h in self.headsets:
            t = getattr(h, "t", None)
            if t is not None:
                try:
                    ports[t.fileno()] = h
                except (AttributeError, OSError):
                    pass
        if not ports:
            self._stop.wait(timeout)
            return
        try:
            ready, _, _ = select.select(list(ports), [], [], timeout)
        except (OSError, ValueError):
            self.node_key = None
            return
        for fd in ready:
            h = ports[fd]
            for _ in range(64):
                try:
                    pkt = h.t.read(0)
                except OSError:
                    self.node_key = None
                    break
                if pkt is None:
                    break
                b = h.parse(pkt)
                if b is not None and b["percent"]:
                    self._battery(h, b)


# --------------------------------------------------------------------------
# Parte visual
# --------------------------------------------------------------------------
def _notify(title, body):
    if shutil.which("notify-send"):
        try:
            subprocess.Popen(["notify-send", "-a", APP_NAME, "-i", "input-mouse", title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


class TrayApp:
    def __init__(self, demo=False):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk
        AI = None
        for name in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(name, "0.1")
                AI = __import__("gi.repository." + name, fromlist=[name])
                break
            except (ImportError, ValueError):
                continue
        if AI is None:
            raise RuntimeError("AppIndicator não encontrado")
        self.Gtk, self.GLib, self.AI = Gtk, GLib, AI
        self.demo = demo
        self.snap = []
        self.mouse_snap = []
        self.head_snap = []
        self._sig = None
        self._building = False

        self.ind = AI.Indicator.new("logimouse", "input-mouse-symbolic",
                                    AI.IndicatorCategory.HARDWARE)
        self.ind.set_title(APP_NAME)
        self.ind.set_status(AI.IndicatorStatus.ACTIVE)

        if demo:
            from . import demo as D
            disc, nodes = D.discover_demo, D.demo_nodes
            self.fake = D.shared_mouse()
            hdisc, hnodes = D.discover_demo_headsets, (lambda: [])
        else:
            disc, nodes = H.discover, H.hidpp_nodes
            hdisc, hnodes = HS.discover, HS.mchose_nodes
        self.monitor = Monitor(disc, nodes,
                               on_change=lambda s: GLib.idle_add(self.update, s),
                               on_low_battery=lambda n, p: GLib.idle_add(
                                   _notify, "Bateria do mouse baixa", f"{n}: {p}%. Hora de carregar."))
        self.headsets = HeadsetWatcher(hdisc, hnodes,
                                       on_change=lambda s: GLib.idle_add(self.update_headsets, s),
                                       on_low_battery=lambda n, p: GLib.idle_add(
                                           _notify, "Bateria do headset baixa", f"{n}: {p}%. Hora de carregar."))
        self.update_info = None
        self._upd_lock = threading.Lock()
        self._upd_stop = threading.Event()
        self.update([])
        threading.Thread(target=self.monitor.run, daemon=True).start()
        threading.Thread(target=self.headsets.run, daemon=True).start()
        if not demo:
            threading.Thread(target=self._update_loop, daemon=True).start()
        for s in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, s, self.quit)
        # SIGHUP: o painel instalou uma versao nova, reabre com ela
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, self.restart)

    def _primary(self):
        online = [d for d in self.mouse_snap if d["online"] and d["battery"]]
        pointers = [d for d in online if d["pointer"]]
        return (pointers or online or [None])[0]

    @staticmethod
    def _bat_label(d):
        return H.battery_text(d["battery"]) + (" ⚡" if d["battery"].get("charging") else "")

    def update_headsets(self, snap):
        self.head_snap = snap
        return self.update(self.mouse_snap)

    def update(self, snap):
        self.mouse_snap = snap
        self.snap = snap + self.head_snap
        parts = []
        p = self._primary()
        if p:
            parts.append(self._bat_label(p))
        head = next((d for d in self.head_snap if d["online"] and d["battery"]), None)
        if head:
            parts.append("🎧 " + self._bat_label(head))
        self.ind.set_label("  ".join(parts), "100% ⚡  🎧 100% ⚡")
        sig = repr([(d["name"], d["online"], d["battery"], d["last_apply"] and d["last_apply"]["at"])
                    for d in self.snap]) + repr((config.autostart_enabled(), config.get_option("reapply"),
                                            config.get_option("notify_low"), config.get_option("auto_update"),
                                            self.update_info and self.update_info["latest"]))
        if sig != self._sig:
            self._sig = sig
            self.build_menu()
        return False

    def build_menu(self):
        Gtk = self.Gtk
        self._building = True
        menu = Gtk.Menu()

        def item(text, cb=None, sensitive=True):
            mi = Gtk.MenuItem(label=text)
            mi.set_sensitive(sensitive and cb is not None)
            if cb:
                mi.connect("activate", lambda *_: cb())
            menu.append(mi)
            return mi

        def check(text, active, cb):
            mi = Gtk.CheckMenuItem(label=text)
            mi.set_active(active)
            mi.connect("toggled", lambda w: None if self._building else cb(w.get_active()))
            menu.append(mi)

        if not self.snap:
            item("Nenhum mouse ou headset encontrado")
        for d in self.snap:
            icon = "🎧 " if d.get("headset") else ""
            if d["online"] and d["battery"]:
                b = d["battery"]
                shown = b.get("status") if b.get("status") not in (None, "", "Ligado") else ""
                txt = f"{icon}{d['name']}: {H.battery_text(b)}" + (f" · {shown}" if shown else "")
            elif d["online"]:
                txt = f"{icon}{d['name']}: sem leitura de bateria"
            else:
                txt = f"{icon}{d['name']}: desligado"
            item(txt)
            la = d["last_apply"]
            if la and la["done"]:
                item("    ajustes reaplicados às " + time.strftime("%H:%M", time.localtime(la["at"])))
        menu.append(Gtk.SeparatorMenuItem())
        item("Abrir painel", self.open_panel)
        item("Reaplicar meus ajustes agora", self.monitor.reapply_now)
        menu.append(Gtk.SeparatorMenuItem())
        check("Iniciar com o sistema", config.autostart_enabled(), self.set_autostart)
        check("Reaplicar ao reconectar", bool(config.get_option("reapply")),
              lambda v: (config.set_option("reapply", v), self.refresh()))
        check("Avisar com bateria baixa", bool(config.get_option("notify_low")),
              lambda v: (config.set_option("notify_low", v), self.refresh()))
        check("Atualizar automaticamente", bool(config.get_option("auto_update")),
              lambda v: (config.set_option("auto_update", v), self.refresh()))
        menu.append(Gtk.SeparatorMenuItem())
        item(f"Versão {__version__}")
        if self.update_info:
            item(f"Instalar a versão {self.update_info['latest']}", self.check_now)
        if not self.demo:
            item("Procurar atualização agora", self.check_now)
        if self.demo:
            menu.append(Gtk.SeparatorMenuItem())
            item("[demo] desligar e ligar o mouse", self.demo_cycle)
        menu.append(Gtk.SeparatorMenuItem())
        item("Sair", self.quit)
        menu.show_all()
        self.ind.set_menu(menu)
        self.menu = menu
        self._building = False

    def refresh(self):
        self._sig = None
        self.update(self.snap)

    def set_autostart(self, on):
        config.set_autostart(on)
        self.refresh()

    def open_panel(self):
        args = ["--demo"] if self.demo else []
        try:
            subprocess.Popen(config.launcher_command(*args), env=config.launcher_env(),
                             start_new_session=True)
        except OSError as e:
            _notify("Não deu para abrir o painel", str(e))

    def demo_cycle(self):
        self.fake.power_off()
        self.GLib.timeout_add(1500, lambda: (self.fake.power_on(), False)[1])

    # ---- atualizacao automatica ----
    FIRST_CHECK = 120  # s depois de abrir (a internet pode ainda nao estar pronta no login)

    def _update_loop(self):
        last = float(config.get_option("last_update_check") or 0)
        wait = max(self.FIRST_CHECK, last + U.CHECK_EVERY - time.time())
        while not self._upd_stop.wait(wait):
            if config.get_option("auto_update"):
                self._check_update(manual=False)
            wait = U.CHECK_EVERY

    def check_now(self):
        threading.Thread(target=self._check_update, kwargs=dict(manual=True), daemon=True).start()

    def _check_update(self, manual):
        if not self._upd_lock.acquire(blocking=False):
            return
        try:
            config.set_option("last_update_check", time.time())
            try:
                info = U.check()
            except U.UpdateError as e:
                log("atualização:", e)
                if manual:
                    _notify("Não deu para procurar atualização", str(e))
                return
            self.update_info = info if info["newer"] else None
            self.GLib.idle_add(self.refresh)
            if not info["newer"]:
                if manual:
                    _notify("LogiMouse está atualizado", f"A versão {info['current']} é a mais nova.")
                return
            log(f"versão nova no GitHub: {info['latest']}")
            if not U.can_self_update():
                if manual:
                    _notify(f"LogiMouse {info['latest']} disponível", U.why_not_self_update())
                return
            self._install(info["ref"], info["latest"])
        finally:
            self._upd_lock.release()

    def _install(self, ref, version):
        try:
            res = U.install(ref, version)
        except (U.UpdateError, OSError) as e:
            log("atualização falhou:", e)
            _notify("A atualização do LogiMouse falhou", f"{e}. Continua na versão {__version__}.")
            return
        msg = f"Atualizado da versão {__version__} para a {res['version']}."
        if res["needs_installer"]:
            msg += " Rode o instalar.sh de novo para atualizar a permissão de acesso ao mouse."
        log(msg)
        _notify("LogiMouse atualizado", msg)
        self.GLib.idle_add(self.restart)

    def restart(self):
        """Reabre a bandeja com a versao nova (mesmo processo, codigo novo)."""
        self.monitor.stop()
        self.headsets.stop()
        self._upd_stop.set()
        cmd = config.launcher_command("--tray")
        try:
            os.execvpe(cmd[0], cmd, config.launcher_env())
        except OSError as e:
            log("não deu para reiniciar:", e)
            _notify("LogiMouse atualizado", "Feche e abra o ícone para usar a versão nova.")
        return False

    def quit(self, *_):
        self.monitor.stop()
        self.headsets.stop()
        self._upd_stop.set()
        self.Gtk.main_quit()
        return False

    def run(self):
        self.Gtk.main()


def run_tray(demo=False):
    H.Device.sw_id = 0x0C  # diferente do painel, para os dois poderem rodar juntos
    if demo:
        config.DRY_RUN = True
    lock = config.acquire_tray_lock()
    if lock is None:
        print("O LogiMouse já está rodando na bandeja.")
        return 0
    try:
        app = TrayApp(demo=demo)
    except (ImportError, ValueError, RuntimeError) as e:
        print(f"Não deu para criar o ícone na bandeja ({e}).\n"
              "Instale as bibliotecas e tente de novo:\n"
              "  Ubuntu/Debian: sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1\n"
              "  Fedora:        sudo dnf install python3-gobject libayatana-appindicator-gtk3\n"
              "  Arch:          sudo pacman -S python-gobject libayatana-appindicator\n"
              "No GNOME fora do Ubuntu, ative também a extensão 'AppIndicator and KStatusNotifierItem Support'.")
        return 1
    app.run()
    lock.close()
    return 0

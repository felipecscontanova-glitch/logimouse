"""Ajustes salvos, inicio automatico e caminhos do app."""

import fcntl
import json
import os
import shutil
import sys
import tempfile

APP_ID = "logimouse"


def _xdg(var, default):
    return os.environ.get(var) or os.path.expanduser(default)


def config_dir():
    return os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), APP_ID)


def config_file():
    return os.path.join(config_dir(), "config.json")


def autostart_file():
    return os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), "autostart", f"{APP_ID}.desktop")


def runtime_dir():
    return os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()


# Modo demonstracao: guarda tudo na memoria, sem mexer nos seus arquivos.
DRY_RUN = False
_memory = None

DEFAULTS = {"reapply": True, "notify_low": True, "auto_update": True, "last_update_check": 0, "devices": {}}


def load():
    global _memory
    if DRY_RUN:
        if _memory is None:
            _memory = json.loads(json.dumps(DEFAULTS))
        return json.loads(json.dumps(_memory))
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(config_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update(data)
    except (OSError, ValueError):
        pass
    if not isinstance(cfg.get("devices"), dict):
        cfg["devices"] = {}
    return cfg


def save(cfg):
    global _memory
    if DRY_RUN:
        _memory = json.loads(json.dumps(cfg))
        return
    os.makedirs(config_dir(), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config_dir(), prefix=".config-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, config_file())


class _locked:
    """Trava o config.json enquanto le-modifica-grava (painel e bandeja escrevem nele)."""

    def __enter__(self):
        self.fh = None
        if DRY_RUN:
            return self
        try:
            os.makedirs(config_dir(), exist_ok=True)
            self.fh = open(os.path.join(config_dir(), ".lock"), "a+")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except OSError:
            self.fh = None
        return self

    def __exit__(self, *exc):
        if self.fh is not None:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
        return False


def set_option(key, value):
    with _locked():
        cfg = load()
        cfg[key] = value
        save(cfg)


def get_option(key):
    return load().get(key, DEFAULTS.get(key))


def remember(device_name, **values):
    """Guarda os ajustes que a pessoa mudou para este mouse."""
    if not device_name:
        return
    with _locked():
        cfg = load()
        cfg["devices"].setdefault(device_name, {}).update(values)
        save(cfg)


def forget(device_name):
    with _locked():
        cfg = load()
        cfg["devices"].pop(device_name, None)
        save(cfg)


def device_settings(device_name):
    return dict(load()["devices"].get(device_name) or {})


# --------------------------------------------------------------------------
# Como abrir o app (para o atalho, o inicio automatico e o botao "Abrir painel")
# --------------------------------------------------------------------------
def installed_launcher():
    path = os.path.expanduser("~/.local/bin/logimouse")
    return path if os.access(path, os.X_OK) else None


def launcher_command(*args):
    """Lista para subprocess."""
    exe = installed_launcher() or shutil.which("logimouse")
    if exe:
        return [exe, *args]
    return [sys.executable, "-m", "logimouse", *args]


def launcher_env():
    env = dict(os.environ)
    if not (installed_launcher() or shutil.which("logimouse")):
        pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = pkg_parent + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _desktop_exec(*args):
    def q(s):
        return f'"{s}"' if any(c in s for c in ' \t"\\') else s
    exe = installed_launcher() or shutil.which("logimouse")
    if exe:
        return " ".join(q(a) for a in (exe, *args))
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return " ".join(q(a) for a in ("env", f"PYTHONPATH={pkg_parent}", sys.executable, "-m", "logimouse", *args))


def autostart_enabled():
    return os.path.exists(autostart_file())


def set_autostart(on):
    path = autostart_file()
    if not on:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=LogiMouse (bandeja)\n"
            "Comment=Bateria do mouse Logitech na barra e reaplica seus ajustes\n"
            f"Exec={_desktop_exec('--tray')}\n"
            "Icon=input-mouse\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            "X-GNOME-Autostart-Delay=5\n"
        )
    return True


# --------------------------------------------------------------------------
# Uma bandeja por vez
# --------------------------------------------------------------------------
def _lock_path():
    return os.path.join(runtime_dir(), f"{APP_ID}-tray-{os.getuid()}.lock")


def acquire_tray_lock():
    """Devolve o arquivo travado (mantenha aberto) ou None se ja ha uma bandeja rodando."""
    fh = open(_lock_path(), "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def tray_pid():
    """PID da bandeja rodando, ou None."""
    if not tray_running():
        return None
    try:
        with open(_lock_path()) as fh:
            return int(fh.read().strip() or 0) or None
    except (OSError, ValueError):
        return None


def restart_tray():
    """Pede para a bandeja reabrir (usado depois de uma atualizacao feita pelo painel)."""
    import signal
    pid = tray_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGHUP)
            return True
        except OSError:
            pass
    return False


def tray_running():
    try:
        fh = open(_lock_path(), "a+")
    except OSError:
        return False
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False
    finally:
        fh.close()


_TRAY_CHECK = """
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
ok = False
for name in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(name, "0.1")
        __import__("gi.repository." + name)
        ok = True
        break
    except (ImportError, ValueError):
        pass
raise SystemExit(0 if ok else 1)
"""


def tray_available():
    """Bibliotecas do icone na bandeja instaladas? (testa num processo separado)"""
    import subprocess
    try:
        return subprocess.run([sys.executable, "-c", _TRAY_CHECK], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

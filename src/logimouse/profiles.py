"""
Perfis do mouse guardados no computador, macros e troca automatica por aplicativo.

O G305 guarda um perfil por vez na memoria. Os outros ficam no config.json:

    "mouse_profiles": {
        "<nome do mouse>": {
            "active": "Padrão",
            "profiles": {"Padrão": {"dpis": [...], "default_dpi": 1, "shift_dpi": 0,
                                     "rate": 1000, "buttons": [{...}, ...]}},
            "rules": [{"match": "valorant", "profile": "Valorant"}]
        }
    },
    "macros": [{"name": "...", "mode": "once", "steps": [{"t": "down", "k": "r"}, ...]}]

A troca por aplicativo olha os processos abertos (/proc): no Wayland o sistema nao
diz qual janela esta em foco, entao vale "o programa esta aberto".
"""

import os

from . import config

DEFAULT_NAME = "Padrão"


def _all(cfg):
    mp = cfg.get("mouse_profiles")
    if not isinstance(mp, dict):
        mp = cfg["mouse_profiles"] = {}
    return mp


def device_data(device):
    data = _all(config.load()).get(device) or {}
    data.setdefault("active", DEFAULT_NAME)
    data.setdefault("profiles", {})
    data.setdefault("rules", [])
    return data


def save_device_data(device, data):
    with config._locked():
        cfg = config.load()
        _all(cfg)[device] = data
        config.save(cfg)


def ensure_default(device, profile_dict):
    """Na primeira vez, o que esta no mouse vira o perfil 'Padrão'."""
    data = device_data(device)
    if not data["profiles"]:
        data["profiles"][DEFAULT_NAME] = profile_dict
        data["active"] = DEFAULT_NAME
        save_device_data(device, data)
    return data


def put_profile(device, name, profile_dict, activate=False):
    name = (name or "").strip()
    if not name:
        raise ValueError("dê um nome ao perfil")
    data = device_data(device)
    data["profiles"][name] = profile_dict
    if activate:
        data["active"] = name
    save_device_data(device, data)
    return data


def delete_profile(device, name):
    data = device_data(device)
    if name == DEFAULT_NAME:
        raise ValueError("o perfil Padrão não pode ser apagado")
    data["profiles"].pop(name, None)
    data["rules"] = [r for r in data["rules"] if r.get("profile") != name]
    if data["active"] == name:
        data["active"] = DEFAULT_NAME
    save_device_data(device, data)
    return data


def set_rules(device, rules):
    data = device_data(device)
    data["rules"] = [{"match": r["match"].strip(), "profile": r["profile"]}
                     for r in rules if r.get("match", "").strip() and r.get("profile")]
    save_device_data(device, data)
    return data


# --------------------------------------------------------------------------
# Macros
# --------------------------------------------------------------------------
def macros():
    m = config.load().get("macros")
    return m if isinstance(m, list) else []


def save_macros(items):
    from . import macros as M
    for m in items:
        if m:
            M.validate(m)
    if len(items) > M.TRIGGERS:
        raise ValueError("no máximo 12 macros")
    config.set_option("macros", items)


# --------------------------------------------------------------------------
# Processos abertos
# --------------------------------------------------------------------------
def running_programs(proc="/proc"):
    """{nome curto em minusculas} dos programas do usuario (comm e executavel)."""
    names = set()
    uid = os.getuid()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return names
    for pid in pids:
        base = os.path.join(proc, pid)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "comm")) as fh:
                names.add(fh.read().strip().lower())
            with open(os.path.join(base, "cmdline"), "rb") as fh:
                first = fh.read(4096).split(b"\0")[0].decode("utf-8", "replace")
            if first:
                # jogos do Proton: Z:\...\VALORANT.exe
                names.add(first.replace("\\", "/").rsplit("/", 1)[-1].lower())
        except OSError:
            continue
    names.discard("")
    return names


def wanted_profile(data, programs):
    """Perfil que deveria estar ativo agora (primeira regra que bate), ou Padrão."""
    for r in data.get("rules") or []:
        m = (r.get("match") or "").lower()
        if m and any(m in p for p in programs) and r.get("profile") in data["profiles"]:
            return r["profile"]
    return DEFAULT_NAME if DEFAULT_NAME in data["profiles"] else data.get("active")


def program_choices(proc="/proc"):
    """Programas abertos, para o botao 'Escolher programa aberto'."""
    skip = {"bash", "sh", "zsh", "systemd", "dbus-daemon", "pipewire", "wireplumber", "gnome-shell",
            "python3", "sleep", "cat", "grep", "ssh-agent", "gvfsd", "at-spi-bus-laun", "xdg-permission-",
            "sd_espeak-ng-mb", "pipewire-pulse", "xdg-desktop-por", "gsd-", "evolution-"}
    out = sorted(p for p in running_programs(proc)
                 if not any(p.startswith(s) for s in skip) and len(p) > 2)
    return out

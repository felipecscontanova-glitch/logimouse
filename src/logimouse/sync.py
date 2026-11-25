"""
Ajustes iguais em varios computadores, por uma pasta que voce ja sincroniza
(Google Drive, Dropbox, Nextcloud, Syncthing...).

O LogiMouse grava ali o arquivo logimouse-ajustes.json sempre que um ajuste muda, e
le o arquivo de tempos em tempos: se outro computador gravou algo mais novo, os
ajustes dele passam a valer aqui. Vale a ultima mudanca (de qualquer computador).

Vai para a pasta: perfis e regras dos mouses, macros, ajustes de cada dispositivo,
equalizador/microfone/surround e as opcoes de luzes e avisos. Fica so neste
computador: os nomes das saidas de som (mudam de um PC para outro), atualizacao,
inicio com o sistema e a propria pasta de sincronizacao.
"""

import hashlib
import json
import os
import socket
import time

from . import config

FILE = "logimouse-ajustes.json"
KEYS = ("mouse_profiles", "macros", "devices", "audio", "lights_off", "lights_sync", "notify_low", "reapply")
LOCAL_AUDIO = ("sink", "source")  # nomes do PipeWire: diferentes em cada computador


def host_id():
    """Identifica este computador sem expor o nome dele no arquivo."""
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:12]


def _payload(cfg):
    data = {k: cfg.get(k) for k in KEYS if k in cfg}
    if isinstance(data.get("audio"), dict):
        data["audio"] = {k: v for k, v in data["audio"].items() if k not in LOCAL_AUDIO}
    return data


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def path(cfg=None):
    cfg = cfg if cfg is not None else config.load()
    d = cfg.get("sync_dir")
    return os.path.join(os.path.expanduser(d), FILE) if d else None


def export(cfg):
    """Grava os ajustes na pasta, se mudaram desde a ultima vez. Devolve True se gravou."""
    p = path(cfg)
    if not p or config.DRY_RUN or not os.path.isdir(os.path.dirname(p)):
        return False
    data = _payload(cfg)
    digest = _digest(data)
    try:
        with open(p, encoding="utf-8") as fh:
            current = json.load(fh)
        if _digest(current.get("data") or {}) == digest:
            return False  # a pasta ja tem exatamente isso
    except (OSError, ValueError):
        pass
    doc = {"app": "LogiMouse", "updated_at": time.time(), "host": host_id(), "data": data}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)
    cfg["sync_seen"] = doc["updated_at"]  # quem chamou (config.save) grava junto
    return True


def pull():
    """Traz ajustes mais novos gravados por outro computador. Devolve as chaves que mudaram."""
    cfg = config.load()
    p = path(cfg)
    if not p or config.DRY_RUN:
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or doc.get("app") != "LogiMouse" or not isinstance(doc.get("data"), dict):
        return []
    if doc.get("host") == host_id() or float(doc.get("updated_at") or 0) <= float(cfg.get("sync_seen") or 0):
        return []
    changed = []
    with config._locked():
        cfg = config.load()
        for k, v in doc["data"].items():
            if k not in KEYS:
                continue
            if k == "audio" and isinstance(v, dict):
                v = dict(v, **{x: (cfg.get("audio") or {}).get(x, "") for x in LOCAL_AUDIO})
            if cfg.get(k) != v:
                cfg[k] = v
                changed.append(k)
        cfg["sync_seen"] = float(doc["updated_at"])
        config.save(cfg, export=False)
    return changed


def connect(folder):
    """Liga (ou desliga, folder vazio) a sincronizacao. Primeiro LE a pasta (o que outro PC
    gravou vale), so depois grava a copia deste computador. Devolve as chaves trazidas."""
    with config._locked():
        cfg = config.load()
        cfg["sync_dir"] = folder or ""
        cfg["sync_seen"] = 0
        config.save(cfg, export=False)
    if not folder:
        return []
    changed = pull()
    config.save(config.load())  # grava a copia na pasta (so se ela nao tiver exatamente isso)
    return changed


def status():
    """Texto curto para a tela."""
    cfg = config.load()
    p = path(cfg)
    if not p:
        return "Desligado"
    if not os.path.isdir(os.path.dirname(p)):
        return "A pasta não existe mais"
    try:
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
        when = time.strftime("%d/%m %H:%M", time.localtime(float(doc.get("updated_at") or 0)))
        who = "este computador" if doc.get("host") == host_id() else "outro computador"
        return f"Última mudança: {when}, por {who}"
    except (OSError, ValueError):
        return "Ainda sem ajustes na pasta"

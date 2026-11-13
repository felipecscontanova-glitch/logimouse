"""
Som do headset pelo PipeWire: equalizador, surround virtual 7.1, microfone sem ruido.

O M HUB faz isso no Windows; no Linux o LogiMouse monta uma cadeia de filtros do
PipeWire (libpipewire-module-filter-chain) e roda num servico do usuario
(~/.config/systemd/user/logimouse-audio.service):

    programas -> [Surround 7.1] -> [Equalizador] -> headset
    microfone do headset -> [passa-alta 80 Hz] -> [RNNoise] -> [EQ da voz] -> [ganho]
        -> microfone virtual "<headset> · sem ruído"

* Equalizador: 10 filtros biquad do proprio PipeWire (nada para instalar).
* Surround: convolucao com um HRIR no formato HeSuVi (14 canais). Sem arquivo da
  pessoa, o LogiMouse gera um a partir de um modelo de cabeca esferica
  (atraso entre os ouvidos + sombra da cabeca, Brown & Duda 1998) e reflexoes de sala.
* Reducao de ruido: plugin LADSPA do RNNoise (rede neural), se estiver instalado.
"""

import glob
import json
import math
import os
import shutil
import struct
import subprocess
import time
import wave

from . import config

FREQS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
FREQ_LABELS = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
PRESETS = {
    "Plano": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "FPS": [-4, -3, -2, 0, 1, 3, 5, 5, 3, 1],
    "Música": [4, 3, 1, 0, -1, 0, 1, 2, 3, 3],
    "Filmes": [5, 4, 2, 0, 0, 1, 2, 2, 1, 0],
    "Voz": [-5, -3, -1, 1, 3, 4, 3, 1, -1, -3],
    "Graves": [7, 6, 4, 2, 0, 0, 0, 0, 0, 0],
}
# EQ da voz: lista de (tipo, freq, Q, ganho)
VOICE = {
    "Natural": [],
    "Clara": [("bq_lowshelf", 160, 0.7, -3), ("bq_peaking", 3000, 1.0, 3), ("bq_highshelf", 7000, 0.7, 2)],
    "Grave": [("bq_lowshelf", 160, 0.7, 4), ("bq_highshelf", 6000, 0.7, -2)],
    "Rádio": [("bq_highpass", 300, 0.7, 0), ("bq_peaking", 1500, 1.0, 4), ("bq_lowpass", 3800, 0.7, 0)],
}
NR_LEVELS = [("Leve", "Voz mais natural", 50.0), ("Média", "Bom para jogos", 75.0),
             ("Forte", "Ambiente barulhento", 90.0)]

DEFAULTS = dict(eq_on=True, preset="Plano", gains=[0] * 10, surround=False, room=40, hrir_file="",
                nr=False, nr_level=1, voice="Natural", mic_gain=0, sidetone=False, default_out=True,
                default_in=True, sink="", source="", label="Headset")

EQ_SINK = "logimouse_eq"
SURROUND_SINK = "logimouse_surround"
MIC_SOURCE = "logimouse_mic"
SERVICE = "logimouse-audio.service"


def settings():
    s = dict(DEFAULTS)
    saved = config.load().get("audio")
    if isinstance(saved, dict):
        s.update(saved)
    if len(s.get("gains") or []) != 10:
        s["gains"] = [0] * 10
    return s


def save_settings(**changes):
    with config._locked():
        cfg = config.load()
        cur = dict(DEFAULTS)
        cur.update(cfg.get("audio") or {})
        cur.update(changes)
        cfg["audio"] = cur
        config.save(cfg)
    return settings()


# --------------------------------------------------------------------------
# Onde estao o headset e os plugins
# --------------------------------------------------------------------------
def _run(cmd, timeout=6, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except (OSError, subprocess.SubprocessError):
        return None


def pw_nodes():
    r = _run(["pw-dump"], timeout=8)
    if not r or r.returncode != 0:
        return []
    try:
        objs = json.loads(r.stdout)
    except ValueError:
        return []
    out = []
    for o in objs:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        p = (o.get("info") or {}).get("props") or {}
        out.append(dict(id=o.get("id"), name=p.get("node.name", ""), desc=p.get("node.description", ""),
                        cls=p.get("media.class", ""), vendor=str(p.get("device.vendor.id", "")),
                        api=p.get("device.api", ""), props=p))
    return out


def _is_headset(n, hints=("mchose", "c-media", "v9 pro", "x9")):
    text = f"{n['name']} {n['desc']} {n['props'].get('alsa.card_name', '')} {n['props'].get('device.product.name', '')}".lower()
    vid = n["vendor"].lower().replace("0x", "")
    return vid in ("291d", "3837") or any(h in text for h in hints)


def find_headset(nodes=None):
    """(sink, source) do headset: dicts do pw-dump ou None."""
    nodes = pw_nodes() if nodes is None else nodes
    sink = next((n for n in nodes if n["cls"] == "Audio/Sink" and _is_headset(n)), None)
    src = next((n for n in nodes if n["cls"] == "Audio/Source" and _is_headset(n)), None)
    return sink, src


LADSPA_DIRS = ["~/.local/lib/ladspa", "~/.ladspa", "/usr/local/lib/ladspa", "/usr/lib/ladspa",
               "/usr/lib/x86_64-linux-gnu/ladspa", "/usr/lib64/ladspa", "/usr/lib/aarch64-linux-gnu/ladspa"]


def rnnoise_plugin():
    extra = os.environ.get("LADSPA_PATH", "")
    for d in [*extra.split(":"), *LADSPA_DIRS]:
        if not d:
            continue
        for name in ("librnnoise_ladspa.so", "rnnoise_ladspa.so"):
            p = os.path.join(os.path.expanduser(d), name)
            if os.path.exists(p):
                return p
    return None


def pipewire_ok():
    return bool(shutil.which("pipewire") and shutil.which("pw-dump"))


# --------------------------------------------------------------------------
# HRIR gerado (modelo de cabeca esferica)
# --------------------------------------------------------------------------
RATE = 48000
# canais do formato HeSuVi, como no sink-virtual-surround-7.1-hesuvi.conf do PipeWire
HESUVI = [("FL", "L"), ("FL", "R"), ("SL", "L"), ("SL", "R"), ("RL", "L"), ("RL", "R"), ("FC", "L"),
          ("FR", "R"), ("FR", "L"), ("SR", "R"), ("SR", "L"), ("RR", "R"), ("RR", "L"), ("FC", "R")]
AZIMUTH = {"FL": -30, "FR": 30, "FC": 0, "SL": -90, "SR": 90, "RL": -135, "RR": 135}


def ear_response(azimuth, ear, room=0.4, n=1024, fs=RATE):
    """Resposta ao impulso de uma caixa em `azimuth` graus (positivo = direita) num ouvido."""
    a, c = 0.0875, 343.0
    ear_az = 90 if ear == "R" else -90
    theta = abs(((azimuth - ear_az) + 180) % 360 - 180)  # angulo entre a caixa e o ouvido
    th = math.radians(theta)
    # atraso (Woodworth): menor no ouvido voltado para a caixa
    if th < math.pi / 2:
        tau = (a / c) * (1 - math.cos(th))
    else:
        tau = (a / c) * (1 + th - math.pi / 2)
    delay = 8 + int(round(tau * fs))
    # sombra da cabeca: polo/zero de 1a ordem
    amin, tmin = 0.1, math.radians(150)
    alpha = (1 + amin / 2) + (1 - amin / 2) * math.cos(th / tmin * math.pi)
    w0 = c / a
    k = fs / w0
    b0, b1, a1 = (alpha * k + 1) / (k + 1), (1 - alpha * k) / (k + 1), (1 - k) / (k + 1)
    x = [0.0] * n
    x[delay] = 1.0
    # reflexoes da sala: algumas copias atrasadas, diferentes em cada ouvido
    seed = (int(azimuth) * 31 + (7 if ear == "R" else 3)) & 0xFFFF
    for i in range(6):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        d = delay + int(fs * (0.004 + 0.0025 * i)) + seed % 37
        if d < n:
            x[d] += room * 0.22 * (0.72 ** i) * (1 if seed & 1 else -1)
    y, xp, yp = [0.0] * n, 0.0, 0.0
    for i in range(n):
        yp = b0 * x[i] + b1 * xp - a1 * yp
        xp = x[i]
        y[i] = yp
    return y


def make_hrir(path, room=40):
    chans = [ear_response(AZIMUTH[spk], ear, room=max(0, min(100, room)) / 100.0) for spk, ear in HESUVI]
    peak = max(max(abs(v) for v in ch) for ch in chans) or 1.0
    scale = 0.5 / peak
    n = len(chans[0])
    frames = bytearray()
    for i in range(n):
        for ch in chans:
            frames += struct.pack("<i", int(max(-1.0, min(1.0, ch[i] * scale)) * 2147483647))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(len(chans))
        w.setsampwidth(4)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return path


# --------------------------------------------------------------------------
# Configuracao do PipeWire
# --------------------------------------------------------------------------
def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _eq_nodes(gains, prefix="eq"):
    nodes, links = [], []
    for i, (f, g) in enumerate(zip(FREQS, gains)):
        label = "bq_lowshelf" if i == 0 else "bq_highshelf" if i == len(FREQS) - 1 else "bq_peaking"
        nodes.append(f'{{ type = builtin name = {prefix}{i} label = {label} '
                     f'control = {{ "Freq" = {f}.0 "Q" = {1.0 if label == "bq_peaking" else 0.7} "Gain" = {float(g)} }} }}')
        if i:
            links.append(f'{{ output = "{prefix}{i - 1}:Out" input = "{prefix}{i}:In" }}')
    return nodes, links, f"{prefix}0:In", f"{prefix}{len(FREQS) - 1}:Out"


def _module(desc, nodes, links, inp, outp, capture, playback, channels=None):
    graph = ("filter.graph = {\n        nodes = [\n          " + "\n          ".join(nodes) + "\n        ]\n"
             + ("        links = [\n          " + "\n          ".join(links) + "\n        ]\n" if links else "")
             + f"        inputs = [ {inp} ]\n        outputs = [ {outp} ]\n      }}")
    ch = ""
    if channels:
        ch = f"      audio.channels = {len(channels)}\n      audio.position = [ {' '.join(channels)} ]\n"
    return ("  { name = libpipewire-module-filter-chain\n    flags = [ nofail ]\n    args = {\n"
            f"      node.description = {_q(desc)}\n      media.name = {_q(desc)}\n      {graph}\n{ch}"
            f"      capture.props = {{ {capture} }}\n      playback.props = {{ {playback} }}\n    }}\n  }}")


def build_conf(s, hrir=None, rnnoise=None):
    """Texto do arquivo que o `pipewire -c` do servico carrega."""
    label = s.get("label") or "Headset"
    mods = []
    sink_target = f'target.object = {_q(s["sink"])}' if s.get("sink") else ""
    src_target = f'target.object = {_q(s["source"])}' if s.get("source") else ""

    eq_active = s.get("eq_on") and any(s["gains"])
    if eq_active:
        nodes, links, i, o = _eq_nodes(s["gains"])
        mods.append(_module(f"{label} · Equalizador", nodes, links, _q(i), _q(o),
                            f'node.name = "{EQ_SINK}" media.class = Audio/Sink',
                            f'node.name = "{EQ_SINK}_out" node.passive = true {sink_target}',
                            channels=["FL", "FR"]))
    if s.get("surround") and hrir:
        names = ["FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"]
        nodes = [f"{{ type = builtin label = copy name = c{n} }}" for n in names]
        conv = {}
        for idx, (spk, ear) in enumerate(HESUVI):
            conv[(spk, ear)] = idx
        pairs = [("FL", 1), ("SL", 2), ("RL", 3), ("FC", 4), ("FR", 5), ("SR", 6), ("RR", 7)]
        links = []
        for spk, mix_in in pairs:
            for ear in ("L", "R"):
                nm = f"v{spk}{ear}"
                nodes.append(f'{{ type = builtin label = convolver name = {nm} config = {{ filename = {_q(hrir)} channel = {conv[(spk, ear)]} }} }}')
                links.append(f'{{ output = "c{spk}:Out" input = "{nm}:In" }}')
                links.append(f'{{ output = "{nm}:Out" input = "mix{ear}:In {mix_in}" }}')
        for ear in ("L", "R"):  # LFE vai pelo centro
            nm = f"vLFE{ear}"
            nodes.append(f'{{ type = builtin label = convolver name = {nm} config = {{ filename = {_q(hrir)} channel = {conv[("FC", ear)]} }} }}')
            links.append(f'{{ output = "cLFE:Out" input = "{nm}:In" }}')
            links.append(f'{{ output = "{nm}:Out" input = "mix{ear}:In 8" }}')
        nodes += ["{ type = builtin label = mixer name = mixL }", "{ type = builtin label = mixer name = mixR }"]
        target = f'target.object = "{EQ_SINK}"' if eq_active else sink_target
        mods.append(_module(f"{label} · Surround 7.1", nodes, links,
                            " ".join(_q(f"c{n}:In") for n in names), '"mixL:Out" "mixR:Out"',
                            f'node.name = "{SURROUND_SINK}" media.class = Audio/Sink audio.channels = 8 '
                            'audio.position = [ FL FR FC LFE RL RR SL SR ]',
                            f'node.name = "{SURROUND_SINK}_out" node.passive = true audio.channels = 2 '
                            f'audio.position = [ FL FR ] {target}'))
    voice = VOICE.get(s.get("voice"), [])
    nr = bool(s.get("nr") and rnnoise)
    if nr or voice or s.get("mic_gain"):
        nodes = ['{ type = builtin name = hp label = bq_highpass control = { "Freq" = 80.0 "Q" = 0.7 } }']
        chain = ["hp"]
        if nr:
            vad = NR_LEVELS[max(0, min(2, int(s.get("nr_level", 1))))][2]
            nodes.append(f'{{ type = ladspa name = rnnoise plugin = {_q(rnnoise)} label = noise_suppressor_mono '
                         f'control = {{ "VAD Threshold (%)" = {vad} "VAD Grace Period (ms)" = 200 }} }}')
            chain.append("rnnoise")
        for i, (typ, f, q, g) in enumerate(voice):
            nodes.append(f'{{ type = builtin name = v{i} label = {typ} control = {{ "Freq" = {float(f)} "Q" = {q} "Gain" = {float(g)} }} }}')
            chain.append(f"v{i}")
        gain = 10 ** (float(s.get("mic_gain", 0)) / 20)
        nodes.append(f'{{ type = builtin name = gain label = mixer control = {{ "Gain 1" = {gain:.4f} }} }}')
        ports = {"rnnoise": ("Input", "Output"), "gain": ("In 1", "Out")}
        links = []
        for a, b in zip(chain, chain[1:] + ["gain"]):
            links.append(f'{{ output = "{a}:{ports.get(a, ("In", "Out"))[1]}" input = "{b}:{ports.get(b, ("In", "Out"))[0]}" }}')
        first = chain[0]
        mods.append(_module(f"{label} · " + ("sem ruído" if nr else "voz"), nodes, links,
                            _q(f"{first}:In"), '"gain:Out"',
                            f'node.name = "{MIC_SOURCE}_in" node.passive = true audio.rate = 48000 {src_target}',
                            f'node.name = "{MIC_SOURCE}" media.class = Audio/Source audio.rate = 48000',
                            channels=["MONO"]))
    if s.get("sidetone") and s.get("source") and s.get("sink"):
        mods.append("  { name = libpipewire-module-loopback\n    args = {\n"
                    f"      node.description = {_q(label + ' · retorno da voz')}\n"
                    f"      capture.props = {{ node.name = \"logimouse_sidetone_in\" {src_target} node.passive = true }}\n"
                    f"      playback.props = {{ node.name = \"logimouse_sidetone_out\" {sink_target} }}\n    }}\n  }}")
    if not mods:
        return None
    head = ("# Gerado pelo LogiMouse. Mude pelo painel: este arquivo e reescrito.\n"
            "context.properties = { log.level = 0 }\n"
            "context.spa-libs = {\n  audio.convert.* = audioconvert/libspa-audioconvert\n  support.* = support/libspa-support\n}\n"
            "context.modules = [\n  { name = libpipewire-module-rt args = { } flags = [ ifexists nofail ] }\n"
            "  { name = libpipewire-module-protocol-native }\n  { name = libpipewire-module-client-node }\n"
            "  { name = libpipewire-module-adapter }\n")
    return head + "\n".join(mods) + "\n]\n"


# --------------------------------------------------------------------------
# Servico
# --------------------------------------------------------------------------
def conf_path():
    return os.path.join(config.config_dir(), "audio.conf")


def hrir_path():
    return os.path.join(config.config_dir(), "hrir-logimouse.wav")


def unit_path():
    return os.path.join(config._xdg("XDG_CONFIG_HOME", "~/.config"), "systemd", "user", SERVICE)


def _systemctl(*args):
    return _run(["systemctl", "--user", *args], timeout=15)


def apply(s=None, wait=True):
    """Grava a configuracao e (re)inicia o servico. Devolve uma lista de avisos."""
    s = s or settings()
    notes = []
    if config.DRY_RUN:
        return ["modo demonstração: nada foi mudado no som"]
    if not pipewire_ok():
        return ["PipeWire não encontrado: equalizador e microfone sem ruído precisam dele"]
    sink, src = find_headset()
    changed = {}
    if sink and sink["name"] != s.get("sink"):
        changed["sink"] = sink["name"]
    if src and src["name"] != s.get("source"):
        changed["source"] = src["name"]
    if sink and not s.get("label"):
        changed["label"] = sink["desc"] or "Headset"
    if changed:
        s = save_settings(**changed)
    hrir = None
    if s.get("surround"):
        hrir = s.get("hrir_file") or ""
        if not hrir or not os.path.exists(hrir):
            hrir = make_hrir(hrir_path(), s.get("room", 40))
    rn = rnnoise_plugin()
    if s.get("nr") and not rn:
        notes.append("redução de ruído: falta o plugin RNNoise (rode o instalar.sh)")
    text = build_conf(s, hrir=hrir, rnnoise=rn)
    if text is None:
        _systemctl("disable", "--now", SERVICE)
        return notes
    os.makedirs(config.config_dir(), exist_ok=True)
    with open(conf_path(), "w", encoding="utf-8") as fh:
        fh.write(text)
    pw = shutil.which("pipewire") or "/usr/bin/pipewire"
    unit = ("[Unit]\nDescription=LogiMouse: equalizador, surround e microfone sem ruído do headset\n"
            "After=pipewire.service wireplumber.service\nBindsTo=pipewire.service\n\n"
            f"[Service]\nExecStart={pw} -c {conf_path()}\nRestart=on-failure\nRestartSec=2\n\n"
            "[Install]\nWantedBy=pipewire.service\n")
    os.makedirs(os.path.dirname(unit_path()), exist_ok=True)
    old = None
    try:
        with open(unit_path(), encoding="utf-8") as fh:
            old = fh.read()
    except OSError:
        pass
    if old != unit:
        with open(unit_path(), "w", encoding="utf-8") as fh:
            fh.write(unit)
        _systemctl("daemon-reload")
    _systemctl("enable", SERVICE)
    r = _systemctl("restart", SERVICE)
    if r is None or r.returncode != 0:
        notes.append("não deu para iniciar o serviço de áudio (systemctl --user)")
        return notes
    if wait:
        _set_defaults(s)
    return notes


def _wait_node(name, timeout=4.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for n in pw_nodes():
            if n["name"] == name:
                return n
        time.sleep(0.25)
    return None


def _set_defaults(s):
    if s.get("default_out"):
        name = SURROUND_SINK if s.get("surround") else EQ_SINK if (s.get("eq_on") and any(s["gains"])) else s.get("sink")
        n = _wait_node(name) if name else None
        if n:
            _run(["wpctl", "set-default", str(n["id"])])
    if s.get("default_in"):
        n = _wait_node(MIC_SOURCE, 2.0)
        if n is None and s.get("source"):
            n = _wait_node(s["source"], 1.0)
        if n:
            _run(["wpctl", "set-default", str(n["id"])])


def service_running():
    r = _systemctl("is-active", SERVICE)
    return bool(r and r.stdout.strip() == "active")


# --------------------------------------------------------------------------
# Volume e teste do microfone
# --------------------------------------------------------------------------
def get_volume(node_id):
    r = _run(["wpctl", "get-volume", str(node_id)])
    if not r or r.returncode != 0:
        return None
    try:
        return round(float(r.stdout.split()[1]) * 100)
    except (IndexError, ValueError):
        return None


def set_volume(node_id, pct):
    if config.DRY_RUN:
        return True
    r = _run(["wpctl", "set-volume", str(node_id), f"{max(0, min(150, int(pct)))}%"])
    return bool(r and r.returncode == 0)


def test_dir():
    return os.path.join(config.runtime_dir(), "logimouse-mic-test")


def record_test(seconds=5, raw_source=None, clean_source=MIC_SOURCE):
    """Grava o mic original e o processado ao mesmo tempo. Devolve {"original": wav, "limpo": wav}."""
    os.makedirs(test_dir(), exist_ok=True)
    jobs = {}
    for key, target in (("original", raw_source), ("limpo", clean_source)):
        if not target:
            continue
        path = os.path.join(test_dir(), f"{key}.wav")
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        try:
            jobs[key] = (subprocess.Popen(["pw-record", "--target", str(target), "--rate", "48000",
                                           "--channels", "1", path],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), path)
        except OSError:
            pass
    time.sleep(seconds)
    out = {}
    for key, (p, path) in jobs.items():
        p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            out[key] = path
    return out


def play_file(path, target=None):
    cmd = ["pw-play", path]
    if target:
        cmd[1:1] = ["--target", str(target)]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def wav_levels(path, bars=40):
    """Picos por fatia, 0..1, para desenhar a forma de onda do teste."""
    try:
        with wave.open(path, "rb") as w:
            width, n = w.getsampwidth(), w.getnframes()
            data = w.readframes(n)
    except (OSError, wave.Error, EOFError):
        return []
    if width != 2 or not data:
        return []
    samples = struct.unpack(f"<{len(data) // 2}h", data[: len(data) // 2 * 2])
    step = max(1, len(samples) // bars)
    return [min(1.0, max(abs(x) for x in samples[i:i + step]) / 32768 * 1.6) for i in range(0, step * bars, step)
            if samples[i:i + step]]


def ladspa_found():
    return sorted({os.path.basename(p) for d in LADSPA_DIRS for p in glob.glob(os.path.join(os.path.expanduser(d), "*.so"))})

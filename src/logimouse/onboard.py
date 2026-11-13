"""
Memoria do mouse (HID++ 2.0, feature 0x8100 "onboard profiles"), usada nos mouses G.

O perfil fica num "setor" da memoria do mouse. No G305 (formato 3) ele tem 255 bytes:

    0       taxa (1 = 1 ms = 1000 Hz, 2 = 500 Hz, 4 = 250 Hz, 8 = 125 Hz)
    1       nivel de DPI padrao (0..4)
    2       nivel de DPI do "segurar para DPI baixo"
    3..12   5 niveis de DPI (uint16 little-endian; 0 = vazio)
    13..15  cor (sem uso no G305)
    16      modo de energia, 17 angle snapping, 18..19 contador de gravacoes
    32..    botoes, 4 bytes cada
    160..207 nome do perfil (UTF-16LE, 0xff = sem nome)
    fim-2   CRC-CCITT (0xffff, big-endian) dos bytes anteriores

O setor 0x0000 e o diretorio (quais perfis existem), 0x0001.. sao os perfis do
usuario e 0x0101.. as copias de fabrica (somente leitura). O formato e o mesmo
usado pelo Solaar e pelo libratbag.

Botao (4 bytes):
    8x 01 HH LL   botao do mouse (mascara: 1 esq, 2 dir, 4 meio, 8 voltar, 0x10 avancar)
    8x 02 MM KK   tecla (MM = modificadores HID, KK = tecla HID)
    8x 03 HH LL   tecla de midia (consumer)
    8x 00 00 00   sem acao
    9x FF 00 00   funcao (FF: 3 DPI+, 4 DPI-, 5 alternar DPI, 7 DPI baixo enquanto segura...)
"""

import json
import os
import time

from . import config
from . import hidpp as H

F = H.F_ONBOARD_PROFILES

MODE_ONBOARD = 0x01
MODE_HOST = 0x02

RATES = {1: 1000, 2: 500, 4: 250, 8: 125}

# Acoes que a interface oferece. "kind" + "value" sao guardados no config.json.
MOUSE_BUTTONS = {1: "Clique esquerdo", 2: "Clique direito", 4: "Clique do meio", 8: "Voltar", 0x10: "Avançar"}
FUNCTIONS = {3: "DPI +", 4: "DPI −", 5: "Alternar DPI", 6: "DPI padrão", 7: "Segurar para DPI baixo",
             12: "Mostrar bateria", 16: "Rolar para baixo", 17: "Rolar para cima"}
CONSUMER = {0xCD: "Mídia: tocar/pausar", 0xB5: "Mídia: próxima", 0xB6: "Mídia: anterior",
            0xE9: "Mídia: volume +", 0xEA: "Mídia: volume −", 0xE2: "Mídia: mudo"}

BUTTON_NAMES = ["Esquerdo", "Direito", "Roda (clique)", "Lateral de trás", "Lateral da frente", "Botão DPI",
                "Botão 7", "Botão 8", "Botão 9", "Botão 10", "Botão 11", "Botão 12"]


class OnboardError(Exception):
    pass


def crc16(data):
    c = 0xFFFF
    for x in data:
        c ^= x << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


# --------------------------------------------------------------------------
# Botoes
# --------------------------------------------------------------------------
def decode_button(b):
    """4 bytes -> {"kind": ..., ...}."""
    b = bytes(b)
    behavior = b[0] >> 4
    if b == b"\xff\xff\xff\xff":
        return {"kind": "none"}
    if behavior == 0x8:
        t = b[1]
        if t == 0x01:
            return {"kind": "mouse", "value": (b[2] << 8) | b[3]}
        if t == 0x02:
            return {"kind": "key", "mods": b[2], "value": b[3]}
        if t == 0x03:
            return {"kind": "consumer", "value": (b[2] << 8) | b[3]}
        if t == 0x00:
            return {"kind": "none"}
    if behavior == 0x9:
        return {"kind": "function", "value": b[1]}
    return {"kind": "raw", "value": b.hex()}


def encode_button(a):
    k = a.get("kind")
    v = int(a.get("value", 0) or 0) if k != "raw" else 0
    if k == "mouse":
        return bytes([0x80, 0x01, (v >> 8) & 0xFF, v & 0xFF])
    if k == "key":
        return bytes([0x80, 0x02, int(a.get("mods", 0)) & 0xFF, v & 0xFF])
    if k == "consumer":
        return bytes([0x80, 0x03, (v >> 8) & 0xFF, v & 0xFF])
    if k == "function":
        return bytes([0x90, v & 0xFF, 0x00, 0x00])
    if k == "none":
        return bytes([0x80, 0x00, 0x00, 0x00])
    if k == "raw":
        raw = bytes.fromhex(a.get("value", ""))
        if len(raw) == 4:
            return raw
    raise ValueError(f"ação de botão inválida: {a!r}")


def describe(a, macros=None):
    """Texto curto para a interface."""
    from . import macros as M
    k = a.get("kind")
    v = a.get("value")
    if k == "mouse":
        return MOUSE_BUTTONS.get(v, f"Botão do mouse {v:#x}")
    if k == "function":
        return FUNCTIONS.get(v, f"Função {v}")
    if k == "consumer":
        return CONSUMER.get(v, f"Mídia {v:#06x}")
    if k == "key":
        trig = M.trigger_index(v, a.get("mods", 0))
        if trig is not None:
            names = [m.get("name") for m in (macros or [])]
            return "Macro: " + (names[trig] if trig < len(names) and names[trig] else f"#{trig + 1}")
        return "Tecla: " + M.combo_text(a.get("mods", 0), v)
    if k == "none":
        return "Desativado"
    return "Outro (mantido)"


# --------------------------------------------------------------------------
# Perfil
# --------------------------------------------------------------------------
class Profile:
    def __init__(self, raw, buttons=6):
        self.raw = bytearray(raw)
        self.nbuttons = buttons

    @property
    def size(self):
        return len(self.raw)

    def crc_ok(self):
        stored = (self.raw[-2] << 8) | self.raw[-1]
        return stored == crc16(self.raw[:-2])

    # taxa
    @property
    def rate(self):
        return RATES.get(self.raw[0], 1000 // max(1, self.raw[0]))

    @rate.setter
    def rate(self, hz):
        inv = {v: k for k, v in RATES.items()}
        if hz not in inv:
            raise ValueError(f"taxa {hz} Hz não existe na memória do mouse")
        self.raw[0] = inv[hz]

    # DPI
    @property
    def dpis(self):
        return [int.from_bytes(self.raw[3 + i * 2:5 + i * 2], "little") for i in range(5)]

    @dpis.setter
    def dpis(self, values):
        vals = [int(v) for v in values if v][:5]
        if not vals:
            raise ValueError("pelo menos um nível de DPI")
        for i in range(5):
            v = vals[i] if i < len(vals) else 0
            self.raw[3 + i * 2:5 + i * 2] = int(v).to_bytes(2, "little")
        n = len(vals)
        if self.raw[1] >= n:
            self.raw[1] = 0
        if self.raw[2] >= n:
            self.raw[2] = 0

    @property
    def default_dpi(self):
        return self.raw[1]

    @default_dpi.setter
    def default_dpi(self, i):
        self.raw[1] = int(i)

    @property
    def shift_dpi(self):
        return self.raw[2]

    @shift_dpi.setter
    def shift_dpi(self, i):
        self.raw[2] = int(i)

    # botoes
    def button(self, i):
        return decode_button(self.raw[32 + i * 4:36 + i * 4])

    def set_button(self, i, action):
        if i == 0 and action.get("kind") in ("none",):
            raise ValueError("o botão esquerdo não pode ficar desativado")
        self.raw[32 + i * 4:36 + i * 4] = encode_button(action)

    @property
    def buttons(self):
        return [self.button(i) for i in range(self.nbuttons)]

    def seal(self):
        """Conta mais uma gravacao e recalcula o CRC."""
        wc = int.from_bytes(self.raw[18:20], "little")
        if wc != 0xFFFF:
            self.raw[18:20] = ((wc + 1) & 0xFFFF).to_bytes(2, "little")
        c = crc16(self.raw[:-2])
        self.raw[-2] = c >> 8
        self.raw[-1] = c & 0xFF
        return bytes(self.raw)

    def to_dict(self):
        return dict(rate=self.rate, dpis=[d for d in self.dpis if d], default_dpi=self.default_dpi,
                    shift_dpi=self.shift_dpi, buttons=self.buttons)

    def apply_dict(self, d):
        if d.get("dpis"):
            self.dpis = d["dpis"]
        n = len([x for x in self.dpis if x])
        if "default_dpi" in d:
            self.default_dpi = min(int(d["default_dpi"]), n - 1)
        if "shift_dpi" in d:
            self.shift_dpi = min(int(d["shift_dpi"]), n - 1)
        if d.get("rate"):
            self.rate = int(d["rate"])
        for i, a in enumerate(d.get("buttons") or []):
            if i < self.nbuttons and a:
                self.set_button(i, a)
        return self


# --------------------------------------------------------------------------
# Conversa com o mouse
# --------------------------------------------------------------------------
class Onboard:
    def __init__(self, dev):
        self.dev = dev
        r = dev.call(F, 0)
        self.memory_model, self.profile_format, self.macro_format = r[0], r[1], r[2]
        self.profile_count, self.profile_count_oob = r[3], r[4]
        self.nbuttons = r[5] or 6
        self.sector_count = r[6]
        self.sector_size = (r[7] << 8) | r[8]
        if not (32 + self.nbuttons * 4 < self.sector_size <= 4096):
            raise OnboardError("formato da memória do mouse desconhecido")

    # modo
    def mode(self):
        return self.dev.call(F, 2)[0]

    def set_mode(self, m):
        self.dev.call(F, 1, m)

    def current_sector(self):
        r = self.dev.call(F, 4)
        return (r[0] << 8) | r[1]

    def activate(self, sector):
        self.dev.call(F, 3, sector >> 8, sector & 0xFF)

    # setores
    def read_sector(self, sector, size=None):
        size = size or self.sector_size
        out = b""
        o = 0
        while o < size:
            off = max(0, min(o, size - 16))
            chunk = self.dev.call(F, 5, sector >> 8, sector & 0xFF, off >> 8, off & 0xFF)
            out += chunk[o - off:16]
            o = off + 16
        return out[:size]

    def write_sector(self, sector, data):
        data = bytes(data)
        if sector >= 0x0100:
            raise OnboardError("os setores de fábrica são só leitura")
        n = len(data)
        self.dev.call(F, 6, sector >> 8, sector & 0xFF, 0, 0, n >> 8, n & 0xFF)
        for o in range(0, n, 16):
            self.dev.call(F, 7, *data[o:o + 16])
        self.dev.call(F, 8)

    def directory(self):
        """[(setor, ligado)] dos perfis do usuario."""
        raw = self.read_sector(0, min(self.sector_size, 4 * max(1, self.profile_count) + 4))
        out = []
        for i in range(0, len(raw) - 3, 4):
            s = (raw[i] << 8) | raw[i + 1]
            if s == 0xFFFF:
                break
            out.append((s, raw[i + 2] == 1))
        return out

    def user_sector(self):
        d = self.directory()
        return d[0][0] if d else 0x0001

    def read_profile(self, sector=None):
        sector = self.user_sector() if sector is None else sector
        p = Profile(self.read_sector(sector), self.nbuttons)
        p.sector = sector
        return p

    def factory_profile(self):
        p = Profile(self.read_sector(0x0101), self.nbuttons)
        p.sector = 0x0101
        return p

    def write_profile(self, profile, backup=True):
        """Grava o perfil, confere lendo de volta e faz o mouse usa-lo. Devolve o perfil lido."""
        sector = getattr(profile, "sector", None) or self.user_sector()
        if sector >= 0x0100:
            sector = self.user_sector()
        current = self.read_sector(sector)
        if backup:
            save_backup(self.dev.name, sector, current)
        data = profile.seal()
        self.write_sector(sector, data)
        back = self.read_sector(sector)
        if back != data:
            raise OnboardError("o mouse não confirmou a gravação (tente de novo)")
        if self.mode() != MODE_ONBOARD:
            self.set_mode(MODE_ONBOARD)
        try:
            self.activate(sector)
        except H.DEVICE_ERRORS:
            pass
        p = Profile(back, self.nbuttons)
        p.sector = sector
        return p

    def restore_factory(self):
        f = self.factory_profile()
        f.sector = self.user_sector()
        f.raw[18:20] = self.read_sector(f.sector)[18:20]
        return self.write_profile(f)


def backups_dir():
    return os.path.join(config.config_dir(), "backups")


def save_backup(name, sector, data):
    if config.DRY_RUN:
        return None
    os.makedirs(backups_dir(), exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in (name or "mouse"))[:40]
    path = os.path.join(backups_dir(), f"{safe}-setor{sector:04x}-{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"device": name, "sector": sector, "data": bytes(data).hex()}, fh)
    return path


def supported(dev):
    try:
        return dev.has(F)
    except H.DEVICE_ERRORS:
        return False

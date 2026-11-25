"""
Protocolo HID++ 2.0 da Logitech sobre /dev/hidraw.

Funciona com receptor Unifying, Bolt, Lightspeed, Bluetooth e cabo USB.
Sem dependencias externas.
"""

import glob
import os
import re
import select
import threading
import time

LOGI_VID = 0x046D

# Features HID++ 2.0
F_ROOT = 0x0000
F_DEVICE_NAME = 0x0005
F_BATTERY_STATUS = 0x1000
F_BATTERY_VOLTAGE = 0x1001
F_UNIFIED_BATTERY = 0x1004
F_WIRELESS_STATUS = 0x1D4B
F_SMART_SHIFT = 0x2110
F_SMART_SHIFT_ENH = 0x2111
F_HIRES_WHEEL = 0x2121
F_ADJUSTABLE_DPI = 0x2201
F_EXT_DPI = 0x2202
F_POINTER_SPEED = 0x2205
F_REPORT_RATE = 0x8060
F_EXT_REPORT_RATE = 0x8061
F_ONBOARD_PROFILES = 0x8100
# fones Logitech (G935, G733, G535, PRO X...)
F_ADC_MEASUREMENT = 0x1F20   # bateria pela tensao
F_SIDETONE = 0x8300          # retorno da voz no fone (0..100)
F_EQUALIZER = 0x8310         # equalizador gravado no fone
F_LED_EFFECTS = 0x8070       # luzes por zona

ERRORS_20 = {
    1: "erro desconhecido", 2: "argumento inválido", 3: "fora de alcance",
    4: "erro de hardware", 5: "erro interno", 6: "índice de feature inválido",
    7: "função inválida", 8: "ocupado", 9: "não suportado",
}
ERRORS_10 = {
    1: "comando inválido", 2: "endereço inválido", 3: "valor inválido",
    4: "falha de conexão", 5: "muitos dispositivos", 6: "já existe",
    7: "ocupado", 8: "dispositivo desconhecido", 9: "dispositivo desligado/fora de alcance",
    10: "erro de requisição", 11: "parâmetro inválido", 12: "PIN errado",
}
KINDS = {
    0: "Teclado", 1: "Controle remoto", 2: "Teclado numérico", 3: "Mouse",
    4: "Touchpad", 5: "Trackball", 6: "Apresentador", 7: "Receptor", 8: "Headset",
}
HEADSET_KIND = 8
POINTING_KINDS = (3, 4, 5)


class HidppError(Exception):
    def __init__(self, code, hidpp10=False):
        self.code = code
        self.hidpp10 = hidpp10  # erro do receptor: em geral, dispositivo desligado
        table = ERRORS_10 if hidpp10 else ERRORS_20
        super().__init__(table.get(code, f"erro 0x{code:02X}"))


class HidppTimeout(Exception):
    pass


class NotSupported(Exception):
    pass


DEVICE_ERRORS = (HidppError, HidppTimeout, NotSupported, OSError)


# --------------------------------------------------------------------------
# Transporte
# --------------------------------------------------------------------------
class HidrawTransport:
    """Le e escreve relatorios HID crus num /dev/hidrawN."""

    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        self.lock = threading.RLock()

    def fileno(self):
        return self.fd

    def write(self, data):
        os.write(self.fd, bytes(data))

    def read(self, timeout):
        r, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not r:
            return None
        try:
            return os.read(self.fd, 64)
        except BlockingIOError:
            return None

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Dispositivo
# --------------------------------------------------------------------------
class Device:
    # Identificador do programa nas mensagens (1..15). A bandeja usa outro
    # valor para nao confundir respostas com as do painel.
    sw_id = 0x0B

    def __init__(self, transport, index, bus=None):
        self.t = transport
        self.index = index
        self.bus = bus
        self._features = {F_ROOT: 0}
        self.protocol = None
        self.name = None
        self.kind = None

    def __repr__(self):
        return f"<Device {self.name!r} idx={self.index}>"

    # ---- baixo nivel ----
    def _drain(self):
        while self.t.read(0) is not None:
            pass

    def request(self, feat_idx, function, *params, timeout=1.5):
        """Envia (feature, funcao, parametros) e devolve os 16 bytes da resposta."""
        funcsw = ((function & 0x0F) << 4) | (self.sw_id & 0x0F)
        msg = bytes([0x11, self.index, feat_idx, funcsw]) + bytes(params)
        msg = msg[:20].ljust(20, b"\x00")
        with self.t.lock:
            self._drain()
            self.t.write(msg)
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise HidppTimeout("sem resposta do dispositivo")
                r = self.t.read(left)
                if not r or len(r) < 7 or r[0] not in (0x10, 0x11):
                    continue
                if r[1] not in (self.index, self.index ^ 0xFF):
                    continue
                if r[0] == 0x11 and r[2] == 0xFF and r[3] == feat_idx and r[4] == funcsw:
                    raise HidppError(r[5])
                if r[0] == 0x10 and r[2] == 0x8F and r[3] == feat_idx and r[4] == funcsw:
                    raise HidppError(r[5], hidpp10=True)
                if r[2] == feat_idx and r[3] == funcsw:
                    return bytes(r[4:]).ljust(16, b"\x00")

    def ping(self, timeout=1.0):
        mark = 0x5A
        r = self.request(0, 1, 0, 0, mark, timeout=timeout)
        if r[2] != mark:
            raise HidppTimeout("ping sem eco")
        self.protocol = (r[0], r[1])
        return self.protocol

    def feature(self, fid):
        if fid not in self._features:
            try:
                r = self.request(0, 0, fid >> 8, fid & 0xFF)
                self._features[fid] = r[0] or None
            except HidppError as e:
                if e.hidpp10:
                    raise  # dispositivo inacessivel: nao guardar como "sem suporte"
                self._features[fid] = None
        return self._features[fid]

    def cached_feature(self, fid):
        """Indice da feature se ja foi consultada (sem falar com o mouse)."""
        return self._features.get(fid)

    def has(self, fid):
        return self.feature(fid) is not None

    def call(self, fid, function, *params):
        idx = self.feature(fid)
        if idx is None:
            raise NotSupported(f"feature 0x{fid:04X} não suportada")
        return self.request(idx, function, *params)

    # ---- identidade ----
    def read_identity(self):
        name = ""
        if self.has(F_DEVICE_NAME):
            count = self.call(F_DEVICE_NAME, 0)[0]
            while len(name) < count:
                chunk = self.call(F_DEVICE_NAME, 1, len(name))
                part = chunk[: count - len(name)].split(b"\x00")[0]
                if not part:
                    break
                name += part.decode("utf-8", "replace")
            try:
                self.kind = self.call(F_DEVICE_NAME, 2)[0]
            except (HidppError, HidppTimeout):
                self.kind = None
        self.name = name.strip() or f"Dispositivo Logitech #{self.index}"
        return self.name

    @property
    def kind_name(self):
        return KINDS.get(self.kind, "Dispositivo")

    @property
    def is_pointer(self):
        return self.kind in POINTING_KINDS

    @property
    def connection(self):
        if self.bus == 0x05:
            return "Bluetooth"
        if self.index == 0xFF:
            return "USB"
        return "Receptor"

    # ---- bateria ----
    def battery(self):
        """Devolve dict: percent, level, status, charging, voltage, source."""
        if self.has(F_UNIFIED_BATTERY):
            return parse_unified_battery(self.call(F_UNIFIED_BATTERY, 1))
        if self.has(F_BATTERY_STATUS):
            return parse_battery_status(self.call(F_BATTERY_STATUS, 0))
        if self.has(F_BATTERY_VOLTAGE):
            r = self.call(F_BATTERY_VOLTAGE, 0)
            mv = (r[0] << 8) | r[1]
            flags = r[2]
            charging = bool(flags & 0x80)
            st = "Carregando" if charging else "Descarregando"
            if charging and (flags & 0x03) == 0x02:
                st = "Carga completa"
            return dict(percent=volt_to_percent(mv), level=None, status=st,
                        charging=charging, voltage=mv, source="HID++ 0x1001 (estimado pela tensão)")
        if self.has(F_ADC_MEASUREMENT):
            r = self.call(F_ADC_MEASUREMENT, 0)
            mv = (r[0] << 8) | r[1]
            flags = r[2]
            if not mv:
                raise NotSupported("bateria não informada agora (fone desligado?)")
            charging = bool(flags & 0x02)  # visto num G935 real: 0x01 na bateria, 0x03 carregando
            st = "Carregando" if charging else "Ligado"
            if flags & 0x04:
                st = "Carga completa"
            pct, src = charge_estimate(mv, charging)
            if flags & 0x04:
                pct = 100
            return dict(percent=pct, level=None, status=st, charging=charging, voltage=mv,
                        approx=charging and not flags & 0x04, source=src)
        raise NotSupported("bateria não informada pelo dispositivo")

    def battery_from_event(self, feat_idx, payload):
        """Interpreta um aviso de bateria que o mouse manda sozinho."""
        if feat_idx and feat_idx == self.cached_feature(F_UNIFIED_BATTERY):
            return parse_unified_battery(payload)
        if feat_idx and feat_idx == self.cached_feature(F_BATTERY_STATUS):
            return parse_battery_status(payload)
        return None

    # ---- DPI ----
    def _dpi_list(self, fid, function, skip, direction):
        raw = b""
        for i in range(16):
            r = self.call(fid, function, 0, direction, i)
            raw += r[skip:]
            if raw[-2:] == b"\x00\x00":
                break
        return parse_dpi_list(raw)

    def dpi(self):
        """Devolve (lista_de_valores, atual, padrao)."""
        if self.has(F_EXT_DPI):
            choices = self._dpi_list(F_EXT_DPI, 2, 3, 0)
            r = self.call(F_EXT_DPI, 5, 0)
        elif self.has(F_ADJUSTABLE_DPI):
            choices = self._dpi_list(F_ADJUSTABLE_DPI, 1, 1, 0)
            r = self.call(F_ADJUSTABLE_DPI, 2, 0)
        else:
            raise NotSupported("DPI ajustável não suportado")
        cur = (r[1] << 8) | r[2]
        dflt = (r[3] << 8) | r[4]
        return choices, cur or dflt, dflt

    def set_dpi(self, value):
        value = int(value)
        if self.has(F_EXT_DPI):
            caps = self.call(F_EXT_DPI, 1, 0)
            has_y = bool(caps[2] & 0x01)
            has_lod = bool(caps[2] & 0x02)
            cur = self.call(F_EXT_DPI, 5, 0)
            y = value if has_y else 0
            lod = cur[9] if has_lod else 0
            self.call(F_EXT_DPI, 6, 0, value >> 8, value & 0xFF, y >> 8, y & 0xFF, lod)
        else:
            self.call(F_ADJUSTABLE_DPI, 3, 0, value >> 8, value & 0xFF)
        return self.dpi()[1]

    # ---- velocidade do ponteiro ----
    def pointer_speed(self):
        r = self.call(F_POINTER_SPEED, 0)
        return (r[0] << 8) | r[1]

    def set_pointer_speed(self, v):
        v = max(0x2E, min(0x1FF, int(v)))
        self.call(F_POINTER_SPEED, 1, v >> 8, v & 0xFF)
        return self.pointer_speed()

    # ---- taxa de atualizacao ----
    EXT_RATES = {0: 125, 1: 250, 2: 500, 3: 1000, 4: 2000, 5: 4000, 6: 8000}

    def report_rate(self):
        """Devolve (lista_hz, atual_hz)."""
        if self.has(F_EXT_REPORT_RATE):
            r = self.call(F_EXT_REPORT_RATE, 1)
            flags = (r[0] << 8) | r[1]
            choices = [self.EXT_RATES[i] for i in range(7) if flags & (1 << i)]
            cur = self.EXT_RATES.get(self.call(F_EXT_REPORT_RATE, 2)[0])
            return choices, cur
        if self.has(F_REPORT_RATE):
            flags = self.call(F_REPORT_RATE, 0)[0]
            choices = [round(1000 / (i + 1)) for i in range(8) if flags & (1 << i)]
            ms = self.call(F_REPORT_RATE, 1)[0]
            return choices, round(1000 / ms) if ms else None
        raise NotSupported("taxa de atualização fixa")

    def set_report_rate(self, hz):
        hz = int(hz)
        if self.has(F_EXT_REPORT_RATE):
            idx = {v: k for k, v in self.EXT_RATES.items()}[hz]
            self.call(F_EXT_REPORT_RATE, 3, idx)
        else:
            ms = max(1, min(8, round(1000 / hz)))
            self.call(F_REPORT_RATE, 2, ms)
        return self.report_rate()[1]

    # ---- roda ----
    def _ss(self):
        if self.has(F_SMART_SHIFT_ENH):
            return F_SMART_SHIFT_ENH, 1, 2
        if self.has(F_SMART_SHIFT):
            return F_SMART_SHIFT, 0, 1
        raise NotSupported("sem SmartShift")

    def smartshift(self):
        """Devolve (modo, limiar): modo 1 = livre, 2 = catraca; limiar 1..50 ou None (sem auto)."""
        fid, rd, _ = self._ss()
        r = self.call(fid, rd)
        mode, thr = r[0], r[1]
        return mode, (thr if 0 < thr < 255 else None)

    def set_smartshift(self, mode, threshold):
        """mode 1 = livre, 2 = catraca. threshold None = sem troca automatica."""
        fid, _, wr = self._ss()
        if int(mode) == 1:
            self.call(fid, wr, 1, 0)
        else:
            thr = 255 if threshold is None else max(1, min(50, int(threshold)))
            self.call(fid, wr, 2, thr)
        return self.smartshift()

    def hires_wheel(self):
        """Devolve dict hires, invert, can_invert, raw."""
        caps = self.call(F_HIRES_WHEEL, 0)
        mode = self.call(F_HIRES_WHEEL, 1)[0]
        return dict(hires=bool(mode & 0x02), invert=bool(mode & 0x04),
                    can_invert=bool(caps[1] & 0x08), raw=mode)

    def set_hires_wheel(self, hires=None, invert=None):
        mode = self.call(F_HIRES_WHEEL, 1)[0]
        if hires is not None:
            mode = (mode | 0x02) if hires else (mode & ~0x02)
        if invert is not None:
            mode = (mode | 0x04) if invert else (mode & ~0x04)
        self.call(F_HIRES_WHEEL, 2, mode & 0xFF)
        return self.hires_wheel()

    # ---- fones ----
    @property
    def is_audio(self):
        """Fone/headset Logitech (HID++ tipo 8)."""
        return self.kind == HEADSET_KIND

    @property
    def ui(self):
        return "logi_headset" if self.is_audio else "mouse" if self.is_pointer else "generic"

    def sidetone(self):
        """Retorno da voz no fone, 0..100."""
        return self.call(F_SIDETONE, 0)[0]

    def set_sidetone(self, level):
        self.call(F_SIDETONE, 1, max(0, min(100, int(level))))
        return self.sidetone()

    def eq_info(self):
        """dict(bands, range_db, freqs) do equalizador gravado no fone."""
        r = self.call(F_EQUALIZER, 0)
        n, rng = r[0], r[1]
        freqs = []
        while len(freqs) < n:
            chunk = self.call(F_EQUALIZER, 1, len(freqs))
            got = [int.from_bytes(chunk[1 + i * 2:3 + i * 2], "big") for i in range(min(7, n - len(freqs)))]
            if not any(got):
                break
            freqs += got
        return dict(bands=n, range_db=rng, freqs=freqs[:n])

    def eq_gains(self, n=None):
        n = n or self.eq_info()["bands"]
        r = self.call(F_EQUALIZER, 2, 1)
        return [b - 256 if b > 127 else b for b in r[:n]]

    def set_eq_gains(self, gains):
        """Grava as faixas (dB) no fone. Vale em qualquer computador."""
        info = self.eq_info()
        if len(gains) != info["bands"]:
            raise ValueError(f"o fone tem {info['bands']} faixas")
        rng = info["range_db"] or 12
        vals = [max(-rng, min(rng, int(round(g)))) & 0xFF for g in gains]
        self.call(F_EQUALIZER, 3, 1, *vals)
        return self.eq_gains(info["bands"])

    # luzes (0x8070): efeitos por zona
    LED_EFFECTS = {0x0000: "Desligada", 0x0001: "Cor fixa", 0x0003: "Ciclo de cores", 0x000A: "Respirar"}
    LED_ZONES = {0x0001: "Principal", 0x0002: "Logo", 0x0003: "Lado esquerdo", 0x0004: "Lado direito",
                 0x0005: "Todas", 0x0006: "Faixa", 0x0007: "Teclas"}

    def led_zones(self):
        """[dict(zone, name, effects=[(indice, id, nome)])]."""
        out = []
        for z in range(self.call(F_LED_EFFECTS, 0)[0]):
            zi = self.call(F_LED_EFFECTS, 1, z)
            loc = (zi[1] << 8) | zi[2]
            effects = []
            for e in range(min(zi[3], 16)):
                ei = self.call(F_LED_EFFECTS, 2, z, e)
                eid = (ei[2] << 8) | ei[3]
                if eid in self.LED_EFFECTS:
                    effects.append((e, eid, self.LED_EFFECTS[eid]))
            out.append(dict(zone=z, name=self.LED_ZONES.get(loc, f"Zona {z + 1}"), effects=effects))
        return out

    def leds_off(self):
        """Apaga todas as zonas que tem o efeito "desligada". Devolve quantas apagou."""
        n = 0
        for z in self.led_zones():
            if any(eid == 0x0000 for _, eid, _ in z["effects"]):
                self.set_led(z["zone"], 0x0000)
                n += 1
        if not n:
            raise NotSupported("sem luzes para apagar")
        return n

    def set_led(self, zone, effect_id, color=(0xA8, 0x55, 0xF7), period=4000):
        """Aplica um efeito numa zona: 0 desligada, 1 cor fixa, 0x0A respirar, 3 ciclo."""
        z = next((x for x in self.led_zones() if x["zone"] == zone), None)
        if z is None:
            raise ValueError("zona de luz inexistente")
        idx = next((e for e, eid, _ in z["effects"] if eid == effect_id), None)
        if idx is None:
            raise NotSupported("efeito não suportado nesta zona")
        r, g, b = (int(c) & 0xFF for c in color)
        per = max(1000, min(20000, int(period)))
        params = [0] * 10
        if effect_id == 0x0001:
            params[:4] = [r, g, b, 0]
        elif effect_id == 0x000A:
            params[:7] = [r, g, b, per >> 8, per & 0xFF, 0, 0]
        elif effect_id == 0x0003:
            params[5:8] = [per >> 8, per & 0xFF, 0]
        self.call(F_LED_EFFECTS, 3, zone, idx, *params, 0x01)

    # ---- perfis da memoria (mouses gamer) ----
    def host_mode(self):
        """True = configuracoes controladas pelo computador; False = perfis da memoria."""
        return self.call(F_ONBOARD_PROFILES, 2)[0] == 0x02

    def set_host_mode(self, on):
        self.call(F_ONBOARD_PROFILES, 1, 0x02 if on else 0x01)
        return self.host_mode()


# --------------------------------------------------------------------------
# Interpretacao de respostas
# --------------------------------------------------------------------------
def parse_unified_battery(r):
    soc, level, chg = r[0], r[1], r[2]
    lv = {8: "Cheia", 4: "Boa", 2: "Baixa", 1: "Crítica"}.get(level)
    st = {0: "Descarregando", 1: "Carregando", 2: "Carregando (lento)",
          3: "Carga completa", 4: "Erro na carga"}.get(chg, "")
    return dict(percent=soc or None, level=lv, status=st,
                charging=chg in (1, 2), voltage=None, source="HID++ 0x1004")


def parse_battery_status(r):
    st = {0: "Descarregando", 1: "Carregando", 2: "Quase cheia",
          3: "Carga completa", 4: "Carregando (lento)", 5: "Bateria inválida",
          6: "Erro de temperatura"}.get(r[2], "")
    return dict(percent=r[0] or None, level=None, status=st,
                charging=r[2] in (1, 2, 4), voltage=None, source="HID++ 0x1000")


def parse_dpi_list(raw):
    """Lista de DPI: valores de 16 bits; 0b111xxxxx... = passo ate o proximo valor."""
    out, i = [], 0
    while i + 1 < len(raw):
        v = (raw[i] << 8) | raw[i + 1]
        if v == 0:
            break
        if v >> 13 == 0b111:
            step = v & 0x1FFF
            if i + 3 >= len(raw):
                break
            last = (raw[i + 2] << 8) | raw[i + 3]
            if out and step:
                out += range(out[-1] + step, last + 1, step)
            i += 4
        else:
            out.append(v)
            i += 2
    return sorted(set(out))


def volt_to_percent(mv):
    table = [(4186, 100), (4067, 90), (3989, 80), (3922, 70), (3859, 60), (3811, 50),
             (3778, 40), (3751, 30), (3717, 20), (3671, 10), (3646, 5), (3579, 2), (3500, 0)]
    if mv >= table[0][0]:
        return 100
    if mv <= table[-1][0]:
        return 0
    for (vh, ph), (vl, pl) in zip(table, table[1:]):
        if vl <= mv <= vh:
            return round(pl + (ph - pl) * (mv - vl) / (vh - vl))
    return None


def battery_value(b):
    """Numero 0-100 para barras e icones, mesmo quando so ha nivel aproximado."""
    if not b:
        return None
    if b.get("percent") is not None:
        return b["percent"]
    return {"Cheia": 100, "Boa": 60, "Baixa": 20, "Crítica": 5}.get(b.get("level"))


# Carregando, o carregador empurra a tensao para cima e a conta pela tensao exagera a carga
# (G935 real: 4,09 V = "92%" com a carga de verdade por volta de 75-85%). Desconta-se essa
# sobra e a estimativa nunca chega a 100% enquanto carrega: o "cheio" vem do proprio fone.
CHARGING_OFFSET_MV = 120


def charge_estimate(mv, charging):
    """(porcentagem, texto da fonte) a partir da tensao da bateria."""
    if not charging:
        return volt_to_percent(mv), "HID++ 0x1F20 (estimado pela tensão)"
    pct = volt_to_percent(mv - CHARGING_OFFSET_MV)
    return (min(pct, 99) if pct is not None else None,
            "HID++ 0x1F20 (estimado pela tensão, descontando o carregador)")


def battery_text(b):
    if not b:
        return "?"
    if b.get("percent") is not None:
        return f"{'~' if b.get('approx') else ''}{b['percent']}%"
    return b.get("level") or "?"


def sysfs_battery(name=None):
    """Plano B: bateria exposta pelo driver do kernel (hid-logitech-hidpp)."""
    found = []
    for d in glob.glob("/sys/class/power_supply/hidpp_battery_*"):
        def rd(f, d=d):
            try:
                with open(os.path.join(d, f)) as fh:
                    return fh.read().strip()
            except OSError:
                return None
        found.append(dict(model=rd("model_name"), capacity=rd("capacity"),
                          level=rd("capacity_level"), status=rd("status")))
    if not found:
        return None
    pick = next((b for b in found if name and b["model"] and b["model"].lower() in name.lower()), None)
    if pick is None and len(found) == 1:
        pick = found[0]
    if pick is None:
        return None
    lv = {"Full": "Cheia", "High": "Boa", "Normal": "Boa", "Low": "Baixa",
          "Critical": "Crítica"}.get(pick["level"] or "")
    st = {"Discharging": "Descarregando", "Charging": "Carregando",
          "Full": "Carga completa"}.get(pick["status"] or "", pick["status"] or "")
    pct = int(pick["capacity"]) if pick["capacity"] and pick["capacity"].isdigit() else None
    return dict(percent=pct, level=lv, status=st, charging=st == "Carregando",
                voltage=None, source="driver do kernel")


def read_battery(dev):
    try:
        return dev.battery()
    except (NotSupported, HidppError, HidppTimeout):
        return sysfs_battery(dev.name)


# --------------------------------------------------------------------------
# Descoberta
# --------------------------------------------------------------------------
_HID_DIR = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}$")


def hidpp_nodes():
    """Lista os /dev/hidrawN da Logitech que falam HID++."""
    nodes = []
    paths = glob.glob("/sys/class/hidraw/hidraw*")
    paths.sort(key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0))
    for sp in paths:
        dev = os.path.realpath(os.path.join(sp, "device"))
        try:
            with open(os.path.join(dev, "uevent")) as fh:
                props = dict(line.split("=", 1) for line in fh.read().splitlines() if "=" in line)
            with open(os.path.join(dev, "report_descriptor"), "rb") as fh:
                desc = fh.read()
        except OSError:
            continue
        parts = props.get("HID_ID", "").split(":")
        if len(parts) != 3:
            continue
        bus, vid, pid = (int(p, 16) for p in parts)
        if vid != LOGI_VID:
            continue
        if b"\x85\x11" not in desc or not re.search(rb"\x06.\xff", desc, re.S):
            continue
        # filhos virtuais criados pelo driver do receptor: ja falamos pelo receptor
        if _HID_DIR.match(os.path.basename(os.path.dirname(dev))):
            continue
        nodes.append(dict(path="/dev/" + os.path.basename(sp), bus=bus, pid=pid,
                          name=props.get("HID_NAME", "")))
    return nodes


def probe_transport(t, bus):
    """Procura dispositivos HID++ 2.0 atras de um transporte aberto."""
    found = []
    d = Device(t, 0xFF, bus)  # o proprio dispositivo (USB direto / Bluetooth)
    try:
        if d.ping(timeout=0.6)[0] >= 2:
            found.append(d)
    except DEVICE_ERRORS:
        pass
    if not found and bus != 0x05:
        for idx in range(1, 7):  # receptor: ate 6 pareados
            d = Device(t, idx, bus)
            try:
                if d.ping(timeout=0.6)[0] >= 2:
                    found.append(d)
            except DEVICE_ERRORS:
                pass
    for d in found:
        try:
            d.read_identity()
        except DEVICE_ERRORS:
            d.name = d.name or f"Dispositivo Logitech #{d.index}"
    return found


def discover(nodes=None):
    """Devolve (lista_de_Device, lista_de_problemas)."""
    devices, problems = [], []
    nodes = hidpp_nodes() if nodes is None else nodes
    if not nodes:
        problems.append("Nenhum receptor ou mouse Logitech com HID++ encontrado.")
    for n in nodes:
        try:
            t = HidrawTransport(n["path"])
        except PermissionError:
            problems.append(f"Sem permissão para abrir {n['path']} ({n['name']}). "
                            "Rode o instalar.sh (regra udev) e reconecte o receptor/mouse.")
            continue
        except OSError as e:
            problems.append(f"{n['path']}: {e}")
            continue
        t.bus = n["bus"]
        found = probe_transport(t, n["bus"])
        devices += found
        if not found:
            t.close()
    if nodes and not devices and not problems:
        problems.append("Receptor encontrado, mas nenhum dispositivo respondeu. "
                        "Mexa o mouse para acordá-lo e clique em Atualizar.")
    devices.sort(key=lambda d: (not d.is_pointer, d.name or ""))
    return devices, problems


# --------------------------------------------------------------------------
# Leitura geral e reaplicacao de ajustes
# --------------------------------------------------------------------------
def read_all(dev):
    """Le tudo que o dispositivo suporta. Cada item: valor ou None."""
    s = {}

    def safe(key, fn):
        try:
            s[key] = fn()
        except (NotSupported, HidppError, HidppTimeout):
            s[key] = None
        except OSError as e:
            s[key] = None
            s.setdefault("errors", []).append(str(e))

    s["battery"] = read_battery(dev)
    if dev.is_audio:
        safe("sidetone", dev.sidetone)
        safe("eq_info", dev.eq_info)
        if s.get("eq_info"):
            safe("eq", lambda: dev.eq_gains(s["eq_info"]["bands"]))
        safe("leds", dev.led_zones)
        for k in ("dpi", "pointer_speed", "report_rate", "smartshift", "hires", "host_mode"):
            s[k] = None
        return s
    safe("dpi", dev.dpi)
    safe("pointer_speed", dev.pointer_speed)
    safe("report_rate", dev.report_rate)
    safe("smartshift", dev.smartshift)
    safe("hires", dev.hires_wheel)
    safe("host_mode", dev.host_mode)
    safe("leds", dev.led_zones)
    return s


def apply_settings(dev, saved):
    """Reaplica ajustes salvos. Devolve (aplicados, falhas) com nomes legiveis."""
    done, failed = [], []
    steps = [
        # modo host primeiro: ele decide se o DPI do computador vale
        ("host_mode", "modo host", lambda v: dev.set_host_mode(bool(v))),
        ("dpi", "DPI", lambda v: dev.set_dpi(int(v))),
        ("pointer_speed", "velocidade", lambda v: dev.set_pointer_speed(int(v))),
        ("report_rate", "taxa", lambda v: dev.set_report_rate(int(v))),
        ("smartshift", "roda", lambda v: dev.set_smartshift(v[0], v[1])),
        ("hires", "alta resolução", lambda v: dev.set_hires_wheel(hires=bool(v))),
        ("invert", "inverter rolagem", lambda v: dev.set_hires_wheel(invert=bool(v))),
        ("sidetone", "retorno da voz", lambda v: dev.set_sidetone(int(v))),
        ("leds", "luzes", lambda v: dev.leds_off() if v == "off" else [
            dev.set_led(int(z), int(x["effect"]), x.get("color", (0, 0, 0)), x.get("period", 4000))
            for z, x in v.items()]),
    ]
    for key, label, fn in steps:
        if key not in saved or saved[key] is None:
            continue
        try:
            fn(saved[key])
            done.append(label)
        except (NotSupported, HidppError, HidppTimeout, OSError, ValueError, KeyError, TypeError, IndexError):
            failed.append(label)
    return done, failed

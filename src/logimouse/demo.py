"""Mouse simulado para testar o app sem hardware (--demo e testes automaticos)."""

import os
import select
import threading

from . import hidpp as H


# Memoria de um G305 de verdade (perfil de fabrica): 400/800/1600/3200 DPI, 1000 Hz, 6 botoes.
G305_DIRECTORY = bytes.fromhex("00010100ffff0000")
G305_PROFILE = bytes.fromhex(
    "010100900120034006800c0000ffffffff00ffffffffffffffffffffffffffff"
    "800100018001000280010004800100088001001090050000ffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff0000000000001f400000000000000000"
    "001f40000000ffffffffffffffffffffffffffffffffffffffffffffff7a22"
)


class FakeMouse:
    """Transporte falso que responde como um mouse HID++ 2.0 atras de um receptor."""

    FEATURES = [H.F_ROOT, 0x0001, H.F_DEVICE_NAME, H.F_UNIFIED_BATTERY, H.F_WIRELESS_STATUS,
                H.F_SMART_SHIFT, H.F_HIRES_WHEEL, H.F_ADJUSTABLE_DPI, H.F_REPORT_RATE,
                H.F_ONBOARD_PROFILES]
    DEFAULTS = dict(dpi=1000, ss=[2, 12], wheel=0x02, rate_ms=8, onboard=0x01)

    def __init__(self, name="MX Master 3S (demo)", index=1):
        self.lock = threading.RLock()
        self.name = name.encode()
        self.index = index
        self.bus = 0x03
        self.path = "demo"
        self.out = []
        self._r, self._w = os.pipe()
        self.online = True
        self.ignore_dpi = False  # simula mouse G em modo de perfis da memoria
        self.soc = 73
        self.charging = 0
        self.sectors = {0x0000: G305_DIRECTORY.ljust(255, b"\xff"), 0x0001: G305_PROFILE, 0x0101: G305_PROFILE}
        self._write = None
        self.current_sector = 0x0001
        self.reset()

    # ---- simulacao ----
    def reset(self):
        """Volta aos padroes de fabrica, como um mouse que foi desligado."""
        self.dpi = self.DEFAULTS["dpi"]
        self.ss = list(self.DEFAULTS["ss"])
        self.wheel = self.DEFAULTS["wheel"]
        self.rate_ms = self.DEFAULTS["rate_ms"]
        self.onboard = self.DEFAULTS["onboard"]

    def power_off(self):
        self.online = False
        self.reset()
        self._push(bytes([0x10, self.index, 0x41, 0x04, 0x40 | 0x01, 0x23, 0x40]))

    def power_on(self):
        self.online = True
        self._push(bytes([0x10, self.index, 0x41, 0x04, 0x01, 0x23, 0x40]))
        fi = self.FEATURES.index(H.F_WIRELESS_STATUS)
        self._push(bytes([0x11, self.index, fi, 0x00, 0x01, 0x01, 0x01]) + bytes(13))

    def battery_event(self, soc, charging=0):
        self.soc, self.charging = soc, charging
        fi = self.FEATURES.index(H.F_UNIFIED_BATTERY)
        self._push(bytes([0x11, self.index, fi, 0x00, soc, 4, charging, 0]) + bytes(12))

    # ---- transporte ----
    def fileno(self):
        return self._r

    def _push(self, pkt):
        with self.lock:
            self.out.append(bytes(pkt))
            os.write(self._w, b"x")

    def write(self, m):
        m = bytes(m)
        if m[1] != self.index:
            self._push(bytes([0x10, m[1], 0x8F, m[2], m[3], 0x08, 0]))
            return
        if not self.online:
            self._push(bytes([0x10, m[1], 0x8F, m[2], m[3], 0x09, 0]))
            return
        feat, fn, p = m[2], m[3] >> 4, m[4:]
        try:
            payload = self.handle(self.FEATURES[feat], fn, p)
            self._push(bytes(m[:4]) + bytes(payload).ljust(16, b"\x00"))
        except (IndexError, KeyError, ValueError):
            self._push(bytes([0x11, m[1], 0xFF, feat, m[3], 0x07]) + bytes(14))

    def read(self, timeout):
        r, _, _ = select.select([self._r], [], [], max(0.0, timeout))
        if not r:
            return None
        os.read(self._r, 1)
        with self.lock:
            return self.out.pop(0) if self.out else None

    def close(self):
        pass

    # ---- respostas ----
    def handle(self, fid, fn, p):
        if fid == H.F_ROOT:
            if fn == 0:
                want = (p[0] << 8) | p[1]
                return [self.FEATURES.index(want) if want in self.FEATURES else 0, 0, 0]
            if fn == 1:
                return [4, 5, p[2]]
        if fid == H.F_DEVICE_NAME:
            if fn == 0:
                return [len(self.name)]
            if fn == 1:
                return list(self.name[p[0]:p[0] + 16])
            if fn == 2:
                return [3]
        if fid == H.F_UNIFIED_BATTERY and fn == 1:
            return [self.soc, 4, self.charging, 0]
        if fid == H.F_ADJUSTABLE_DPI:
            if fn == 1:  # 200..8000 passo 50
                return [0, 200 >> 8, 200 & 0xFF, 0xE0, 50, 8000 >> 8, 8000 & 0xFF, 0, 0]
            if fn == 2:
                return [0, self.dpi >> 8, self.dpi & 0xFF, 1000 >> 8, 1000 & 0xFF]
            if fn == 3:
                if not self.ignore_dpi:
                    self.dpi = (p[1] << 8) | p[2]
                return [0, p[1], p[2]]
        if fid == H.F_SMART_SHIFT:
            if fn == 0:
                return [self.ss[0], self.ss[1], 12]
            if fn == 1:
                if p[0]:
                    self.ss[0] = p[0]
                if p[1]:
                    self.ss[1] = p[1]
                return []
        if fid == H.F_HIRES_WHEEL:
            if fn == 0:
                return [8, 0x0C]
            if fn == 1:
                return [self.wheel]
            if fn == 2:
                self.wheel = p[0]
                return [self.wheel]
        if fid == H.F_REPORT_RATE:
            if fn == 0:
                return [0b10001011]  # 1, 2, 4, 8 ms
            if fn == 1:
                return [self.rate_ms]
            if fn == 2:
                self.rate_ms = p[0]
                return []
        if fid == H.F_ONBOARD_PROFILES:
            if fn == 0:
                return [0x01, 0x03, 0x01, 0x01, 0x01, 0x06, 0x06, 0x00, 0xFF, 0x0A, 0x02]
            if fn == 2:
                return [self.onboard]
            if fn == 1:
                self.onboard = p[0]
                return []
            if fn == 3:
                self.current_sector = (p[0] << 8) | p[1]
                return []
            if fn == 4:
                return [self.current_sector >> 8, self.current_sector & 0xFF]
            if fn == 5:
                sec, off = (p[0] << 8) | p[1], (p[2] << 8) | p[3]
                data = self.sectors[sec]
                if off + 16 > len(data):
                    raise ValueError("fora do setor")
                return list(data[off:off + 16])
            if fn == 6:
                sec, n = (p[0] << 8) | p[1], (p[4] << 8) | p[5]
                if sec >= 0x100 or sec not in self.sectors:
                    raise ValueError("setor só leitura")
                self._write = [sec, n, bytearray()]
                return []
            if fn == 7:
                self._write[2] += bytes(p[:16])
                return []
            if fn == 8:
                sec, n, buf = self._write
                self.sectors[sec] = bytes(buf[:n])
                self._write = None
                return []
        raise KeyError(fid)


_shared = None


def shared_mouse():
    """Um unico mouse simulado por processo (a bandeja e o painel veem o mesmo estado)."""
    global _shared
    if _shared is None:
        _shared = FakeMouse()
    return _shared


def discover_demo(nodes=None):
    fake = shared_mouse()
    found = H.probe_transport(fake, fake.bus) if fake.online else []
    return found, ([] if found else ["Mouse simulado desligado."])


def demo_nodes():
    return [dict(path="demo", bus=0x03, pid=0, name="demo")]


# --------------------------------------------------------------------------
# Headset MCHOSE simulado
# --------------------------------------------------------------------------
# Descriptor parecido com o do receptor: report 0x55 de 63 bytes nos dois
# sentidos, na pagina do fabricante 0xff90.
MCHOSE_DESCRIPTOR = bytes([
    0x06, 0x90, 0xFF, 0x09, 0x01, 0xA1, 0x01,       # Usage Page 0xff90, Usage 1, Collection
    0x85, 0x55, 0x15, 0x00, 0x26, 0xFF, 0x00,       # Report ID 0x55, 0..255
    0x75, 0x08, 0x95, 0x3F, 0x09, 0x01, 0x81, 0x02,  # 63 bytes de entrada
    0x95, 0x3F, 0x09, 0x01, 0x91, 0x02,             # 63 bytes de saida
    0xC0,
])


class FakeMchose:
    """Receptor 2.4 GHz de um headset MCHOSE, com o 'ruido' que o de verdade manda."""

    def __init__(self, battery=58):
        self.lock = threading.RLock()
        self.out = []
        self._r, self._w = os.pipe()
        self.battery = battery
        self.online = True
        self.writes = []

    def fileno(self):
        return self._r

    def _push(self, pkt):
        with self.lock:
            self.out.append(bytes(pkt).ljust(64, b"\x00"))
            os.write(self._w, b"x")

    def write(self, m):
        m = bytes(m)
        self.writes.append(m)
        if m[:3] == bytes([0x55, 0x65, 0x01]):
            self._push([0x55, 0x00, 0x01])               # "estou vivo"
            self._push([0x55, 0x65, 0x37, 0x05])         # outro campo, nao e bateria
            self._push([0x55, 0x65, self.battery if self.online else 0, 0x02])

    def battery_event(self, pct):
        self.battery = pct
        self._push([0x55, 0x65, pct, 0x02])

    def read(self, timeout):
        r, _, _ = select.select([self._r], [], [], max(0.0, timeout))
        if not r:
            return None
        os.read(self._r, 1)
        with self.lock:
            return self.out.pop(0) if self.out else None

    def close(self):
        pass


_shared_headset = None


def shared_headset():
    global _shared_headset
    if _shared_headset is None:
        _shared_headset = FakeMchose()
    return _shared_headset


def discover_demo_headsets():
    from .headset import MchoseHeadset
    return [MchoseHeadset(shared_headset(), "MCHOSE V9 Pro (demo)", 0x6046)], []

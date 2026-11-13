"""
Macros e teclas.

O G305 nao tem setor livre para macros na memoria, entao a macro roda no computador:
o botao e gravado no mouse como uma tecla reservada (F13..F24, uma por macro), e o
LogiMouse (na bandeja) escuta essa tecla na interface de teclado do receptor Logitech
e digita a macro por um teclado virtual (uinput).

Para a tecla reservada nao chegar aos programas, a interface do receptor e "agarrada"
(EVIOCGRAB) e todas as outras teclas dela sao repassadas pelo teclado virtual.
"""

import fcntl
import glob
import os
import select
import struct
import threading
import time

# nome -> (codigo Linux, uso HID)
KEYS = {}
for _n, _l in zip("qwertyuiop", range(16, 26)):
    KEYS[_n] = _l
for _n, _l in zip("asdfghjkl", range(30, 39)):
    KEYS[_n] = _l
for _n, _l in zip("zxcvbnm", range(44, 51)):
    KEYS[_n] = _l
KEYS = {k: (v, 0x04 + ord(k) - ord("a")) for k, v in KEYS.items()}
for _i in range(1, 10):
    KEYS[str(_i)] = (1 + _i, 0x1D + _i)
KEYS["0"] = (11, 0x27)
KEYS.update({
    "Enter": (28, 0x28), "Esc": (1, 0x29), "Backspace": (14, 0x2A), "Tab": (15, 0x2B), "Espaço": (57, 0x2C),
    "-": (12, 0x2D), "=": (13, 0x2E), "PrintScreen": (99, 0x46), "Insert": (110, 0x49), "Home": (102, 0x4A),
    "PageUp": (104, 0x4B), "Delete": (111, 0x4C), "End": (107, 0x4D), "PageDown": (109, 0x4E),
    "→": (106, 0x4F), "←": (105, 0x50), "↓": (108, 0x51), "↑": (103, 0x52),
})
for _i in range(1, 11):
    KEYS[f"F{_i}"] = (58 + _i, 0x39 + _i)
KEYS["F11"] = (87, 0x44)
KEYS["F12"] = (88, 0x45)

# modificadores: nome -> (codigo Linux, bit HID)
MODS = {"Ctrl": (29, 0x01), "Shift": (42, 0x02), "Alt": (56, 0x04), "Super": (125, 0x08)}
ALL = dict(KEYS)
ALL.update({k: (v[0], None) for k, v in MODS.items()})

HID_TO_NAME = {v[1]: k for k, v in KEYS.items()}

# Teclas reservadas para disparar macros: F13..F24
TRIGGERS = 12
TRIGGER_HID = 0x68
TRIGGER_LINUX = 183


def trigger_action(i):
    if not 0 <= i < TRIGGERS:
        raise ValueError("no máximo 12 macros")
    return {"kind": "key", "mods": 0, "value": TRIGGER_HID + i}


def trigger_index(hid_usage, mods=0):
    if mods == 0 and TRIGGER_HID <= hid_usage < TRIGGER_HID + TRIGGERS:
        return hid_usage - TRIGGER_HID
    return None


def combo_text(mods, usage):
    parts = [n for n, (_, bit) in MODS.items() if mods & bit]
    parts.append(HID_TO_NAME.get(usage, f"0x{usage:02x}"))
    return "+".join(p.upper() if len(p) == 1 else p for p in parts)


def key_action(names):
    """["Ctrl", "c"] -> acao de botao (tecla com modificadores, gravada no mouse)."""
    mods, key = 0, None
    for n in names:
        if n in MODS:
            mods |= MODS[n][1]
        elif n in KEYS:
            if key is not None:
                raise ValueError("só uma tecla além dos modificadores")
            key = KEYS[n][1]
        else:
            raise ValueError(f"tecla desconhecida: {n}")
    if key is None:
        raise ValueError("escolha uma tecla")
    return {"kind": "key", "mods": mods, "value": key}


def step_text(s):
    if s.get("t") == "wait":
        return f"⏱ {int(s.get('ms', 0))} ms"
    k = s.get("k", "?")
    k = k.upper() if len(k) == 1 else k
    return ("↓ " if s.get("t") == "down" else "↑ ") + k


def validate(macro):
    steps = macro.get("steps") or []
    held = set()
    for s in steps:
        t = s.get("t")
        if t == "wait":
            if not 0 <= int(s.get("ms", 0)) <= 10000:
                raise ValueError("espera entre 0 e 10000 ms")
        elif t in ("down", "up"):
            if s.get("k") not in ALL:
                raise ValueError(f"tecla desconhecida: {s.get('k')}")
            (held.add if t == "down" else held.discard)(s.get("k"))
        else:
            raise ValueError("passo inválido")
    if macro.get("mode", "once") not in ("once", "hold", "toggle"):
        raise ValueError("modo inválido")
    return sorted(held)  # teclas que ficaram apertadas (sao soltas no fim)


# --------------------------------------------------------------------------
# Linux: evdev e uinput
# --------------------------------------------------------------------------
EV_SYN, EV_KEY = 0, 1
EVENT = struct.Struct("llHHi")
EVIOCGRAB = 0x40044590
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_SETUP = 0x405C5503
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502


class VirtualKeyboard:
    def __init__(self, path="/dev/uinput"):
        self.fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_SYN)
        for code in range(1, 256):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        setup = struct.pack("<HHHH80sI", 0x06, 0x046D, 0x4C4D, 1, b"LogiMouse teclado virtual", 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        self.lock = threading.Lock()
        time.sleep(0.2)  # o sistema precisa ver o teclado novo antes da primeira tecla

    def emit(self, code, value):
        with self.lock:
            os.write(self.fd, EVENT.pack(0, 0, EV_KEY, code, value) + EVENT.pack(0, 0, EV_SYN, 0, 0))

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)


def play(kbd, macro, stop=None):
    """Executa os passos uma vez."""
    held = []
    for s in macro.get("steps") or []:
        if stop is not None and stop.is_set():
            break
        t = s.get("t")
        if t == "wait":
            time.sleep(max(0, int(s.get("ms", 0))) / 1000)
            continue
        code = ALL[s["k"]][0]
        kbd.emit(code, 1 if t == "down" else 0)
        if t == "down":
            held.append(code)
        elif code in held:
            held.remove(code)
        if not any(x.get("t") == "wait" for x in macro["steps"]):
            time.sleep(0.008)
    for code in reversed(held):
        kbd.emit(code, 0)


def _key_bits(event_dir):
    try:
        with open(os.path.join(event_dir, "device", "capabilities", "key")) as fh:
            words = fh.read().split()
    except OSError:
        return 0
    n = 0
    for w in words:
        n = (n << 64) | int(w, 16)
    return n


def logitech_key_nodes(root="/sys/class/input"):
    """Interfaces de teclado de receptores/mouses Logitech que podem mandar F13."""
    out = []
    for ev in sorted(glob.glob(os.path.join(root, "event*"))):
        try:
            with open(os.path.join(ev, "device", "id", "vendor")) as fh:
                vid = int(fh.read().strip(), 16)
            with open(os.path.join(ev, "device", "name")) as fh:
                name = fh.read().strip()
        except (OSError, ValueError):
            continue
        if vid != 0x046D or name.startswith("LogiMouse"):
            continue
        if not (_key_bits(ev) >> TRIGGER_LINUX) & 1:
            continue
        out.append(("/dev/input/" + os.path.basename(ev), name))
    return out


class MacroService:
    """Escuta as teclas reservadas e roda as macros. Roda numa thread da bandeja."""

    def __init__(self, get_macros, log=print):
        self.get_macros = get_macros
        self.log = log
        self.kbd = None
        self.fds = {}
        self.stop = threading.Event()
        self.running = {}
        self.problem = None

    def _open(self):
        for path, name in logitech_key_nodes():
            if path in self.fds.values():
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as e:
                self.problem = f"sem permissão para {path} ({e.strerror}); rode o instalar.sh de novo"
                continue
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)
            except OSError:
                os.close(fd)
                continue
            self.fds[fd] = path
            self.log(f"macros: escutando {name} ({path})")

    def run(self):
        while not self.stop.is_set():
            if not any(m for m in self.get_macros()):
                time.sleep(3)
                continue
            if self.kbd is None:
                try:
                    self.kbd = VirtualKeyboard()
                except OSError as e:
                    self.problem = f"sem acesso ao /dev/uinput ({e.strerror}); rode o instalar.sh de novo"
                    time.sleep(30)
                    continue
            self._open()
            if not self.fds:
                time.sleep(3)
                continue
            r, _, _ = select.select(list(self.fds), [], [], 2.0)
            for fd in r:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except OSError:
                    self.fds.pop(fd, None)
                    os.close(fd)
                    continue
                for o in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, typ, code, value = EVENT.unpack_from(data, o)
                    if typ == EV_KEY:
                        self._key(code, value)
        self.close()

    def _key(self, code, value):
        idx = code - TRIGGER_LINUX
        if not 0 <= idx < TRIGGERS:
            self.kbd.emit(code, value)  # repassa
            return
        macros = self.get_macros()
        if idx >= len(macros) or not macros[idx]:
            return
        m = macros[idx]
        mode = m.get("mode", "once")
        if value == 2:  # repeticao automatica da tecla
            return
        cur = self.running.get(idx)
        if mode == "once" and value == 1:
            if not (cur and cur[0].is_alive()):
                self._start(idx, m, loop=False)
        elif mode == "hold":
            if value == 1:
                self._start(idx, m, loop=True)
            elif cur:
                cur[1].set()
        elif mode == "toggle" and value == 1:
            if cur and cur[0].is_alive():
                cur[1].set()
            else:
                self._start(idx, m, loop=True)

    def _start(self, idx, m, loop):
        ev = threading.Event()

        def go():
            while True:
                play(self.kbd, m, ev)
                if not loop or ev.is_set() or self.stop.is_set():
                    break
        th = threading.Thread(target=go, daemon=True)
        self.running[idx] = (th, ev)
        th.start()

    def close(self):
        for fd in list(self.fds):
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 0)
            except OSError:
                pass
            os.close(fd)
        self.fds.clear()
        if self.kbd:
            self.kbd.close()
            self.kbd = None

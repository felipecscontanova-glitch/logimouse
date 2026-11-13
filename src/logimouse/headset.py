"""
Bateria de headsets sem programa para Linux.

MCHOSE (V9, V9 Pro, X9 e parecidos), pelo receptor 2.4 GHz
-----------------------------------------------------------
O receptor (chip C-Media; fabricante USB 0x3837 no X9, 0x291d no V9 Pro) tem uma colecao HID do
fabricante (usage page 0xff90) com o report 0x55 nos dois sentidos:

    pergunta: 55 65 01 00 ...      (mensagem 0x65, campo pedido 0x01 = bateria)
    resposta: 55 65 VV 02 ...      (VV = bateria em %, 02 = "este valor e a bateria")

O receptor tambem manda sozinho outros reports no mesmo formato (um
"estou vivo" e campos ainda nao identificados); so o campo 0x02 e lido.
Fonte: driver do MCHOSE X9 no HeadsetControl (github.com/Sapd/HeadsetControl,
PR #563), feito a partir de uma captura USB do app oficial "M HUB".
Confirmado num V9 Pro real (receptor 291d:385d): 55 65 01 -> 55 65 32 02 (50%).

Com o cabo de carga plugado o fone sai do 2.4 GHz, entao "carregando" nao
aparece por este caminho.

Qualquer headset, por Bluetooth ou com bateria conhecida pelo sistema
---------------------------------------------------------------------
Lido do UPower (o mesmo servico que mostra baterias em Configuracoes >
Energia), filtrando os dispositivos do tipo headset/fone.
"""

import glob
import os
import re
import select
import shutil
import subprocess
import time

MCHOSE_VID = 0x3837
# Fabricantes USB usados nos receptores MCHOSE (visto no diagnostico de um V9 Pro: 291d:385d).
MCHOSE_VIDS = (0x3837, 0x291D)
KNOWN_MODELS = {(0x3837, 0x6045): "MCHOSE X9", (0x291D, 0x385D): "MCHOSE V9 Pro"}

REPORT_ID = 0x55
MSG_VALUE = 0x65
ASK_BATTERY = 0x01
FIELD_BATTERY = 0x02
DEFAULT_LEN = 64  # bytes escritos, contando o report id (igual ao app oficial)


class HeadsetError(Exception):
    pass


class HeadsetTimeout(HeadsetError):
    pass


# --------------------------------------------------------------------------
# Report descriptor (para achar o report 0x55 e o tamanho certo)
# --------------------------------------------------------------------------
def parse_report_descriptor(desc):
    """Devolve {("in"|"out"|"feat", report_id): {"bits": n, "pages": {usage_page, ...}}}."""
    reports = {}
    g = dict(page=0, size=0, count=0, rid=0)
    stack = []
    i = 0
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:  # item longo: pula
            if i + 1 >= len(desc):
                break
            i += 3 + desc[i + 1]
            continue
        size = (0, 1, 2, 4)[b & 0x03]
        kind = (b >> 2) & 0x03
        tag = b >> 4
        data = desc[i + 1:i + 1 + size]
        val = int.from_bytes(data, "little") if data else 0
        i += 1 + size
        if kind == 1:  # global
            if tag == 0:
                g["page"] = val
            elif tag == 7:
                g["size"] = val
            elif tag == 8:
                g["rid"] = val
            elif tag == 9:
                g["count"] = val
            elif tag == 10:
                stack.append(dict(g))
            elif tag == 11 and stack:
                g = stack.pop()
        elif kind == 0 and tag in (8, 9, 11):  # Input, Output, Feature
            name = {8: "in", 9: "out", 11: "feat"}[tag]
            r = reports.setdefault((name, g["rid"]), {"bits": 0, "pages": set()})
            r["bits"] += g["size"] * g["count"]
            r["pages"].add(g["page"])
    return reports


def mchose_endpoint(desc):
    """(tem_report_0x55, bytes_para_escrever) a partir do descriptor."""
    reports = parse_report_descriptor(desc)
    out = reports.get(("out", REPORT_ID)) or reports.get(("feat", REPORT_ID))
    inp = reports.get(("in", REPORT_ID))
    if not out and not inp:
        return False, DEFAULT_LEN
    vendor = any(p >= 0xFF00 for r in (out, inp) if r for p in r["pages"])
    if not vendor:
        return False, DEFAULT_LEN
    length = 1 + (out["bits"] + 7) // 8 if out and out["bits"] else DEFAULT_LEN
    return True, max(4, min(length, 1025))


# --------------------------------------------------------------------------
# Descoberta
# --------------------------------------------------------------------------
_HID_DIR = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}$")


def hid_nodes(vendor=None, root="/sys/class/hidraw"):
    """Todos os /dev/hidrawN (opcionalmente de um ou mais fabricantes), com descriptor."""
    if isinstance(vendor, int):
        vendor = (vendor,)
    out = []
    paths = glob.glob(os.path.join(root, "hidraw*"))
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
        if vendor is not None and vid not in vendor:
            continue
        out.append(dict(path="/dev/" + os.path.basename(sp), bus=bus, vid=vid, pid=pid,
                        name=props.get("HID_NAME", "").strip(), desc=desc,
                        virtual=bool(_HID_DIR.match(os.path.basename(os.path.dirname(dev))))))
    return out


class HidrawPort:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def fileno(self):
        return self.fd

    def write(self, data):
        os.write(self.fd, bytes(data))

    def read(self, timeout):
        r, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not r:
            return None
        try:
            return os.read(self.fd, 1024)
        except BlockingIOError:
            return None

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


def mchose_nodes(root="/sys/class/hidraw"):
    """Interfaces HID que podem ser de um receptor MCHOSE (por fabricante ou pelo nome)."""
    return [n for n in hid_nodes(root=root)
            if n["vid"] in MCHOSE_VIDS or "mchose" in n["name"].lower()]


def model_name(node):
    name = (node.get("name") or "").strip()
    vid, pid = node.get("vid", MCHOSE_VID), node.get("pid", 0)
    m = re.search(r"(?i)mchose\b.*", name)
    if m:  # "C-Media Electronics Inc MCHOSE V9 PRO" -> "MCHOSE V9 PRO"
        return "MCHOSE" + m.group(0)[6:]
    if (vid, pid) in KNOWN_MODELS:
        return KNOWN_MODELS[(vid, pid)]
    if name and not re.match(r"(?i)(c-media|usb audio|generic)", name):
        return f"MCHOSE {name}"
    return f"Headset MCHOSE ({vid:04x}:{pid:04x})"


class MchoseHeadset:
    kind = None
    kind_name = "Headset"
    is_pointer = False
    is_headset = True
    protocol = None

    def __init__(self, port, name, pid=0, bus=0x03, write_len=DEFAULT_LEN, vid=MCHOSE_VID):
        self.t = port
        self.name = name
        self.vid = vid
        self.pid = pid
        self.bus = bus
        self.write_len = write_len
        self.last_battery = None

    def __repr__(self):
        return f"<MchoseHeadset {self.name!r}>"

    @property
    def connection(self):
        return "Bluetooth" if self.bus == 0x05 else "Receptor 2.4 GHz"

    @property
    def detail(self):
        return f"{self.kind_name} · {self.connection} · {self.vid:04x}:{self.pid:04x}"

    def _battery_dict(self, pct):
        return dict(percent=pct, level=None, status="Ligado", charging=False, voltage=None,
                    source="MCHOSE 2.4 GHz (report 0x55)")

    def parse(self, pkt):
        """Bateria (dict) se o pacote for uma resposta/aviso de bateria valido, senao None."""
        if not pkt or len(pkt) < 4 or pkt[0] != REPORT_ID or pkt[1] != MSG_VALUE or pkt[3] != FIELD_BATTERY:
            return None
        pct = pkt[2]
        if pct > 100:
            return None
        return self._battery_dict(pct)

    def battery(self, timeout=1.5):
        msg = bytes([REPORT_ID, MSG_VALUE, ASK_BATTERY]).ljust(self.write_len, b"\x00")
        try:
            self.t.write(msg)
        except OSError as e:
            raise HeadsetError(f"não deu para falar com o receptor ({e.strerror or e})") from e
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise HeadsetTimeout("o fone não respondeu (desligado ou fora de alcance?)")
            try:
                pkt = self.t.read(left)
            except OSError as e:
                raise HeadsetError(f"o receptor saiu da USB ({e.strerror or e})") from e
            b = self.parse(pkt)
            if b is not None:
                if b["percent"] == 0:
                    # o receptor responde 0 quando nao ha fone conectado a ele
                    raise HeadsetTimeout("sem leitura de bateria (fone desligado?)")
                self.last_battery = b
                return b

    def read_battery(self):
        return self.battery()

    def close(self):
        self.t.close()


def discover_mchose(nodes=None):
    """Devolve (headsets, problemas)."""
    found, problems = [], []
    nodes = mchose_nodes() if nodes is None else nodes
    seen_pid = set()
    for n in nodes:
        if n.get("virtual"):
            continue
        ok, wlen = mchose_endpoint(n["desc"])
        if not ok or (n["vid"], n["pid"], n["bus"]) in seen_pid:
            continue
        try:
            port = HidrawPort(n["path"])
        except PermissionError:
            problems.append(f"Sem permissão para abrir o receptor do headset ({n['path']}). "
                            "Rode o instalar.sh de novo e recoloque o receptor.")
            continue
        except OSError as e:
            problems.append(f"{n['path']}: {e}")
            continue
        seen_pid.add((n["vid"], n["pid"], n["bus"]))
        found.append(MchoseHeadset(port, model_name(n), n["pid"], n["bus"], wlen, n["vid"]))
    return found, problems


# --------------------------------------------------------------------------
# UPower: Bluetooth e outros headsets que o sistema ja conhece
# --------------------------------------------------------------------------
HEADSET_TYPES = ("headset", "headphones")


def _run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def parse_upower_info(text):
    info = dict(type=None)
    for line in text.splitlines():
        m = re.match(r"^\s{2}(\S+)\s*$", line)
        if m and info["type"] is None:
            info["type"] = m.group(1)
            continue
        m = re.match(r"^\s+([\w-]+):\s+(.*?)\s*$", line)
        if m:
            info.setdefault(m.group(1), m.group(2))
    return info


def upower_headsets(run=_run):
    if run is _run and not shutil.which("upower"):
        return []
    out = []
    for path in run(["upower", "-e"]).split():
        if "DisplayDevice" in path:
            continue
        info = parse_upower_info(run(["upower", "-i", path]))
        model = info.get("model") or ""
        if info.get("type") not in HEADSET_TYPES and "mchose" not in model.lower():
            continue
        m = re.match(r"(\d+(?:[.,]\d+)?)%", info.get("percentage", ""))
        if not m:
            continue
        out.append(UPowerHeadset(path, model or "Headset", info, run))
    return out


class UPowerHeadset:
    kind = None
    kind_name = "Headset"
    is_pointer = False
    is_headset = True
    protocol = None

    def __init__(self, path, name, info, run=_run):
        self.path = path
        self.name = name
        self.info = info
        self.run = run
        self.last_battery = None

    @property
    def connection(self):
        return "Bluetooth" if "bluez" in (self.info.get("native-path") or "") else "Sistema"

    @property
    def detail(self):
        return f"{self.kind_name} · {self.connection}"

    def battery(self):
        info = parse_upower_info(self.run(["upower", "-i", self.path])) or self.info
        m = re.match(r"(\d+(?:[.,]\d+)?)%", info.get("percentage", ""))
        if not m:
            raise HeadsetTimeout("o sistema não tem a bateria deste headset agora")
        state = info.get("state", "")
        st = {"discharging": "Descarregando", "charging": "Carregando", "fully-charged": "Carga completa",
              "pending-charge": "Aguardando carga"}.get(state, "Ligado")
        b = dict(percent=round(float(m.group(1).replace(",", "."))), level=None, status=st,
                 charging=state == "charging", voltage=None, source="sistema (UPower)")
        self.last_battery = b
        return b

    def read_battery(self):
        return self.battery()

    def close(self):
        pass


def discover():
    """Todos os headsets: MCHOSE pelo receptor e os que o UPower conhece."""
    found, problems = discover_mchose()
    names = {h.name.lower() for h in found}
    for h in upower_headsets():
        if h.name.lower() not in names:
            found.append(h)
    return found, problems


# --------------------------------------------------------------------------
# Diagnostico (para adaptar o app a um modelo novo)
# --------------------------------------------------------------------------
def _hex(b):
    return " ".join(f"{x:02x}" for x in b)


def diagnose(listen=10.0, out=print):
    out(f"LogiMouse - diagnóstico de headset ({time.strftime('%Y-%m-%d %H:%M')})")
    out("")
    out("== Dispositivos USB")
    for d in sorted(glob.glob("/sys/bus/usb/devices/*")):
        def rd(f, d=d):
            try:
                with open(os.path.join(d, f)) as fh:
                    return fh.read().strip()
            except OSError:
                return ""
        vid = rd("idVendor")
        if not vid:
            continue
        name = f"{rd('manufacturer')} {rd('product')}".strip()
        if vid in {f"{v:04x}" for v in MCHOSE_VIDS} or re.search(r"(?i)mchose|c-media|headset|audio", name):
            out(f"  {vid}:{rd('idProduct')}  {name}")
    out("")
    out("== Interfaces HID que podem ser do headset")
    nodes = [n for n in hid_nodes() if n["vid"] in MCHOSE_VIDS
             or re.search(r"(?i)mchose|c-media|headset|audio", n["name"])]
    if not nodes:
        out("  nenhuma (o receptor está na USB? com o fone ligado?)")
    for n in nodes:
        perm = "leitura+escrita" if os.access(n["path"], os.R_OK | os.W_OK) else "SEM PERMISSÃO"
        ok, wlen = mchose_endpoint(n["desc"])
        out(f"  {n['path']}  bus {n['bus']:02x}  {n['vid']:04x}:{n['pid']:04x}  {n['name']!r}  [{perm}]")
        out(f"    report 0x55 do fabricante: {'sim' if ok else 'não'}  (escrita de {wlen} bytes)")
        for (kind, rid), r in sorted(parse_report_descriptor(n["desc"]).items(), key=lambda x: (x[0][1], x[0][0])):
            pages = ",".join(f"{p:04x}" for p in sorted(r["pages"]))
            out(f"    report {rid:#04x} {kind:<4} {r['bits'] // 8:>4} bytes  páginas {pages}")
        out(f"    descriptor: {_hex(n['desc'])}")
    usable = [n for n in nodes if os.access(n["path"], os.R_OK | os.W_OK) and not n["virtual"]]
    for n in usable:
        ok, wlen = mchose_endpoint(n["desc"])
        out("")
        out(f"== Conversa com {n['path']}")
        try:
            port = HidrawPort(n["path"])
        except OSError as e:
            out(f"  não abriu: {e}")
            continue
        try:
            if ok:
                port.write(bytes([REPORT_ID, MSG_VALUE, ASK_BATTERY]).ljust(wlen, b"\x00"))
                out(f"  > {_hex(bytes([REPORT_ID, MSG_VALUE, ASK_BATTERY]))} ... (pergunta da bateria)")
            out(f"  ouvindo por {listen:.0f} s: mexa no volume, no microfone, ligue/desligue o fone...")
            end = time.monotonic() + listen
            seen = 0
            while time.monotonic() < end and seen < 300:
                pkt = port.read(end - time.monotonic())
                if pkt:
                    seen += 1
                    mark = ""
                    if len(pkt) >= 4 and pkt[0] == REPORT_ID and pkt[1] == MSG_VALUE:
                        mark = f"   <- campo {pkt[3]:#04x} = {pkt[2]}" + ("  (BATERIA)" if pkt[3] == FIELD_BATTERY else "")
                    out(f"  < {_hex(pkt[:24])}{' ...' if len(pkt) > 24 else ''}{mark}")
            if not seen:
                out("  (nada recebido)")
        except OSError as e:
            out(f"  erro: {e}")
        finally:
            port.close()
    out("")
    out("== Baterias no sistema (UPower)")
    text = _run(["upower", "-d"]) if shutil.which("upower") else ""
    blocks = [b for b in text.split("\n\n") if "percentage" in b and "DisplayDevice" not in b]
    for b in blocks:
        info = parse_upower_info(b.split("\n", 1)[1] if "\n" in b else b)
        out(f"  {info.get('type')}: {info.get('model', '?')} {info.get('percentage', '')}")
    if not blocks:
        out("  nenhuma")
    out("")
    found, problems = discover()
    for p in problems:
        out(f"  ! {p}")
    out(f"== Resultado: {', '.join(f'{h.name} ({h.connection})' for h in found) or 'nenhum headset reconhecido'}")
    for h in found:
        try:
            out(f"   {h.name}: bateria {h.battery()['percent']}%")
        except HeadsetError as e:
            out(f"   {h.name}: {e}")
        h.close()

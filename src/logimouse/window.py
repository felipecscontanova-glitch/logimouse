"""Painel do LogiMouse 2.0 em GTK 4 + libadwaita (tema escuro neon)."""

import math
import os
import queue
import subprocess
import threading
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_NAME, __version__  # noqa: E402
from . import audio as AU  # noqa: E402
from . import config  # noqa: E402
from . import headset as HS  # noqa: E402
from . import hidpp as H  # noqa: E402
from . import macros as M  # noqa: E402
from . import onboard as O  # noqa: E402
from . import profiles as P  # noqa: E402
from . import update as U  # noqa: E402

APP_ID = "io.github.felipecscontanova.LogiMouse"
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO = os.path.join(ASSETS, "logimouse.svg")

PURPLE = (0xA8 / 255, 0x55 / 255, 0xF7 / 255)
CYAN = (0x22 / 255, 0xD3 / 255, 0xEE / 255)
LINE = (0x1C / 255, 0x1D / 255, 0x2E / 255)
MUTED = (0xA3 / 255, 0xA7 / 255, 0xC2 / 255)
TEXT = (0xF1 / 255, 0xF2 / 255, 0xF8 / 255)

CSS = """
window.lm, .lm-bg { background: #07070c; color: #f1f2f8; }
headerbar.lm-header { background: #0b0b13; border-bottom: 1px solid #1c1d2e; box-shadow: none; min-height: 56px; }
.lm-wordmark { font-weight: 800; font-size: 17px; letter-spacing: 2px; }
.lm-crumb { color: #a3a7c2; font-size: 13px; }
.lm-card { background: #0e0f1a; border: 1px solid #23243a; border-radius: 16px; padding: 20px; }
.lm-card.glow { border-color: #a855f7; box-shadow: 0 0 26px alpha(#a855f7, 0.18); }
.lm-card.dashed { border-style: dashed; border-color: #34365a; }
button.lm-devcard { background-image: linear-gradient(160deg, #13142a, #0b0b14); border: 1px solid #2a2b45;
    border-radius: 20px; padding: 24px; color: #f1f2f8; }
button.lm-devcard:hover { border-color: #a855f7; box-shadow: 0 0 26px alpha(#a855f7, 0.35); }
.lm-title { font-size: 28px; font-weight: 800; }
.lm-name { font-size: 22px; font-weight: 800; }
.lm-h2 { font-size: 15px; font-weight: 700; }
.lm-muted { color: #a3a7c2; font-size: 13px; }
.lm-small { color: #a3a7c2; font-size: 12px; }
.lm-tag { font-size: 11px; font-weight: 800; letter-spacing: 1px; color: #22d3ee; }
.lm-tag.purple { color: #c084fc; }
.lm-big { font-size: 40px; font-weight: 800; color: #22d3ee; }
.lm-stat { background: #090a12; border: 1px solid #1c1d2e; border-radius: 12px; padding: 10px 12px; }
.lm-stat-v { font-size: 15px; font-weight: 700; }
button.lm-pill { background: #14152a; color: #c9cbe0; border: 1px solid #2a2b45; border-radius: 10px;
    padding: 8px 14px; min-height: 28px; font-weight: 500; }
button.lm-pill:checked { background: alpha(#a855f7, 0.18); border-color: #a855f7; color: #f1f2f8; font-weight: 700;
    box-shadow: 0 0 14px alpha(#a855f7, 0.35); }
button.lm-pill.cyan:checked { background: alpha(#22d3ee, 0.14); border-color: #22d3ee; box-shadow: 0 0 14px alpha(#22d3ee, 0.35); }
button.lm-level { background: #14152a; border: 1px solid #2a2b45; border-radius: 14px; padding: 12px 6px; color: #f1f2f8; }
button.lm-level:checked { background: #1a1033; border-color: #a855f7; box-shadow: 0 0 16px alpha(#a855f7, 0.3); }
.lm-level-v { font-size: 20px; font-weight: 800; }
button.lm-primary { background-image: linear-gradient(135deg, #a855f7, #7c3aed); color: white; font-weight: 700;
    border-radius: 10px; padding: 8px 18px; box-shadow: 0 0 18px alpha(#a855f7, 0.4); border: none; }
button.lm-primary:disabled { background-image: none; background: #1c1d2e; color: #6b6f96; box-shadow: none; }
button.lm-ghost { background: transparent; border: 1px solid #34365a; border-radius: 10px; padding: 8px 14px; color: #c9cbe0; }
button.lm-ghost.danger { border-color: #f97316; color: #fdba74; }
button.lm-rec:checked { background: alpha(#ef4444, 0.2); border-color: #ef4444; box-shadow: 0 0 16px alpha(#ef4444, 0.4); color: #fff; }
.lm-side { background: #09090f; border-right: 1px solid #1c1d2e; }
.lm-side list { background: transparent; }
.lm-side row { border-radius: 12px; padding: 12px 14px; margin: 2px 10px; color: #a3a7c2; }
.lm-side row:selected { background: #1a1033; color: #f1f2f8; box-shadow: inset 0 0 0 1px #a855f7; }
.lm-footer { background: #0b0b13; border-top: 1px solid #1c1d2e; padding: 6px 20px; }
.lm-chip { border-radius: 8px; padding: 6px 10px; font-weight: 600; font-size: 13px; }
.lm-chip.down { background: alpha(#22d3ee, 0.12); border: 1px solid alpha(#22d3ee, 0.55); color: #a5f3fc; }
.lm-chip.up { background: alpha(#a855f7, 0.12); border: 1px solid alpha(#a855f7, 0.55); color: #e9d5ff; }
.lm-chip.wait { border: 1px dashed #34365a; color: #a3a7c2; }
.lm-badge { background: #22d3ee; color: #07070c; font-size: 10px; font-weight: 800; border-radius: 999px; padding: 3px 8px; }
.lm-btnrow { padding: 8px 6px; border-radius: 12px; }
.lm-btnrow.sel { background: #1a1033; }
.lm-num { background: #1c1d33; color: #c9cbe0; border-radius: 999px; min-width: 28px; min-height: 28px; font-weight: 800; }
.lm-num.sel { background: #22d3ee; color: #07070c; }
.lm-testpad { border: 1px solid #a855f7; border-radius: 16px; background-image: radial-gradient(circle, #1a1033, #0a0a13); }
.lm-testv { font-size: 34px; font-weight: 800; }
.lm-warn { color: #fdba74; font-size: 13px; }
scale trough { background: #1c1d2e; min-height: 6px; border-radius: 999px; }
scale highlight { background-image: linear-gradient(90deg, #a855f7, #22d3ee); border-radius: 999px; }
scale slider { background: #f1f2f8; min-width: 18px; min-height: 18px; }
switch:checked { background-image: linear-gradient(90deg, #a855f7, #22d3ee); }
levelbar block.filled { background-image: linear-gradient(90deg, #a855f7, #22d3ee); }
levelbar block.empty { background: #1c1d2e; }
entry, dropdown > button, spinbutton { background: #14152a; border: 1px solid #2a2b45; border-radius: 10px; color: #f1f2f8; }
"""


# --------------------------------------------------------------------------
# Ajudantes
# --------------------------------------------------------------------------
def lab(text="", *classes, xalign=0.0, wrap=False, markup=False):
    w = Gtk.Label()
    if markup:
        w.set_markup(text)
    else:
        w.set_text(text)
    w.set_xalign(xalign)
    if wrap:
        w.set_wrap(True)
        w.set_max_width_chars(70)
    for c in classes:
        w.add_css_class(c)
    return w


def vbox(spacing=12, *classes):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in classes:
        b.add_css_class(c)
    return b


def hbox(spacing=12, *classes):
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in classes:
        b.add_css_class(c)
    return b


def card(title=None, sub=None, *classes):
    c = vbox(14, "lm-card", *classes)
    if title:
        c.append(lab(title, "lm-h2"))
    if sub:
        c.append(lab(sub, "lm-muted", wrap=True))
    return c


def button(text, *classes, cb=None, fill=False):
    b = Gtk.Button(label=text)
    for c in " ".join(classes).split():
        b.add_css_class(c)
    if not fill:
        b.set_halign(Gtk.Align.START)
    if cb:
        b.connect("clicked", lambda *_: cb())
    return b


def pills(options, current, on_pick, cyan=False):
    """Fileira de botoes de escolha unica. options: [(valor, texto)]."""
    row = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8,
                      max_children_per_line=12, homogeneous=False)
    first = None
    for value, text in options:
        b = Gtk.ToggleButton(label=text)
        b.add_css_class("lm-pill")
        if cyan:
            b.add_css_class("cyan")
        if first is None:
            first = b
        else:
            b.set_group(first)
        b.set_active(value == current)
        b.connect("toggled", lambda w, v=value: w.get_active() and on_pick(v))
        row.append(b)
    return row


def switch_row(text, active, on_change, sub=None, sensitive=True):
    row = hbox(12)
    txt = vbox(2)
    txt.set_hexpand(True)
    txt.append(lab(text))
    if sub:
        txt.append(lab(sub, "lm-small", wrap=True))
    row.append(txt)
    sw = Gtk.Switch(active=bool(active), valign=Gtk.Align.CENTER)
    sw.set_sensitive(sensitive)
    sw.connect("notify::active", lambda w, _p: on_change(w.get_active()))
    row.append(sw)
    return row, sw


def scroll(child):
    sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    sc.set_vexpand(True)
    sc.set_child(child)
    return sc


def gradient(cr, x0, y0, x1, y1):
    import cairo
    g = cairo.LinearGradient(x0, y0, x1, y1)
    g.add_color_stop_rgb(0, *PURPLE)
    g.add_color_stop_rgb(1, *CYAN)
    return g


class Worker:
    """Conversa com os dispositivos numa thread so, fora da interface."""

    def __init__(self):
        self.q = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, fn, ok=None, err=None):
        self.q.put((fn, ok, err))

    def _loop(self):
        while True:
            fn, ok, err = self.q.get()
            try:
                res, cb = fn(), ok
            except Exception as e:  # noqa: BLE001 - qualquer erro vira mensagem na tela
                if not isinstance(e, (*H.DEVICE_ERRORS, HS.HeadsetError, O.OnboardError, ValueError)):
                    traceback.print_exc()
                res, cb = e, err
            if cb:
                GLib.idle_add(self._call, cb, res)

    @staticmethod
    def _call(cb, res):
        try:
            cb(res)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        return False


# --------------------------------------------------------------------------
# Desenhos
# --------------------------------------------------------------------------
class Ring(Gtk.DrawingArea):
    def __init__(self, size=110, pct=None, text=None, sub="bateria"):
        super().__init__()
        self.pct, self.text, self.sub = pct, text, sub
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)

    def set(self, pct, text=None):
        self.pct, self.text = pct, text
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        r = min(w, h) / 2 - 7
        cx, cy = w / 2, h / 2
        cr.set_line_width(9)
        cr.set_source_rgb(*LINE)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        if self.pct:
            cr.set_source(gradient(cr, 0, 0, w, h))
            cr.set_line_cap(1)
            cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * max(0.01, min(1, self.pct / 100)))
            cr.stroke()
        cr.set_source_rgb(*TEXT)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(r * 0.46)
        t = self.text or (f"{self.pct}%" if self.pct is not None else "—")
        ext = cr.text_extents(t)
        cr.move_to(cx - ext.width / 2 - ext.x_bearing, cy + (ext.height / 2 if not self.sub else ext.height / 3))
        cr.show_text(t)
        if self.sub and r > 30:
            cr.set_source_rgb(*MUTED)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(r * 0.2)
            e2 = cr.text_extents(self.sub)
            cr.move_to(cx - e2.width / 2, cy + r * 0.42)
            cr.show_text(self.sub)


class MouseDiagram(Gtk.DrawingArea):
    # posicao (x, y, raio) dos numeros num mouse de 200x300
    SPOTS = [(58, 66, 13), (142, 66, 13), (128, 40, 11), (48, 155, 11), (48, 191, 11), (128, 98, 11),
             (152, 155, 11), (152, 191, 11), (100, 250, 11)]

    def __init__(self, count, on_pick):
        super().__init__()
        self.count, self.sel, self.on_pick = count, 0, on_pick
        self.set_content_width(220)
        self.set_content_height(320)
        self.set_draw_func(self._draw)
        g = Gtk.GestureClick()
        g.connect("pressed", self._click)
        self.add_controller(g)

    def _xy(self, w, h):
        s = min(w / 200, h / 300)
        return s, (w - 200 * s) / 2, (h - 300 * s) / 2

    def _click(self, _g, _n, x, y):
        s, ox, oy = self._xy(self.get_width(), self.get_height())
        for i, (sx, sy, r) in enumerate(self.SPOTS[:self.count]):
            if (x - (ox + sx * s)) ** 2 + (y - (oy + sy * s)) ** 2 <= (r * s + 6) ** 2:
                self.on_pick(i)
                return

    def _draw(self, _a, cr, w, h):
        s, ox, oy = self._xy(w, h)
        cr.translate(ox, oy)
        cr.scale(s, s)
        cr.move_to(100, 12)
        cr.curve_to(150, 12, 176, 52, 176, 120)
        cr.line_to(176, 210)
        cr.curve_to(176, 262, 144, 290, 100, 290)
        cr.curve_to(56, 290, 24, 262, 24, 210)
        cr.line_to(24, 120)
        cr.curve_to(24, 52, 50, 12, 100, 12)
        cr.close_path()
        cr.set_source_rgb(0x14 / 255, 0x15 / 255, 0x2A / 255)
        cr.fill_preserve()
        cr.set_source_rgb(0x34 / 255, 0x36 / 255, 0x5A / 255)
        cr.set_line_width(2)
        cr.stroke()
        cr.move_to(100, 12)
        cr.line_to(100, 118)
        cr.move_to(24, 118)
        cr.line_to(176, 118)
        cr.stroke()
        cr.rectangle(92, 38, 16, 40)
        cr.rectangle(94, 88, 12, 20)
        cr.rectangle(18, 140, 10, 30)
        cr.rectangle(18, 176, 10, 30)
        cr.stroke()
        cr.select_font_face("Sans", 0, 1)
        for i, (x, y, r) in enumerate(self.SPOTS[:self.count]):
            cr.arc(x, y, r, 0, 2 * math.pi)
            cr.set_source_rgb(*(CYAN if i == self.sel else (0x6B / 255, 0x6F / 255, 0x96 / 255)))
            cr.fill()
            cr.set_source_rgb(0.03, 0.03, 0.05)
            cr.set_font_size(r)
            t = str(i + 1)
            e = cr.text_extents(t)
            cr.move_to(x - e.width / 2 - e.x_bearing, y + e.height / 2)
            cr.show_text(t)


class EqCurve(Gtk.DrawingArea):
    """Curva do equalizador: arraste os pontos para cima/baixo."""

    def __init__(self, gains, on_change, on_done):
        super().__init__()
        self.gains = list(gains)
        self.on_change, self.on_done = on_change, on_done
        self.drag = None
        self.set_content_height(230)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._begin)
        g.connect("drag-update", self._update)
        g.connect("drag-end", self._end)
        self.add_controller(g)
        self.start = (0, 0)

    def _x(self, i, w):
        return w * (0.05 + 0.9 * i / 9)

    def _y(self, g, h):
        return h / 2 - g * (h / 2 - 16) / 12

    def _gain_at(self, y, h):
        return max(-12, min(12, round((h / 2 - y) * 12 / (h / 2 - 16))))

    def _begin(self, _g, x, y):
        w = self.get_width()
        self.drag = min(range(10), key=lambda i: abs(self._x(i, w) - x))
        self.start = (x, y)
        self._set(y)

    def _update(self, _g, dx, dy):
        if self.drag is not None:
            self._set(self.start[1] + dy)

    def _end(self, *_):
        if self.drag is not None:
            self.drag = None
            self.on_done(list(self.gains))

    def _set(self, y):
        g = self._gain_at(y, self.get_height())
        if self.gains[self.drag] != g:
            self.gains[self.drag] = g
            self.on_change(list(self.gains))
            self.queue_draw()

    def set_gains(self, gains):
        self.gains = list(gains)
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgb(0x09 / 255, 0x0A / 255, 0x12 / 255)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_line_width(1)
        for g in (-12, -6, 0, 6, 12):
            cr.set_source_rgb(*(LINE if g else (0x2A / 255, 0x2B / 255, 0x45 / 255)))
            cr.move_to(0, self._y(g, h))
            cr.line_to(w, self._y(g, h))
            cr.stroke()
        pts = [(self._x(i, w), self._y(g, h)) for i, g in enumerate(self.gains)]

        def path():
            cr.move_to(0, pts[0][1])
            cr.line_to(*pts[0])
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                mx = (x0 + x1) / 2
                cr.curve_to(mx, y0, mx, y1, x1, y1)
            cr.line_to(w, pts[-1][1])
        path()
        cr.line_to(w, h)
        cr.line_to(0, h)
        cr.close_path()
        cr.set_source_rgba(*PURPLE, 0.14)
        cr.fill()
        path()
        cr.set_source(gradient(cr, 0, 0, w, 0))
        cr.set_line_width(3)
        cr.stroke()
        for i, (x, y) in enumerate(pts):
            cr.arc(x, y, 9 if i != self.drag else 11, 0, 2 * math.pi)
            cr.set_source_rgb(0.03, 0.03, 0.05)
            cr.fill_preserve()
            cr.set_source_rgb(*CYAN)
            cr.set_line_width(3)
            cr.stroke()


class Bars(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.levels = []
        self.set_content_height(56)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def set(self, levels):
        self.levels = levels
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgb(0x09 / 255, 0x0A / 255, 0x12 / 255)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        lv = self.levels or [0.04] * 40
        bw = w / len(lv)
        cr.set_source_rgb(*(PURPLE if self.levels else LINE))
        for i, v in enumerate(lv):
            bh = max(3, v * (h - 10))
            cr.rectangle(i * bw + 1, (h - bh) / 2, max(1, bw - 2), bh)
        cr.fill()


# --------------------------------------------------------------------------
# Teclas do GTK -> nomes do LogiMouse
# --------------------------------------------------------------------------
GDK_KEYS = {"Return": "Enter", "KP_Enter": "Enter", "Escape": "Esc", "BackSpace": "Backspace", "Tab": "Tab",
            "space": "Espaço", "minus": "-", "equal": "=", "Print": "PrintScreen", "Insert": "Insert",
            "Home": "Home", "Page_Up": "PageUp", "Delete": "Delete", "End": "End", "Page_Down": "PageDown",
            "Right": "→", "Left": "←", "Down": "↓", "Up": "↑",
            "Control_L": "Ctrl", "Control_R": "Ctrl", "Shift_L": "Shift", "Shift_R": "Shift",
            "Alt_L": "Alt", "Alt_R": "Alt", "ISO_Level3_Shift": "Alt", "Super_L": "Super", "Super_R": "Super"}


def key_name(keyval):
    n = Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or ""
    if n in GDK_KEYS:
        return GDK_KEYS[n]
    if len(n) == 1 and (n.isalpha() or n.isdigit()) and n.lower() in M.KEYS:
        return n.lower()
    if n.startswith("F") and n[1:].isdigit() and n in M.KEYS:
        return n
    if n.startswith("KP_") and n[3:].isdigit():
        return n[3:]
    return None


ACTIONS = [
    ("Clique esquerdo", {"kind": "mouse", "value": 1}), ("Clique direito", {"kind": "mouse", "value": 2}),
    ("Clique do meio", {"kind": "mouse", "value": 4}), ("Voltar", {"kind": "mouse", "value": 8}),
    ("Avançar", {"kind": "mouse", "value": 0x10}), ("Alternar DPI", {"kind": "function", "value": 5}),
    ("DPI +", {"kind": "function", "value": 3}), ("DPI −", {"kind": "function", "value": 4}),
    ("Segurar para DPI baixo", {"kind": "function", "value": 7}),
    ("Mídia: tocar/pausar", {"kind": "consumer", "value": 0xCD}), ("Mídia: próxima", {"kind": "consumer", "value": 0xB5}),
    ("Mídia: anterior", {"kind": "consumer", "value": 0xB6}), ("Mídia: volume +", {"kind": "consumer", "value": 0xE9}),
    ("Mídia: volume −", {"kind": "consumer", "value": 0xEA}), ("Mídia: mudo", {"kind": "consumer", "value": 0xE2}),
    ("Desativado", {"kind": "none"}),
]
MODES = [("once", "Roda uma vez"), ("hold", "Repete enquanto segura"), ("toggle", "Liga/desliga repetição")]


def same_action(a, b):
    return a.get("kind") == b.get("kind") and a.get("value") == b.get("value") and \
        int(a.get("mods", 0) or 0) == int(b.get("mods", 0) or 0)


# --------------------------------------------------------------------------
# Aplicativo
# --------------------------------------------------------------------------
class LogiApp(Adw.Application):
    def __init__(self, demo=False):
        super().__init__(application_id=APP_ID + (".Demo" if demo else ""),
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.demo = demo
        self.win = None
        self.connect("activate", self._activate)

    def _activate(self, _app):
        if self.win:
            self.win.present()
            return
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        prov = Gtk.CssProvider()
        if hasattr(prov, "load_from_string"):
            prov.load_from_string(CSS)
        else:
            prov.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.add_search_path(ASSETS)
        self.win = MainWindow(self, self.demo)
        self.win.present()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, demo):
        super().__init__(application=app, title=APP_NAME)
        self.demo = demo
        self.add_css_class("lm")
        self.set_default_size(1240, 820)
        self.set_size_request(760, 560)
        self.set_icon_name("logimouse")
        self.worker = Worker()
        self.audio_worker = Worker()
        self.mice, self.heads, self.states, self.problems = [], [], {}, []
        self.cur = None
        self.section = None
        self.work = None
        self.dirty = False
        self.sel_level = 0
        self.sel_button = 0
        self.sel_macro = 0
        self.macro_edit = None
        self.recording = False
        self.rec_last = None
        self.rec_down = set()
        self._audio_timer = None
        self._busy = False

        self.toast = Adw.ToastOverlay()
        root = vbox(0)
        self.toast.set_child(root)
        self.set_content(self.toast)

        hb = Adw.HeaderBar()
        hb.add_css_class("lm-header")
        self.back = button("", "flat", cb=self.go_home)
        self.back.set_icon_name("go-previous-symbolic")
        self.back.set_tooltip_text("Voltar ao início")
        self.back.set_visible(False)
        hb.pack_start(self.back)
        title = hbox(10)
        logo = Gtk.Image.new_from_file(LOGO)
        logo.set_pixel_size(34)
        title.append(logo)
        title.append(lab("LOGI<span foreground='#c084fc'>MOUSE</span>", "lm-wordmark", markup=True))
        self.crumb = lab("", "lm-crumb")
        title.append(self.crumb)
        hb.set_title_widget(title)
        hb.pack_end(self._app_menu())
        refresh = button("", "flat", cb=self.scan)
        refresh.set_icon_name("view-refresh-symbolic")
        refresh.set_tooltip_text("Procurar e ler de novo (Ctrl+R)")
        hb.pack_end(refresh)
        self.prof_box = hbox(8)
        self.prof_box.append(lab("Perfil", "lm-muted"))
        self.prof_drop = Gtk.DropDown.new_from_strings([])
        self.prof_drop.set_tooltip_text("Perfil gravado no mouse")
        self._prof_sig = self.prof_drop.connect("notify::selected", self._prof_dropped)
        self.prof_box.append(self.prof_drop)
        self.prof_box.set_visible(False)
        hb.pack_end(self.prof_box)
        root.append(hb)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        self.home = vbox(0)
        self.stack.add_named(self.home, "home")
        self.page = hbox(0)
        self.stack.add_named(self.page, "device")
        root.append(self.stack)

        foot = hbox(12, "lm-footer")
        self.status = lab("", "lm-small")
        self.status.set_hexpand(True)
        foot.append(self.status)
        foot.append(lab(f"{APP_NAME} {__version__}" + (" · demonstração" if demo else ""), "lm-small"))
        root.append(foot)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key_pressed)
        keys.connect("key-released", self._key_released)
        self.add_controller(keys)

        GLib.timeout_add(150, lambda: self.scan() and False)
        GLib.timeout_add_seconds(60, self._auto_battery)

    # ---- mensagens ----
    def say(self, text):
        self.status.set_text(text)

    def toast_msg(self, text):
        self.toast.add_toast(Adw.Toast(title=text, timeout=4))
        self.say(text)

    # ---- menu do app ----
    def _app_menu(self):
        mb = Gtk.MenuButton(icon_name="emblem-system-symbolic", tooltip_text="Opções do aplicativo")
        pop = Gtk.Popover()
        box = vbox(12)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_size_request(320, -1)
        box.append(lab("Aplicativo", "lm-h2"))
        r, _ = switch_row("Iniciar com o sistema", config.autostart_enabled(), self._autostart,
                          "Ícone na barra, macros, troca de perfil e ajustes reaplicados")
        box.append(r)
        r, _ = switch_row("Atualizar sozinho", config.get_option("auto_update"),
                          lambda v: config.set_option("auto_update", v), "Procura versão nova no GitHub uma vez por dia")
        box.append(r)
        r, _ = switch_row("Avisar com bateria baixa", config.get_option("notify_low"),
                          lambda v: config.set_option("notify_low", v))
        box.append(r)
        box.append(button("Procurar atualização agora", "lm-ghost", cb=self._check_update))
        box.append(lab(f"{APP_NAME} {__version__}", "lm-small"))
        pop.set_child(box)
        mb.set_popover(pop)
        return mb

    def _autostart(self, on):
        if self.demo:
            self.say("No modo demonstração nada é alterado.")
            return
        config.set_autostart(on)
        if on and not config.tray_running():
            self._start_tray()
        self.say("Início com o sistema " + ("ligado." if on else "desligado."))

    def _start_tray(self):
        args = ["--tray"] + (["--demo"] if self.demo else [])
        try:
            subprocess.Popen(config.launcher_command(*args), env=config.launcher_env(), start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.say(f"Não deu para iniciar o ícone: {e}")

    def _check_update(self):
        if self.demo:
            self.say("No modo demonstração não há atualização.")
            return
        self.say("Procurando atualização no GitHub...")

        def done(info):
            if not info["latest"]:
                self.say("Nenhuma versão publicada no GitHub ainda.")
            elif not info["newer"]:
                self.say(f"Você já está na versão mais nova ({info['current']}).")
            elif not U.can_self_update():
                self.say(f"A versão {info['latest']} está no GitHub ({U.why_not_self_update()}).")
            else:
                self.confirm("Atualização disponível",
                             f"A versão {info['latest']} está disponível (você está na {info['current']}). Instalar agora?",
                             "Instalar", lambda: self._install(info))
        self.worker.submit(U.check, done, lambda e: self.say(f"Não deu para procurar atualização: {e}"))

    def _install(self, info):
        self.say("Baixando e instalando...")

        def ok(res):
            config.restart_tray()
            self.toast_msg(f"Atualizado para {res['version']}. Feche e abra o painel."
                           + (" Rode o instalar.sh de novo (permissões mudaram)." if res["needs_installer"] else ""))
        self.worker.submit(lambda: U.install(info["ref"], info["latest"]), ok,
                           lambda e: self.say(f"A atualização falhou: {e}. Nada foi alterado."))

    def confirm(self, heading, body, yes, on_yes, danger=False):
        d = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
        d.add_response("cancel", "Cancelar")
        d.add_response("ok", yes)
        d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if danger else Adw.ResponseAppearance.SUGGESTED)
        d.connect("response", lambda _d, r: r == "ok" and on_yes())
        d.present()

    def ask_text(self, heading, body, initial, on_ok):
        d = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
        e = Gtk.Entry(text=initial or "")
        d.set_extra_child(e)
        d.add_response("cancel", "Cancelar")
        d.add_response("ok", "Salvar")
        d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        d.connect("response", lambda _d, r: r == "ok" and on_ok(e.get_text()))
        d.present()

    # ---- procurar dispositivos ----
    def scan(self):
        if self._busy:
            return False
        self._busy = True
        self.say("Procurando mouse e headset...")
        if self.demo:
            from . import demo as D
            mice_fn, heads_fn = D.discover_demo, D.discover_demo_headsets
        else:
            mice_fn, heads_fn = H.discover, HS.discover
        demo = self.demo

        def job():
            mice, problems = mice_fn()
            try:
                heads, hp = heads_fn()
            except Exception as e:  # noqa: BLE001 - o headset nunca derruba o mouse
                heads, hp = [], [f"Headset: {e}"]
            if heads and not mice:
                problems = [p for p in problems if "Logitech" not in p]
            mice = [m for m in mice if m.is_pointer] or mice
            states = {}
            for m in mice:
                states[id(m)] = load_mouse(m)
            for h in heads:
                states[id(h)] = load_headset(h, demo)
            return mice, heads, states, problems + hp
        self.worker.submit(job, self._scanned, self._scan_failed)
        return False

    def _scanned(self, res):
        self._busy = False
        old = self.mice + self.heads
        cur_name = self.cur.name if self.cur else None
        self.mice, self.heads, self.states, self.problems = res
        closed = set()
        for d in old:
            if d in self.mice or d in self.heads:
                continue
            t = getattr(d, "t", None)
            if t is not None and id(t) not in closed and not any(getattr(x, "t", None) is t for x in self.mice):
                closed.add(id(t))
                try:
                    d.close() if getattr(d, "is_headset", False) else t.close()
                except OSError:
                    pass
        self.build_home()
        again = next((d for d in self.mice + self.heads if d.name == cur_name), None)
        if again is not None and self.stack.get_visible_child_name() == "device":
            self.open_device(again, keep_section=True)
        else:
            self.go_home()
        n = len(self.mice) + len(self.heads)
        self.say(" ".join(self.problems) if self.problems else f"{n} dispositivo(s) encontrado(s).")

    def _scan_failed(self, e):
        self._busy = False
        self.say(f"Erro ao procurar: {e}")

    def _auto_battery(self):
        devs = list(self.mice + self.heads)

        def job():
            out = {}
            for d in devs:
                try:
                    out[id(d)] = d.read_battery() if getattr(d, "is_headset", False) else H.read_battery(d)
                except (*H.DEVICE_ERRORS, HS.HeadsetError):
                    pass
            return out

        def ok(res):
            for k, b in res.items():
                if k in self.states and b:
                    self.states[k]["battery"] = b
            if self.stack.get_visible_child_name() == "home":
                self.build_home()
            elif self.cur is not None and id(self.cur) in res:
                self.side_ring.set(H.battery_value(res[id(self.cur)]), H.battery_text(res[id(self.cur)]))
        self.worker.submit(job, ok)
        return True

    # ---- inicio ----
    def go_home(self):
        self._stop_recording()
        self.cur = None
        self.back.set_visible(False)
        self.prof_box.set_visible(False)
        self.crumb.set_text("")
        self.build_home()
        self.stack.set_visible_child_name("home")

    def build_home(self):
        clear(self.home)
        box = vbox(26)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(36)
        box.append(lab("Seus dispositivos", "lm-title"))
        devs = self.mice + self.heads
        if not devs:
            box.append(lab("Nenhum mouse ou headset encontrado.", "lm-h2"))
            box.append(lab("\n".join(self.problems) or "Conecte o receptor e clique em atualizar.", "lm-muted", wrap=True))
        else:
            box.append(lab(f"{len(devs)} conectado(s) · seus ajustes voltam sozinhos quando eles religam", "lm-muted"))
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2, min_children_per_line=1,
                           column_spacing=22, row_spacing=22, homogeneous=True)
        for d in devs:
            grid.append(self._dev_card(d))
        box.append(grid)
        chips = hbox(14)
        rules = [r for m in self.mice for r in P.device_data(m.name)["rules"]]
        if rules:
            chips.append(self._chip_card("Troca automática de perfil",
                                         f"{len(rules)} regra(s) · {rules[0]['match']} → {rules[0]['profile']}",
                                         "ATIVA" if config.tray_running() or self.demo else "BANDEJA FECHADA"))
        if self.heads:
            a = AU.settings()
            if a.get("nr"):
                chips.append(self._chip_card("Microfone sem ruído", f"“{a.get('label') or 'Headset'} · sem ruído”",
                                             "IA LIGADA", purple=True))
        if chips.get_first_child():
            box.append(chips)
        self.home.append(scroll(box))

    def _chip_card(self, title, sub, tag, purple=False):
        c = hbox(12, "lm-card")
        c.set_hexpand(True)
        t = vbox(3)
        t.set_hexpand(True)
        t.append(lab(title, "lm-h2"))
        t.append(lab(sub, "lm-small"))
        c.append(t)
        c.append(lab(tag, "lm-tag", *(["purple"] if purple else []), xalign=1))
        return c

    def _dev_card(self, d):
        s = self.states.get(id(d), {})
        b = Gtk.Button()
        b.add_css_class("lm-devcard")
        inner = vbox(20)
        top = hbox(16)
        t = vbox(6)
        t.set_hexpand(True)
        is_h = getattr(d, "is_headset", False)
        t.append(lab("HEADSET" if is_h else "MOUSE", "lm-tag", *(["purple"] if is_h else [])))
        t.append(lab(d.name, "lm-name", wrap=True))
        t.append(lab(d.detail if is_h else f"{d.connection} · HID++ {d.protocol[0]}.{d.protocol[1]}", "lm-muted"))
        top.append(t)
        bat = s.get("battery")
        top.append(Ring(110, H.battery_value(bat) if bat else None, H.battery_text(bat) if bat else "—"))
        inner.append(top)
        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        for k, v in self._stats(d, s):
            st = vbox(4, "lm-stat")
            st.append(lab(k, "lm-small"))
            st.append(lab(v, "lm-stat-v"))
            stats.append(st)
        inner.append(stats)
        inner.append(lab("Abrir ajustes →", "lm-tag", *(["purple"] if is_h else [])))
        b.set_child(inner)
        b.connect("clicked", lambda *_: self.open_device(d))
        return b

    def _stats(self, d, s):
        if getattr(d, "is_headset", False):
            a = AU.settings()
            return [("EQ", a["preset"] if a.get("eq_on") else "Desligado"), ("SURROUND", "7.1" if a.get("surround") else "Não"),
                    ("MIC IA", "Ligado" if a.get("nr") and s.get("rnnoise") else "Desligado")]
        ob = s.get("onboard")
        if ob:
            p = ob["profile"]
            dp = p["dpis"][p["default_dpi"]] if p["dpis"] else "—"
            return [("DPI", str(dp)), ("TAXA", f"{p['rate']} Hz"), ("PERFIL", P.device_data(d.name)["active"])]
        dpi = s.get("dpi")
        rate = s.get("report_rate")
        return [("DPI", str(dpi[1]) if dpi else "—"), ("TAXA", f"{rate[1]} Hz" if rate and rate[1] else "—"),
                ("CONEXÃO", d.connection)]

    # ---- pagina do dispositivo ----
    def open_device(self, d, keep_section=False):
        self._stop_recording()
        if self.cur is not d:
            self.dirty = False
            self.work = None
        self.cur = d
        s = self.states.get(id(d), {})
        is_h = getattr(d, "is_headset", False)
        ob = None if is_h else s.get("onboard")
        if ob and (self.work is None or not keep_section):
            self.work = json_copy(ob["profile"])
            P.ensure_default(d.name, json_copy(ob["profile"]))
            self.sel_level = self.work["default_dpi"]
        if is_h:
            secs = [("sound", "Som"), ("mic", "Microfone"), ("general", "Geral")]
        elif ob:
            secs = [("perf", "Desempenho"), ("buttons", "Botões"), ("macros", "Macros"), ("profiles", "Perfis"),
                    ("test", "Teste")]
        else:
            secs = [("perf", "Desempenho"), ("test", "Teste")]
        if not keep_section or self.section not in dict(secs):
            self.section = secs[0][0]
        self.secs = secs
        self.back.set_visible(True)
        self.crumb.set_text(f"/  {d.name}")
        self._update_profile_drop()
        clear(self.page)
        side = vbox(4, "lm-side")
        side.set_size_request(236, -1)
        head = hbox(12)
        for m in ("top", "start", "end"):
            getattr(head, f"set_margin_{m}")(18)
        head.set_margin_bottom(14)
        bat = s.get("battery")
        self.side_ring = Ring(56, H.battery_value(bat) if bat else None, H.battery_text(bat) if bat else "—", sub=None)
        head.append(self.side_ring)
        ht = vbox(2)
        ht.append(lab(d.name, "lm-h2", wrap=True))
        ht.append(lab("Headset" if is_h else d.kind_name, "lm-small"))
        head.append(ht)
        side.append(head)
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        for key, text in secs:
            row = Gtk.ListBoxRow()
            row.set_child(lab(text))
            row.key = key
            lb.append(row)
            if key == self.section:
                lb.select_row(row)
        lb.connect("row-selected", lambda _l, row: row and row.key != self.section and self.show_section(row.key))
        self.side_list = lb
        side.append(lb)
        self.page.append(side)
        self.content = vbox(0)
        self.content.set_hexpand(True)
        self.page.append(self.content)
        self.stack.set_visible_child_name("device")
        self.show_section(self.section)

    def show_section(self, key):
        if key != "macros":
            self._stop_recording()
        self.section = key
        row = self.side_list.get_first_child() if getattr(self, "side_list", None) else None
        while row is not None:
            if getattr(row, "key", None) == key and not row.is_selected():
                self.side_list.select_row(row)
            row = row.get_next_sibling()
        clear(self.content)
        body = vbox(18)
        for m in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{m}")(28)
        getattr(self, f"_sec_{key}")(body)
        self.content.append(scroll(body))

    def refresh_section(self):
        if self.cur is not None and self.section:
            self.show_section(self.section)

    @property
    def st(self):
        return self.states.get(id(self.cur), {})

    # ---- perfis no cabecalho ----
    def _update_profile_drop(self):
        d = self.cur
        ob = self.st.get("onboard") if d is not None and not getattr(d, "is_headset", False) else None
        self.prof_box.set_visible(bool(ob))
        if not ob:
            return
        data = P.device_data(d.name)
        names = list(data["profiles"].keys())
        self.prof_drop.handler_block(self._prof_sig)
        self.prof_drop.set_model(Gtk.StringList.new(names))
        if data["active"] in names:
            self.prof_drop.set_selected(names.index(data["active"]))
        self.prof_drop.handler_unblock(self._prof_sig)
        self._prof_names = names

    def _prof_dropped(self, drop, _p):
        i = drop.get_selected()
        names = getattr(self, "_prof_names", [])
        if 0 <= i < len(names):
            data = P.device_data(self.cur.name)
            if names[i] != data["active"]:
                self.activate_profile(names[i])

    # ======================================================================
    # MOUSE
    # ======================================================================
    def _save_bar(self, body):
        bar = hbox(12)
        self.dirty_lbl = lab("Alterações ainda não gravadas no mouse." if self.dirty else "Tudo gravado no mouse.",
                             "lm-warn" if self.dirty else "lm-small")
        self.dirty_lbl.set_hexpand(True)
        bar.append(self.dirty_lbl)
        bar.append(button("Desfazer", "lm-ghost", cb=self._undo))
        self.save_btn = button("Gravar no mouse", "lm-primary", cb=self.save_profile)
        self.save_btn.set_sensitive(self.dirty)
        bar.append(self.save_btn)
        body.append(bar)

    def _mark(self):
        self.dirty = True
        if getattr(self, "save_btn", None) is not None:
            self.save_btn.set_sensitive(True)
            self.dirty_lbl.set_text("Alterações ainda não gravadas no mouse.")
            self.dirty_lbl.remove_css_class("lm-small")
            self.dirty_lbl.add_css_class("lm-warn")

    def _undo(self):
        ob = self.st.get("onboard")
        if ob:
            self.work = json_copy(ob["profile"])
            self.dirty = False
            self.refresh_section()

    def save_profile(self, name=None, then=None):
        d, s = self.cur, self.st
        ob = s.get("onboard")
        if not ob:
            return
        work = json_copy(self.work)
        if not any(same_action(a, {"kind": "mouse", "value": 1}) for a in work["buttons"]):
            self.toast_msg("Algum botão precisa ser o clique esquerdo.")
            return
        name = name or P.device_data(d.name)["active"]
        self.say("Gravando no mouse...")

        def job():
            p = ob["ob"].read_profile()
            p.apply_dict(work)
            q = ob["ob"].write_profile(p)
            P.put_profile(d.name, name, q.to_dict(), activate=True)
            # na memoria do mouse, o DPI/taxa do computador nao valem mais
            config.remember(d.name, host_mode=False, dpi=None, report_rate=None)
            return q.to_dict(), ob["ob"].mode()

        def ok(res):
            ob["profile"], ob["mode"] = res
            self.work = json_copy(res[0])
            self.dirty = False
            self._update_profile_drop()
            self.refresh_section()
            self.toast_msg(f"Perfil “{name}” gravado no mouse.")
            if then:
                then()
        self.worker.submit(job, ok, lambda e: self.toast_msg(f"Não gravou: {e}. Mexa o mouse e tente de novo."))

    def activate_profile(self, name):
        d = self.cur
        data = P.device_data(d.name)
        prof = data["profiles"].get(name)
        if prof is None:
            return
        self.work = json_copy(prof)
        self.save_profile(name)

    # ---- Desempenho ----
    def _sec_perf(self, body):
        s = self.st
        ob = s.get("onboard")
        if ob:
            self._perf_onboard(body, s)
        else:
            self._perf_host(body, s)
        b = s.get("battery")
        c = card("Bateria")
        row = hbox(12)
        row.append(lab(H.battery_text(b) if b else "—", "lm-big"))
        row.append(lab((b or {}).get("status") or "não informada", "lm-muted"))
        c.append(row)
        lv = Gtk.LevelBar(min_value=0, max_value=100, value=H.battery_value(b) or 0 if b else 0)
        c.append(lv)
        body.append(c)

    def _dpi_range(self, s):
        dpi = s.get("dpi")
        if dpi and dpi[0]:
            return min(dpi[0]), max(dpi[0])
        return 100, 12000

    def _perf_onboard(self, body, s):
        w = self.work
        c = card()
        top = hbox(12)
        t = vbox(4)
        t.set_hexpand(True)
        t.append(lab("Níveis de DPI", "lm-h2"))
        t.append(lab("O botão de DPI do mouse alterna entre eles. Clique num nível para ajustar.", "lm-muted", wrap=True))
        top.append(t)
        self.dpi_big = lab(str(w["dpis"][self.sel_level]) if w["dpis"] else "—", "lm-big", xalign=1)
        top.append(self.dpi_big)
        top.append(lab("DPI", "lm-muted"))
        c.append(top)
        self.sel_level = min(self.sel_level, len(w["dpis"]) - 1)
        levels = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        first = None
        colors = ["#f97316", "#22d3ee", "#a855f7", "#ec4899", "#facc15"]
        self.level_lbls = []
        for i, v in enumerate(w["dpis"]):
            b = Gtk.ToggleButton()
            b.add_css_class("lm-level")
            inner = vbox(4)
            tag = "PADRÃO" if i == w["default_dpi"] else ("DPI BAIXO" if i == w["shift_dpi"] and self._has_shift() else f"NÍVEL {i + 1}")
            inner.append(lab(tag, "lm-small", xalign=0.5))
            vl = lab(str(v), "lm-level-v", xalign=0.5)
            self.level_lbls.append(vl)
            inner.append(vl)
            inner.append(lab(f"<span foreground='{colors[i]}'>━━</span>", xalign=0.5, markup=True))
            b.set_child(inner)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.set_active(i == self.sel_level)
            b.connect("toggled", lambda btn, i=i: btn.get_active() and self._pick_level(i))
            levels.append(b)
        if len(w["dpis"]) < 5:
            add = button("+ Nível", "lm-ghost", cb=self._add_level)
            levels.append(add)
        c.append(levels)
        lo, hi = self._dpi_range(s)
        row = hbox(14)
        row.append(lab(f"Nível {self.sel_level + 1}", "lm-muted"))
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 50)
        sc.set_hexpand(True)
        sc.set_draw_value(False)
        sc.set_value(w["dpis"][self.sel_level])
        sc.connect("value-changed", self._dpi_moved)
        row.append(sc)
        row.append(lab(f"{lo} – {hi}", "lm-small"))
        c.append(row)
        opts = hbox(10)
        opts.append(button("Usar ao ligar", "lm-ghost", cb=lambda: self._set_work("default_dpi", self.sel_level)))
        opts.append(button("Usar como DPI baixo", "lm-ghost", cb=lambda: self._set_work("shift_dpi", self.sel_level)))
        if len(w["dpis"]) > 1:
            opts.append(button("Remover nível", "lm-ghost", cb=self._remove_level))
        c.append(opts)
        c.append(lab("“DPI baixo” vale enquanto você segura um botão com a ação “Segurar para DPI baixo” (modo sniper).",
                     "lm-small", wrap=True))
        body.append(c)
        c = card("Taxa de atualização", "Mais alta responde mais rápido e gasta mais bateria.")
        c.append(pills([(r, f"{r} Hz") for r in sorted(O.RATES.values())], w["rate"],
                       lambda v: self._set_work("rate", v, rebuild=False), cyan=True))
        body.append(c)
        self._save_bar(body)

    def _has_shift(self):
        return any(same_action(a, {"kind": "function", "value": 7}) for a in self.work["buttons"])

    def _pick_level(self, i):
        self.sel_level = i
        self.refresh_section()

    def _dpi_moved(self, sc):
        v = int(round(sc.get_value() / 50) * 50)
        if self.work["dpis"][self.sel_level] != v:
            self.work["dpis"][self.sel_level] = v
            self.dpi_big.set_text(str(v))
            self.level_lbls[self.sel_level].set_text(str(v))
            self._mark()

    def _add_level(self):
        d = self.work["dpis"]
        d.append(min(self._dpi_range(self.st)[1], (d[-1] if d else 400) * 2))
        self.sel_level = len(d) - 1
        self._mark()
        self.refresh_section()

    def _remove_level(self):
        d = self.work["dpis"]
        if len(d) <= 1:
            return
        d.pop(self.sel_level)
        for k in ("default_dpi", "shift_dpi"):
            if self.work[k] >= len(d) or self.work[k] == self.sel_level:
                self.work[k] = 0
            elif self.work[k] > self.sel_level:
                self.work[k] -= 1
        self.sel_level = max(0, self.sel_level - 1)
        self._mark()
        self.refresh_section()

    def _set_work(self, key, value, rebuild=True):
        if self.work.get(key) != value:
            self.work[key] = value
            self._mark()
            if rebuild:
                self.refresh_section()

    def _perf_host(self, body, s):
        d = self.cur
        dpi = s.get("dpi")
        if dpi:
            choices, cur, _ = dpi
            c = card("DPI", "Aplicado na hora e reaplicado quando o mouse religa.")
            top = hbox(12)
            big = lab(str(cur), "lm-big")
            top.append(big)
            top.append(lab("DPI", "lm-muted"))
            c.append(top)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, min(choices), max(choices), 50)
            sc.set_draw_value(False)
            sc.set_value(cur)
            sc.connect("value-changed", lambda w: big.set_text(str(snap(w.get_value(), choices))))
            rel = Gtk.GestureClick()
            rel.connect("released", lambda *_: self._apply(lambda v=snap(sc.get_value(), choices): d.set_dpi(v),
                                                           "DPI", {"dpi": snap(sc.get_value(), choices)}))
            sc.add_controller(rel)
            c.append(sc)
            presets = [v for v in (400, 800, 1000, 1600, 3200) if min(choices) <= v <= max(choices)]
            c.append(pills([(v, str(v)) for v in presets], cur,
                           lambda v: self._apply(lambda: d.set_dpi(v), "DPI", {"dpi": v}, reload=True)))
            body.append(c)
        rate = s.get("report_rate")
        if rate and rate[0]:
            c = card("Taxa de atualização")
            c.append(pills([(r, f"{r} Hz") for r in rate[0]], rate[1],
                           lambda v: self._apply(lambda: d.set_report_rate(v), "Taxa", {"report_rate": v}), cyan=True))
            body.append(c)
        sp = s.get("pointer_speed")
        if sp is not None:
            c = card("Velocidade do ponteiro")
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0x2E, 0x1FF, 1)
            sc.set_draw_value(False)
            sc.set_value(sp)
            rel = Gtk.GestureClick()
            rel.connect("released", lambda *_: self._apply(lambda v=int(sc.get_value()): d.set_pointer_speed(v),
                                                           "Velocidade", {"pointer_speed": int(sc.get_value())}))
            sc.add_controller(rel)
            c.append(sc)
            body.append(c)
        ss, hw = s.get("smartshift"), s.get("hires")
        if ss or hw:
            c = card("Roda de rolagem")
            if ss:
                mode, thr = ss
                c.append(pills([(2, "Catraca"), (1, "Livre")], mode,
                               lambda v: self._apply(lambda: d.set_smartshift(v, thr), "Roda", {"smartshift": [v, thr]},
                                                     reload=True)))
                r, _ = switch_row("SmartShift", thr is not None,
                                  lambda on: self._apply(lambda: d.set_smartshift(2, 12 if on else None), "SmartShift",
                                                         {"smartshift": [2, 12 if on else None]}, reload=True),
                                  "Solta a roda sozinha quando você gira rápido")
                c.append(r)
            if hw:
                r, _ = switch_row("Rolagem em alta resolução", hw["hires"],
                                  lambda on: self._apply(lambda: d.set_hires_wheel(hires=on), "Alta resolução", {"hires": on}))
                c.append(r)
                if hw["can_invert"]:
                    r, _ = switch_row("Inverter direção", hw["invert"],
                                      lambda on: self._apply(lambda: d.set_hires_wheel(invert=on), "Inverter", {"invert": on}))
                    c.append(r)
            body.append(c)
        if not (dpi or rate or sp is not None or ss or hw):
            body.append(card("Este dispositivo não tem ajustes de desempenho.",
                             "Só a bateria é lida. Remapear teclas precisa da memória de perfis (mouses G)."))

    def _apply(self, fn, what, wanted, reload=False):
        d = self.cur
        self.say(f"Aplicando: {what}...")

        def ok(_res):
            if wanted:
                config.remember(d.name, **wanted)
            self.say(f"{what}: aplicado e salvo.")
            if reload:
                self.worker.submit(lambda: load_mouse(d), self._reloaded)

        def fail(e):
            if wanted and isinstance(e, (H.HidppTimeout, OSError)):
                config.remember(d.name, **wanted)
                self.say(f"{what}: o mouse não respondeu. Salvei e aplico quando ele reconectar.")
            else:
                self.say(f"{what}: não deu certo ({e}).")
        self.worker.submit(fn, ok, fail)

    def _reloaded(self, s):
        if self.cur is not None:
            self.states[id(self.cur)] = s
            self.refresh_section()

    # ---- Botoes ----
    def _sec_buttons(self, body):
        w = self.work
        n = len(w["buttons"])
        self.sel_button = min(self.sel_button, n - 1)
        row = hbox(18)
        left = card(None, None)
        left.set_valign(Gtk.Align.START)
        self.diagram = MouseDiagram(n, self._pick_button)
        self.diagram.sel = self.sel_button
        left.append(self.diagram)
        left.append(lab("Gravado na memória do mouse:\nvale em qualquer computador.", "lm-small", xalign=0.5))
        row.append(left)
        right = card(None, None)
        right.set_hexpand(True)
        macros = P.macros()
        self.btn_rows = []
        for i, a in enumerate(w["buttons"]):
            r = hbox(14, "lm-btnrow")
            if i == self.sel_button:
                r.add_css_class("sel")
            num = lab(str(i + 1), "lm-num", xalign=0.5)
            num.set_valign(Gtk.Align.CENTER)
            if i == self.sel_button:
                num.add_css_class("sel")
            r.append(num)
            t = vbox(2)
            t.set_hexpand(True)
            t.append(lab(O.BUTTON_NAMES[i] if i < len(O.BUTTON_NAMES) else f"Botão {i + 1}", "lm-h2"))
            t.append(lab(O.describe(a, macros), "lm-small"))
            r.append(t)
            r.append(self._action_drop(i, a, macros))
            click = Gtk.GestureClick()
            click.connect("pressed", lambda *_a, i=i: self._pick_button(i))
            r.add_controller(click)
            right.append(r)
            self.btn_rows.append((r, num))
        foot = hbox(12)
        foot.append(lab("O mouse precisa de pelo menos um clique esquerdo.", "lm-small"))
        right.append(foot)
        restore = button("Botões de fábrica", "lm-ghost", cb=self._factory_buttons)
        right.append(restore)
        row.append(right)
        body.append(row)
        self._save_bar(body)

    def _action_drop(self, i, a, macros):
        opts = [x for x in ACTIONS if not (i == 0 and x[1]["kind"] == "none")]
        for mi, m in enumerate(macros):
            if m:
                opts.append((f"Macro: {m.get('name') or mi + 1}", M.trigger_action(mi)))
        if not any(same_action(a, x[1]) for x in opts):
            opts.append((O.describe(a, macros), a))
        opts.append(("Tecla ou atalho…", None))
        drop = Gtk.DropDown.new_from_strings([x[0] for x in opts])
        drop.set_valign(Gtk.Align.CENTER)
        drop.set_size_request(240, -1)
        sel = next((k for k, x in enumerate(opts) if x[1] and same_action(a, x[1])), 0)
        drop.set_selected(sel)

        def changed(dd, _p):
            k = dd.get_selected()
            if k >= len(opts):
                return
            act = opts[k][1]
            if act is None:
                dd.set_selected(sel)
                self._capture_key(i)
                return
            if not same_action(act, self.work["buttons"][i]):
                self.work["buttons"][i] = dict(act)
                self._mark()
                self.sel_button = i
                GLib.idle_add(lambda: self.refresh_section() and False)
        drop.connect("notify::selected", changed)
        return drop

    def _pick_button(self, i):
        self.sel_button = i
        self.diagram.sel = i
        self.diagram.queue_draw()
        for k, (r, num) in enumerate(self.btn_rows):
            for wdg in (r, num):
                (wdg.add_css_class if k == i else wdg.remove_css_class)("sel")

    def _capture_key(self, i):
        d = Adw.MessageDialog(transient_for=self, heading=f"Tecla para o botão {i + 1}",
                              body="Aperte a tecla ou o atalho (por exemplo Ctrl+C). Ela fica gravada no mouse.")
        shown = lab("…", "lm-name", xalign=0.5)
        d.set_extra_child(shown)
        d.add_response("cancel", "Cancelar")
        d.add_response("ok", "Usar")
        d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        d.set_response_enabled("ok", False)
        got = {}
        kc = Gtk.EventControllerKey()
        kc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def pressed(_c, keyval, _code, state):
            n = key_name(keyval)
            if n is None or n in M.MODS:
                return True
            names = [m for m, flag in (("Ctrl", Gdk.ModifierType.CONTROL_MASK), ("Shift", Gdk.ModifierType.SHIFT_MASK),
                                       ("Alt", Gdk.ModifierType.ALT_MASK), ("Super", Gdk.ModifierType.SUPER_MASK))
                     if state & flag] + [n]
            try:
                got["a"] = M.key_action(names)
            except ValueError:
                return True
            shown.set_text(M.combo_text(got["a"]["mods"], got["a"]["value"]))
            d.set_response_enabled("ok", True)
            return True
        kc.connect("key-pressed", pressed)
        d.add_controller(kc)

        def resp(_d, r):
            if r == "ok" and "a" in got:
                self.work["buttons"][i] = got["a"]
                self._mark()
                self.refresh_section()
        d.connect("response", resp)
        d.present()

    def _factory_buttons(self):
        ob = self.st["onboard"]["ob"]

        def ok(fp):
            self.work["buttons"] = fp.to_dict()["buttons"]
            self._mark()
            self.refresh_section()
        self.worker.submit(ob.factory_profile, ok, lambda e: self.say(f"Não deu para ler o padrão: {e}"))

    # ---- Macros ----
    def _sec_macros(self, body):
        items = P.macros()
        if self.macro_edit is None:
            self.sel_macro = min(self.sel_macro, max(0, len(items) - 1))
            self.macro_edit = json_copy(items[self.sel_macro]) if items else None
        row = hbox(18)
        left = card(None, None)
        left.set_size_request(270, -1)
        left.set_valign(Gtk.Align.START)
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        lb.add_css_class("lm-side")
        for i, m in enumerate(items):
            r = Gtk.ListBoxRow()
            t = vbox(2)
            t.append(lab(m.get("name") or f"Macro {i + 1}", "lm-h2"))
            used = [k + 1 for k, a in enumerate(self.work["buttons"]) if same_action(a, M.trigger_action(i))]
            t.append(lab(f"{len(m.get('steps') or [])} passos · " + (f"botão {used[0]}" if used else "sem botão"), "lm-small"))
            r.set_child(t)
            lb.append(r)
            if i == self.sel_macro:
                lb.select_row(r)
        lb.connect("row-selected", lambda _l, r: r and self._pick_macro(r.get_index()))
        left.append(lb)
        if len(items) < M.TRIGGERS:
            left.append(button("+ Nova macro", "lm-ghost", cb=self._new_macro))
        row.append(left)
        right = card(None, None)
        right.set_hexpand(True)
        m = self.macro_edit
        if m is None:
            right.append(lab("Nenhuma macro ainda", "lm-h2"))
            right.append(lab("Crie uma macro, grave as teclas e depois escolha-a num botão em “Botões”.", "lm-muted", wrap=True))
        else:
            name = Gtk.Entry(text=m.get("name", ""))
            name.set_placeholder_text("Nome da macro")
            name.connect("changed", lambda e: m.__setitem__("name", e.get_text()))
            right.append(name)
            ctl = hbox(10)
            self.rec_btn = Gtk.ToggleButton(label="● Parar gravação" if self.recording else "● Gravar teclas")
            self.rec_btn.add_css_class("lm-pill")
            self.rec_btn.add_css_class("lm-rec")
            self.rec_btn.set_active(self.recording)
            self.rec_btn.connect("toggled", lambda b: self._toggle_recording(b.get_active()))
            ctl.append(self.rec_btn)
            self.rec_waits = Gtk.CheckButton(label="Gravar as esperas", active=m.get("waits", True))
            self.rec_waits.connect("toggled", lambda c: m.__setitem__("waits", c.get_active()))
            ctl.append(self.rec_waits)
            sp = hbox(0)
            sp.set_hexpand(True)
            ctl.append(sp)
            ctl.append(lab("Ao apertar", "lm-muted"))
            mode = Gtk.DropDown.new_from_strings([t for _, t in MODES])
            mode.set_selected([k for k, _ in MODES].index(m.get("mode", "once")))
            mode.connect("notify::selected", lambda dd, _p: m.__setitem__("mode", MODES[dd.get_selected()][0]))
            ctl.append(mode)
            right.append(ctl)
            self.steps_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8,
                                         max_children_per_line=30)
            frame = vbox(0, "lm-stat")
            frame.set_size_request(-1, 110)
            frame.append(self.steps_box)
            right.append(frame)
            self._draw_steps()
            right.append(lab("Durante a gravação, as teclas que você apertar entram na macro (não vão para outros programas).",
                             "lm-small", wrap=True))
            acts = hbox(10)
            acts.append(button("Limpar passos", "lm-ghost", cb=self._clear_steps))
            acts.append(button("Apagar macro", "lm-ghost danger", cb=self._delete_macro))
            sp = hbox(0)
            sp.set_hexpand(True)
            acts.append(sp)
            acts.append(button("Salvar macro", "lm-primary", cb=self._save_macro))
            right.append(acts)
            if not self.demo and not config.tray_running():
                right.append(lab("A macro roda pelo ícone do LogiMouse na barra: ligue “Iniciar com o sistema” "
                                 "nas opções (engrenagem).", "lm-warn", wrap=True))
        row.append(right)
        body.append(row)

    def _draw_steps(self):
        clear(self.steps_box)
        steps = (self.macro_edit or {}).get("steps") or []
        if not steps:
            self.steps_box.append(lab("Sem passos. Clique em “Gravar teclas”.", "lm-small"))
        for s in steps:
            self.steps_box.append(lab(M.step_text(s), "lm-chip", s.get("t", "wait")))

    def _pick_macro(self, i):
        if i == self.sel_macro and self.macro_edit is not None:
            return
        self._stop_recording()
        self.sel_macro = i
        items = P.macros()
        self.macro_edit = json_copy(items[i]) if i < len(items) else None
        GLib.idle_add(lambda: self.refresh_section() and False)

    def _new_macro(self):
        items = P.macros()
        items.append({"name": f"Macro {len(items) + 1}", "mode": "once", "steps": []})
        P.save_macros(items)
        self.sel_macro = len(items) - 1
        self.macro_edit = json_copy(items[-1])
        self.refresh_section()

    def _save_macro(self):
        self._stop_recording()
        items = P.macros()
        m = self.macro_edit
        try:
            M.validate(m)
            items[self.sel_macro] = m
            P.save_macros(items)
        except (ValueError, IndexError) as e:
            self.toast_msg(f"Macro não salva: {e}")
            return
        self.toast_msg(f"Macro “{m.get('name')}” salva. Escolha-a num botão em “Botões”.")
        self.refresh_section()

    def _delete_macro(self):
        def go():
            self._stop_recording()
            items = P.macros()
            if self.sel_macro < len(items):
                # a posicao da macro e a tecla que o mouse manda: deixa o lugar vazio
                items[self.sel_macro] = None if self.sel_macro < len(items) - 1 else items.pop() and None
                while items and items[-1] is None:
                    items.pop()
                P.save_macros(items)
            self.macro_edit = None
            self.sel_macro = 0
            self.refresh_section()
        self.confirm("Apagar macro?", "Botões que usam esta macro deixam de fazer algo até você escolher outra ação.",
                     "Apagar", go, danger=True)

    def _clear_steps(self):
        if self.macro_edit:
            self.macro_edit["steps"] = []
            self._draw_steps()

    def _toggle_recording(self, on):
        self.recording = on
        self.rec_last = None
        self.rec_down = set()
        if getattr(self, "rec_btn", None):
            self.rec_btn.set_label("● Parar gravação" if on else "● Gravar teclas")
        self.say("Gravando: aperte as teclas da macro." if on else "")

    def _stop_recording(self):
        if self.recording:
            self.recording = False
            if getattr(self, "rec_btn", None):
                try:
                    self.rec_btn.set_active(False)
                except Exception:  # noqa: BLE001 - botao ja destruido
                    pass

    def _rec_step(self, t, keyval):
        n = key_name(keyval)
        if n is None or self.macro_edit is None:
            return
        if t == "down":
            if n in self.rec_down:
                return  # repeticao automatica
            self.rec_down.add(n)
        else:
            self.rec_down.discard(n)
        now = GLib.get_monotonic_time() // 1000
        steps = self.macro_edit.setdefault("steps", [])
        if self.macro_edit.get("waits", True) and self.rec_last is not None:
            ms = int(min(10000, now - self.rec_last))
            if ms >= 10:
                steps.append({"t": "wait", "ms": ms})
        self.rec_last = now
        steps.append({"t": t, "k": n})
        self._draw_steps()

    def _key_pressed(self, _c, keyval, _code, state):
        if self.recording:
            self._rec_step("down", keyval)
            return True
        if state & Gdk.ModifierType.CONTROL_MASK and Gdk.keyval_to_lower(keyval) == Gdk.KEY_r:
            self.scan()
            return True
        return False

    def _key_released(self, _c, keyval, _code, _state):
        if self.recording:
            self._rec_step("up", keyval)
            return True
        return False

    # ---- Perfis ----
    def _sec_profiles(self, body):
        d = self.cur
        data = P.device_data(d.name)
        ob = self.st["onboard"]
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, min_children_per_line=1,
                           column_spacing=14, row_spacing=14, homogeneous=True)
        for name, p in data["profiles"].items():
            b = Gtk.Button()
            b.add_css_class("lm-devcard")
            inner = vbox(8)
            top = hbox(8)
            nm = lab(name, "lm-name")
            nm.set_hexpand(True)
            top.append(nm)
            if name == data["active"]:
                top.append(lab("NO MOUSE", "lm-badge"))
            inner.append(top)
            dp = p.get("dpis") or []
            inner.append(lab(f"{dp[p.get('default_dpi', 0)] if dp else '—'} DPI · {p.get('rate', '—')} Hz", "lm-muted"))
            apps = [r["match"] for r in data["rules"] if r["profile"] == name]
            inner.append(lab("Abre com: " + ", ".join(apps) if apps else
                             ("Usado quando nenhum programa da lista está aberto" if name == P.DEFAULT_NAME else "Só manual"),
                             "lm-small", wrap=True))
            b.set_child(inner)
            b.connect("clicked", lambda *_a, n=name: self._profile_clicked(n))
            grid.append(b)
        body.append(grid)
        acts = hbox(10)
        acts.append(button("Salvar ajustes atuais como novo perfil…", "lm-ghost", cb=self._new_profile))
        if data["active"] != P.DEFAULT_NAME:
            acts.append(button(f"Apagar “{data['active']}”", "lm-ghost danger",
                               cb=lambda: self.confirm("Apagar perfil?", f"O perfil “{data['active']}” sai do computador. "
                                                       "O mouse volta para o Padrão.", "Apagar",
                                                       lambda: self._delete_profile(data["active"]), danger=True)))
        body.append(acts)

        c = card("Trocar sozinho por programa",
                 "Quando um destes programas estiver aberto, o LogiMouse grava o perfil dele no mouse. "
                 "Ao fechar, volta para “Padrão”. (Funciona com a bandeja ligada.)")
        names = list(data["profiles"].keys())
        for k, r in enumerate(data["rules"]):
            row = hbox(12, "lm-stat")
            t = lab(r["match"], "lm-h2")
            t.set_hexpand(True)
            row.append(t)
            row.append(lab("usa", "lm-muted"))
            dd = Gtk.DropDown.new_from_strings(names)
            if r["profile"] in names:
                dd.set_selected(names.index(r["profile"]))
            dd.connect("notify::selected", lambda w, _p, k=k: self._rule_profile(k, names[w.get_selected()]))
            row.append(dd)
            rm = button("", "lm-ghost", cb=lambda k=k: self._rule_remove(k))
            rm.set_icon_name("user-trash-symbolic")
            rm.set_tooltip_text("Remover regra")
            row.append(rm)
            c.append(row)
        add = hbox(10)
        self.rule_entry = Gtk.Entry(placeholder_text="nome do programa (ex.: valorant, code, steam)")
        self.rule_entry.set_hexpand(True)
        add.append(self.rule_entry)
        pick = Gtk.MenuButton(label="Escolher programa aberto")
        pick.add_css_class("lm-ghost")
        pop = Gtk.Popover()
        plist = Gtk.ListBox()
        for prog in P.program_choices()[:60]:
            r = Gtk.ListBoxRow()
            r.set_child(lab(prog))
            r.prog = prog
            plist.append(r)
        plist.connect("row-activated", lambda _l, r: (self.rule_entry.set_text(r.prog), pop.popdown()))
        pop.set_child(scroll(plist))
        pop.set_size_request(280, 320)
        pick.set_popover(pop)
        add.append(pick)
        self.rule_prof = Gtk.DropDown.new_from_strings([n for n in names if n != P.DEFAULT_NAME] or names)
        add.append(self.rule_prof)
        add.append(button("Adicionar", "lm-primary", cb=self._rule_add))
        c.append(add)
        body.append(c)

        c = card("Quem manda nos ajustes")
        c.append(pills([(O.MODE_ONBOARD, "Memória do mouse (recomendado)"), (O.MODE_HOST, "Este computador")],
                       ob["mode"], self._set_mode))
        c.append(lab("Na memória do mouse, DPI, taxa e botões valem em qualquer PC, mesmo sem o LogiMouse. "
                     "Em “este computador”, os botões voltam ao padrão de fábrica.", "lm-small", wrap=True))
        body.append(c)
        c = card("Voltar ao padrão de fábrica",
                 "Copia o perfil original guardado no mouse por cima do perfil gravado. "
                 "Antes, o LogiMouse guarda uma cópia em ~/.config/logimouse/backups.", "dashed")
        c.append(button("Restaurar fábrica", "lm-ghost danger",
                        cb=lambda: self.confirm("Restaurar o mouse?", "DPI, taxa e botões voltam ao padrão de fábrica.",
                                                "Restaurar", self._factory, danger=True)))
        body.append(c)

    def _profile_clicked(self, name):
        if self.dirty:
            self.confirm("Trocar de perfil?", "Há alterações não gravadas no perfil atual. Elas serão perdidas.",
                         "Trocar", lambda: self.activate_profile(name))
        else:
            self.activate_profile(name)

    def _new_profile(self):
        def ok(name):
            name = name.strip()
            if not name:
                return
            data = P.device_data(self.cur.name)
            if name in data["profiles"]:
                self.toast_msg("Já existe um perfil com esse nome.")
                return
            P.put_profile(self.cur.name, name, json_copy(self.work))
            self.save_profile(name)
        self.ask_text("Novo perfil", "Os ajustes de agora (DPI, taxa e botões) viram um perfil novo, gravado no mouse.",
                      "", ok)

    def _delete_profile(self, name):
        P.delete_profile(self.cur.name, name)
        self.activate_profile(P.DEFAULT_NAME)

    def _rule_add(self):
        txt = self.rule_entry.get_text().strip().lower()
        model = self.rule_prof.get_model()
        prof = model.get_string(self.rule_prof.get_selected()) if model and model.get_n_items() else None
        if not txt or not prof:
            self.toast_msg("Escreva o nome do programa e escolha o perfil.")
            return
        data = P.device_data(self.cur.name)
        P.set_rules(self.cur.name, data["rules"] + [{"match": txt, "profile": prof}])
        self.refresh_section()

    def _rule_remove(self, k):
        data = P.device_data(self.cur.name)
        rules = data["rules"]
        if k < len(rules):
            rules.pop(k)
        P.set_rules(self.cur.name, rules)
        self.refresh_section()

    def _rule_profile(self, k, prof):
        data = P.device_data(self.cur.name)
        if k < len(data["rules"]):
            data["rules"][k]["profile"] = prof
            P.set_rules(self.cur.name, data["rules"])

    def _set_mode(self, mode):
        ob = self.st["onboard"]
        if ob["mode"] == mode:
            return
        d = self.cur

        def job():
            ob["ob"].set_mode(mode)
            config.remember(d.name, host_mode=mode == O.MODE_HOST)
            return ob["ob"].mode()

        def ok(m):
            ob["mode"] = m
            self.say("O mouse agora usa " + ("a memória dele." if m == O.MODE_ONBOARD else "os ajustes deste computador."))
        self.worker.submit(job, ok, lambda e: self.say(f"Não deu para trocar: {e}"))

    def _factory(self):
        ob = self.st["onboard"]

        def ok(p):
            ob["profile"] = p.to_dict()
            self.work = json_copy(ob["profile"])
            self.dirty = False
            P.put_profile(self.cur.name, P.device_data(self.cur.name)["active"], json_copy(ob["profile"]))
            self.refresh_section()
            self.toast_msg("Mouse restaurado para o padrão de fábrica.")
        self.worker.submit(ob["ob"].restore_factory, ok, lambda e: self.toast_msg(f"Não restaurou: {e}"))

    # ---- Teste ----
    def _sec_test(self, body):
        self.test = dict(clicks=0, doubles=0, scroll=0, moves=0)
        pad = vbox(10, "lm-testpad")
        pad.set_size_request(-1, 320)
        pad.set_valign(Gtk.Align.FILL)
        inner = vbox(8)
        inner.set_valign(Gtk.Align.CENTER)
        inner.set_vexpand(True)
        inner.append(lab("ÚLTIMO BOTÃO", "lm-tag", xalign=0.5))
        self.test_last = lab("—", "lm-testv", xalign=0.5)
        inner.append(self.test_last)
        inner.append(lab("Clique com qualquer botão, role a roda e mova o mouse aqui dentro.", "lm-muted", xalign=0.5))
        pad.append(inner)
        names = {1: "Esquerdo", 2: "Meio (roda)", 3: "Direito", 8: "Lateral de trás", 9: "Lateral da frente"}
        g = Gtk.GestureClick(button=0)

        def pressed(gest, n, _x, _y):
            b = gest.get_current_button()
            self.test["clicks"] += 1
            if n >= 2:
                self.test["doubles"] += 1
            self.test_last.set_text(names.get(b, f"Botão {b}") + (" (duplo)" if n == 2 else ""))
            self._test_stats()
        g.connect("pressed", pressed)
        pad.add_controller(g)
        mot = Gtk.EventControllerMotion()

        def moved(*_a):
            self.test["moves"] += 1
            if self.test["moves"] % 10 == 0:
                self._test_stats()
        mot.connect("motion", moved)
        pad.add_controller(mot)
        scr = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)

        def scrolled(_c, dx, dy):
            self.test["scroll"] += 1
            self.test_last.set_text("Roda ↑" if dy < 0 else "Roda ↓" if dy > 0 else ("Roda ←" if dx < 0 else "Roda →"))
            self._test_stats()
            return True
        scr.connect("scroll", scrolled)
        pad.add_controller(scr)
        body.append(pad)
        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14, homogeneous=True)
        self.test_lbls = {}
        for key, title in (("clicks", "CLIQUES"), ("doubles", "DUPLOS CLIQUES"), ("scroll", "ROLAGENS"), ("moves", "MOVIMENTOS")):
            c = vbox(6, "lm-card")
            c.append(lab(title, "lm-small"))
            v = lab("0", "lm-big")
            self.test_lbls[key] = v
            c.append(v)
            stats.append(c)
        body.append(stats)
        body.append(lab("Duplo clique sem querer em um clique só pode ser desgaste do botão.", "lm-small"))

    def _test_stats(self):
        for k, v in self.test_lbls.items():
            v.set_text(str(self.test[k]))

    # ======================================================================
    # HEADSET
    # ======================================================================
    def audio_change(self, rebuild=False, **kw):
        AU.save_settings(**kw)
        if self._audio_timer:
            GLib.source_remove(self._audio_timer)
        self._audio_timer = GLib.timeout_add(700, self._audio_apply)
        if rebuild:
            self.refresh_section()

    def _audio_apply(self):
        self._audio_timer = None
        self.say("Aplicando som...")

        def ok(notes):
            self.say(" · ".join(notes) if notes else "Som aplicado.")
            st = self.st
            st["running"] = AU.service_running() if not self.demo else False
        self.audio_worker.submit(AU.apply, ok, lambda e: self.say(f"Som: {e}"))
        return False

    def _sec_sound(self, body):
        a = AU.settings()
        s = self.st
        c = card()
        top = hbox(12)
        t = vbox(4)
        t.set_hexpand(True)
        t.append(lab("Equalizador", "lm-h2"))
        t.append(lab("Arraste os pontos para desenhar a curva, ou escolha uma predefinição.", "lm-muted"))
        top.append(t)
        sw = Gtk.Switch(active=a["eq_on"], valign=Gtk.Align.CENTER)
        sw.connect("notify::active", lambda w, _p: self.audio_change(eq_on=w.get_active()))
        top.append(lab("Ligado", "lm-muted"))
        top.append(sw)
        c.append(top)
        names = list(AU.PRESETS) + ["Personalizado"]
        c.append(pills([(n, n) for n in names], a["preset"] if a["preset"] in names else "Personalizado", self._preset))
        self.eq_vals = []
        self.eq = EqCurve(a["gains"], self._eq_drag, lambda g: self.audio_change(gains=g, preset=self._preset_of(g)))
        c.append(self.eq)
        lbls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True)
        for i, f in enumerate(AU.FREQ_LABELS):
            b = vbox(2)
            v = lab(gain_text(a["gains"][i]), "lm-h2", xalign=0.5)
            self.eq_vals.append(v)
            b.append(v)
            b.append(lab(f"{f} Hz", "lm-small", xalign=0.5))
            lbls.append(b)
        c.append(lbls)
        body.append(c)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18, homogeneous=True)
        c = card()
        r, _ = switch_row("Surround virtual 7.1", a["surround"], lambda v: self.audio_change(surround=v),
                          "Simula 8 caixas em volta da cabeça para ouvir de onde vêm passos e tiros. "
                          "O jogo precisa mandar som 5.1/7.1.")
        c.append(r)
        rr = hbox(12)
        rr.append(lab("Ambiente", "lm-muted"))
        room = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        room.set_hexpand(True)
        room.set_draw_value(False)
        room.set_value(a["room"])
        rel = Gtk.GestureClick()
        rel.connect("released", lambda *_: self.audio_change(room=int(room.get_value())))
        room.add_controller(rel)
        rr.append(room)
        c.append(rr)
        hr = hbox(10)
        hr.append(lab(("HRIR: " + os.path.basename(a["hrir_file"])) if a.get("hrir_file") else "HRIR: gerado pelo LogiMouse",
                      "lm-small"))
        hr.append(button("Usar arquivo HeSuVi…", "lm-ghost", cb=self._pick_hrir))
        if a.get("hrir_file"):
            hr.append(button("Usar o gerado", "lm-ghost", cb=lambda: self.audio_change(hrir_file="", rebuild=True)))
        c.append(hr)
        row.append(c)
        c = card("Volume")
        sink = s.get("sink")
        if sink and s.get("vol") is not None:
            vr = hbox(12)
            vlab = lab(f"{s['vol']}%", "lm-h2")
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            sc.set_hexpand(True)
            sc.set_draw_value(False)
            sc.set_value(s["vol"])
            sc.connect("value-changed", lambda w: (vlab.set_text(f"{int(w.get_value())}%"),
                                                   self.audio_worker.submit(lambda v=int(w.get_value()): AU.set_volume(sink["id"], v))))
            vr.append(lab("Saída", "lm-muted"))
            vr.append(sc)
            vr.append(vlab)
            c.append(vr)
        else:
            c.append(lab("A saída de som do headset não apareceu no PipeWire (o receptor está na USB?).", "lm-muted", wrap=True))
        r, _ = switch_row("Usar como saída padrão", a["default_out"], lambda v: self.audio_change(default_out=v))
        c.append(r)
        row.append(c)
        body.append(row)
        if not s.get("pw"):
            body.append(card("PipeWire não encontrado", "Equalizador, surround e microfone sem ruído precisam do PipeWire.",
                             "dashed"))

    def _preset_of(self, g):
        return next((n for n, v in AU.PRESETS.items() if v == list(g)), "Personalizado")

    def _preset(self, name):
        if name in AU.PRESETS:
            g = list(AU.PRESETS[name])
            self.eq.set_gains(g)
            for v, x in zip(self.eq_vals, g):
                v.set_text(gain_text(x))
            self.audio_change(preset=name, gains=g)
        else:
            self.audio_change(preset=name)

    def _eq_drag(self, g):
        for v, x in zip(self.eq_vals, g):
            v.set_text(gain_text(x))

    def _pick_hrir(self):
        dlg = Gtk.FileDialog(title="Arquivo HRIR no formato HeSuVi (14 canais, .wav)")
        f = Gtk.FileFilter()
        f.set_name("WAV")
        f.add_pattern("*.wav")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg.set_filters(store)

        def done(d, res):
            try:
                gf = d.open_finish(res)
            except GLib.Error:
                return
            if gf and gf.get_path():
                self.audio_change(hrir_file=gf.get_path(), rebuild=True)
        dlg.open(self, None, done)

    # ---- Microfone ----
    def _sec_mic(self, body):
        a = AU.settings()
        s = self.st
        rn = s.get("rnnoise")
        c = card(None, None, "glow")
        r, _ = switch_row("Redução de ruído por IA", a["nr"] and bool(rn), lambda v: self.audio_change(nr=v, rebuild=True),
                          "Uma rede neural (RNNoise) tira teclado, ventilador e barulho de fundo. Aparece como o "
                          f"microfone “{a.get('label') or 'Headset'} · sem ruído” no Discord, OBS e jogos.",
                          sensitive=bool(rn))
        c.append(r)
        if not rn:
            c.append(lab("O plugin RNNoise não está instalado. Rode ./instalar.sh e aceite baixar o RNNoise "
                         "(github.com/werman/noise-suppression-for-voice).", "lm-warn", wrap=True))
        lv = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        first = None
        for i, (name, hint, _vad) in enumerate(AU.NR_LEVELS):
            b = Gtk.ToggleButton()
            b.add_css_class("lm-level")
            inner = vbox(2)
            inner.append(lab(name, "lm-h2"))
            inner.append(lab(hint, "lm-small"))
            b.set_child(inner)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.set_active(i == a["nr_level"])
            b.set_sensitive(bool(rn and a["nr"]))
            b.connect("toggled", lambda w, i=i: w.get_active() and self.audio_change(nr_level=i))
            lv.append(b)
        c.append(lv)
        body.append(c)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18, homogeneous=True)
        c = card("Voz: ganho e equalizador")
        gr = hbox(12)
        glab = lab(gain_text(a["mic_gain"]), "lm-h2")
        gs = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -12, 12, 1)
        gs.set_hexpand(True)
        gs.set_draw_value(False)
        gs.set_value(a["mic_gain"])
        gs.connect("value-changed", lambda w: glab.set_text(gain_text(int(w.get_value()))))
        rel = Gtk.GestureClick()
        rel.connect("released", lambda *_: self.audio_change(mic_gain=int(gs.get_value())))
        gs.add_controller(rel)
        gr.append(lab("Ganho", "lm-muted"))
        gr.append(gs)
        gr.append(glab)
        c.append(gr)
        c.append(pills([(v, v) for v in AU.VOICE], a["voice"], lambda v: self.audio_change(voice=v), cyan=True))
        c.append(lab("“Rádio” deixa a voz com cara de rádio de jogo; “Clara” realça a fala.", "lm-small", wrap=True))
        row.append(c)
        c = card("Teste de microfone", "Grave 5 segundos e ouça com e sem a redução de ruído.")
        self.bars = Bars()
        c.append(self.bars)
        tr = hbox(8)
        self.rec_test = button("● Gravar 5 s", "lm-primary", cb=self._mic_test)
        tr.append(self.rec_test)
        self.play_raw = button("▶ Original", "lm-ghost", cb=lambda: self._play_test("original"))
        self.play_clean = button("▶ Sem ruído", "lm-ghost", cb=lambda: self._play_test("limpo"))
        for b in (self.play_raw, self.play_clean):
            b.set_sensitive(False)
            tr.append(b)
        c.append(tr)
        row.append(c)
        body.append(row)
        c = card()
        src = s.get("source")
        if src and s.get("micvol") is not None:
            mr = hbox(12)
            mlab = lab(f"{s['micvol']}%", "lm-h2")
            ms = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            ms.set_hexpand(True)
            ms.set_draw_value(False)
            ms.set_value(s["micvol"])
            ms.connect("value-changed", lambda w: (mlab.set_text(f"{int(w.get_value())}%"),
                                                   self.audio_worker.submit(lambda v=int(w.get_value()): AU.set_volume(src["id"], v))))
            mr.append(lab("Volume do microfone", "lm-muted"))
            mr.append(ms)
            mr.append(mlab)
            c.append(mr)
        r, _ = switch_row("Ouvir a própria voz no fone (retorno)", a["sidetone"], lambda v: self.audio_change(sidetone=v))
        c.append(r)
        r, _ = switch_row("Usar como microfone padrão", a["default_in"], lambda v: self.audio_change(default_in=v))
        c.append(r)
        body.append(c)

    def _mic_test(self):
        s = self.st
        src = s.get("source")
        if self.demo or not src:
            self.say("Teste de microfone: o microfone do headset não apareceu no PipeWire.")
            return
        a = AU.settings()
        clean = AU.MIC_SOURCE if s.get("running") and (a.get("nr") or a.get("voice") != "Natural" or a.get("mic_gain")) else None
        self.rec_test.set_sensitive(False)
        self.rec_test.set_label("Gravando… fale agora")

        def ok(files):
            self.test_files = files
            self.rec_test.set_sensitive(True)
            self.rec_test.set_label("● Gravar 5 s")
            key = "limpo" if "limpo" in files else "original"
            if key in files:
                self.bars.set(AU.wav_levels(files[key]))
            self.play_raw.set_sensitive("original" in files)
            self.play_clean.set_sensitive("limpo" in files)
            self.say("Gravado. Ouça os dois." if len(files) == 2 else
                     "Gravado (sem a versão processada: ligue a redução de ruído para comparar).")
        self.audio_worker.submit(lambda: AU.record_test(5, src["id"], clean), ok,
                                 lambda e: (self.say(f"Teste falhou: {e}"), self.rec_test.set_sensitive(True)))

    def _play_test(self, key):
        f = getattr(self, "test_files", {}).get(key)
        if f:
            sink = self.st.get("sink")
            AU.play_file(f, sink["id"] if sink else None)

    # ---- Geral ----
    def _sec_general(self, body):
        s = self.st
        b = s.get("battery")
        c = card("Bateria e avisos")
        row = hbox(12)
        row.append(lab(H.battery_text(b) if b else "—", "lm-big"))
        row.append(lab((b or {}).get("source") or s.get("error") or "", "lm-muted"))
        c.append(row)
        c.append(Gtk.LevelBar(min_value=0, max_value=100, value=(H.battery_value(b) or 0) if b else 0))
        r, _ = switch_row("Avisar com bateria baixa (15%)", config.get_option("notify_low"),
                          lambda v: config.set_option("notify_low", v))
        c.append(r)
        body.append(c)
        c = card("Ainda não disponível no Linux",
                 "Luzes, desligamento automático e o equalizador gravado dentro do fone usam comandos do M HUB "
                 "que ninguém publicou. Uma captura USB feita no Windows (Wireshark + USBPcap) com o M HUB "
                 "mudando cada opção libera esses controles: abra uma issue no GitHub com o arquivo.", "dashed")
        c.append(button("Gerar diagnóstico do headset (~/logimouse-diagnostico.txt)", "lm-ghost", cb=self._diag))
        body.append(c)

    def _diag(self):
        if self.demo:
            self.say("No modo demonstração não há diagnóstico.")
            return
        path = os.path.expanduser("~/logimouse-diagnostico.txt")

        def job():
            lines = []
            HS.diagnose(listen=5.0, out=lines.append)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            return path
        self.say("Gerando diagnóstico (5 s)...")
        self.worker.submit(job, lambda p: self.toast_msg(f"Diagnóstico salvo em {p}"),
                           lambda e: self.say(f"Diagnóstico falhou: {e}"))


# --------------------------------------------------------------------------
# Leitura dos dispositivos (rodam na thread do Worker)
# --------------------------------------------------------------------------
def load_mouse(dev):
    s = H.read_all(dev)
    s["onboard"] = None
    if O.supported(dev):
        try:
            ob = O.Onboard(dev)
            prof = ob.read_profile()
            if prof.crc_ok():
                s["onboard"] = dict(ob=ob, mode=ob.mode(), profile=prof.to_dict(), nbuttons=ob.nbuttons)
        except (O.OnboardError, *H.DEVICE_ERRORS):
            pass
    return s


def load_headset(h, demo=False):
    s = dict(battery=None, error=None, sink=None, source=None, vol=None, micvol=None)
    try:
        s["battery"] = h.read_battery()
    except HS.HeadsetError as e:
        s["error"] = str(e)
    s["pw"] = AU.pipewire_ok()
    s["rnnoise"] = AU.rnnoise_plugin() if not demo else "demo"
    s["running"] = AU.service_running() if not demo else False
    if not demo and s["pw"]:
        sink, src = AU.find_headset()
        s["sink"], s["source"] = sink, src
        if sink:
            s["vol"] = AU.get_volume(sink["id"])
            if not AU.settings().get("label") or AU.settings().get("label") == "Headset":
                AU.save_settings(label=h.name)
        if src:
            s["micvol"] = AU.get_volume(src["id"])
    return s


def clear(box):
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def json_copy(x):
    import json
    return json.loads(json.dumps(x))


def snap(v, choices):
    return min(choices, key=lambda c: abs(c - v)) if choices else int(v)


def gain_text(g):
    g = int(g)
    return f"+{g} dB" if g > 0 else f"{g} dB"

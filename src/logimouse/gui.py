"""Painel (janela) em Tkinter."""

import os
import queue
import subprocess
import threading
import traceback

from . import APP_NAME, __version__
from . import config
from . import hidpp as H
from . import update as U


def run_gui(demo=False):
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("Falta o Tkinter. Instale com:\n"
              "  Ubuntu/Debian/Mint: sudo apt install python3-tk\n"
              "  Fedora:             sudo dnf install python3-tkinter\n"
              "  Arch/Manjaro:       sudo pacman -S tk\n"
              "Ou use o modo terminal: logimouse --cli")
        return 1
    if demo:
        config.DRY_RUN = True
    App(tk, ttk, demo=demo).run()
    return 0


class Worker:
    """Roda as conversas com o mouse fora da thread da interface."""

    def __init__(self, root):
        self.root = root
        self.jobs = queue.Queue()
        self.done = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()
        root.after(40, self._poll)

    def submit(self, fn, ok=None, err=None):
        self.jobs.put((fn, ok, err))

    def _loop(self):
        while True:
            fn, ok, err = self.jobs.get()
            try:
                res = fn()
                self.done.put((ok, res, None))
            except Exception as e:  # noqa: BLE001 - mostramos qualquer erro na barra de status
                self.done.put((err, None, e))

    def _poll(self):
        # Um erro num callback nao pode parar os outros: antes, uma excecao aqui
        # interrompia o ciclo e as respostas seguintes (inclusive "salvar") se perdiam.
        try:
            while True:
                try:
                    cb, res, exc = self.done.get_nowait()
                except queue.Empty:
                    break
                if cb:
                    try:
                        cb(exc if exc is not None else res)
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
        finally:
            self.root.after(40, self._poll)


class App:
    BG = "#f4f5f7"
    CARD = "#ffffff"
    TEXT = "#1d1f23"
    MUTED = "#6b7280"
    ACCENT = "#0a7d6b"
    LOW = "#c2410c"
    LINE = "#e3e5e9"

    def __init__(self, tk, ttk, demo=False):
        self.tk, self.ttk, self.demo = tk, ttk, demo
        self.root = tk.Tk(className="logimouse")
        self.root.title(APP_NAME)
        self.root.geometry("440x720")
        self.root.minsize(380, 420)
        self.root.configure(bg=self.BG)
        self.worker = Worker(self.root)
        self.devices = []
        self.dev = None
        self.state = {}
        self._busy = False
        self.tray_ok = None
        self._style()
        self._layout()
        self.root.after(100, self.scan)
        self.root.after(60_000, self._auto_battery)
        self.worker.submit(config.tray_available, self._tray_checked, lambda e: None)

    # ---- aparencia ----
    def _style(self):
        st = self.ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except self.tk.TclError:
            pass
        st.configure(".", background=self.BG, foreground=self.TEXT, font=("Sans", 10))
        st.configure("Card.TFrame", background=self.CARD)
        st.configure("Card.TLabel", background=self.CARD, foreground=self.TEXT)
        st.configure("Muted.TLabel", background=self.CARD, foreground=self.MUTED, font=("Sans", 9))
        st.configure("Title.TLabel", background=self.CARD, foreground=self.MUTED, font=("Sans", 9, "bold"))
        st.configure("Big.TLabel", background=self.CARD, foreground=self.TEXT, font=("Sans", 26, "bold"))
        st.configure("Value.TLabel", background=self.CARD, foreground=self.TEXT, font=("Sans", 12, "bold"))
        st.configure("Head.TLabel", background=self.BG, foreground=self.TEXT, font=("Sans", 13, "bold"))
        st.configure("Sub.TLabel", background=self.BG, foreground=self.MUTED, font=("Sans", 9))
        st.configure("Status.TLabel", background=self.BG, foreground=self.MUTED, font=("Sans", 9))
        st.configure("Card.TCheckbutton", background=self.CARD, foreground=self.TEXT)
        st.map("Card.TCheckbutton", background=[("active", self.CARD)])
        st.configure("Card.TRadiobutton", background=self.CARD, foreground=self.TEXT)
        st.map("Card.TRadiobutton", background=[("active", self.CARD)])
        st.configure("Horizontal.TScale", background=self.CARD, troughcolor=self.LINE)
        for name, color in (("Good", self.ACCENT), ("Low", self.LOW)):
            st.configure(f"{name}.Horizontal.TProgressbar", troughcolor=self.LINE,
                         background=color, bordercolor=self.LINE, lightcolor=color,
                         darkcolor=color, thickness=10)

    def _layout(self):
        tk, ttk = self.tk, self.ttk
        top = ttk.Frame(self.root, padding=(16, 14, 16, 6))
        top.pack(fill="x")
        ttk.Label(top, text=APP_NAME + (" (demo)" if self.demo else ""), style="Head.TLabel").pack(side="left")
        ttk.Button(top, text="Atualizar", command=self.scan).pack(side="right")

        sel = ttk.Frame(self.root, padding=(16, 0, 16, 6))
        sel.pack(fill="x")
        self.dev_var = tk.StringVar()
        self.dev_combo = ttk.Combobox(sel, textvariable=self.dev_var, state="readonly")
        self.dev_combo.pack(fill="x")
        self.dev_combo.bind("<<ComboboxSelected>>", lambda e: self.select(self.dev_combo.current()))
        self.dev_info = ttk.Label(sel, text="", style="Sub.TLabel")
        self.dev_info.pack(anchor="w", pady=(4, 0))

        self.status = ttk.Label(self.root, text="", style="Status.TLabel", padding=(16, 6), wraplength=400)
        self.status.pack(fill="x", side="bottom")

        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, bg=self.BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=(16, 4, 16, 16))
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.root.bind_all(seq, self._wheel)

    def _wheel(self, e):
        w = self.root.winfo_containing(e.x_root, e.y_root)
        if w is not None and str(w).startswith(str(self.canvas)):
            if getattr(w, "winfo_class", lambda: "")() in ("TScale", "TCombobox", "TSpinbox"):
                return
            delta = -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1
            self.canvas.yview_scroll(delta, "units")

    def card(self, title):
        f = self.ttk.Frame(self.body, style="Card.TFrame", padding=14)
        f.pack(fill="x", pady=6)
        self.ttk.Label(f, text=title.upper(), style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        return f

    def say(self, text):
        self.status.configure(text=text)

    def clear_body(self):
        for w in self.body.winfo_children():
            w.destroy()

    def message(self, text):
        self.clear_body()
        c = self.card("Aviso")
        self.ttk.Label(c, text=text, style="Card.TLabel", wraplength=360, justify="left").pack(anchor="w")
        self._build_app_card()

    # ---- fluxo ----
    def scan(self):
        if self._busy:
            return
        self._busy = True
        self.say("Procurando dispositivos Logitech...")
        if self.demo:
            from .demo import discover_demo
            fn = discover_demo
        else:
            fn = H.discover
        self.worker.submit(fn, self._scanned, self._failed)

    def _scanned(self, res):
        self._busy = False
        self.devices, problems = res
        if not self.devices:
            self.dev_combo.configure(values=[])
            self.dev_var.set("")
            self.dev_info.configure(text="")
            self.message("\n\n".join(problems) or "Nenhum dispositivo encontrado.")
            self.say("")
            return
        self.dev_combo.configure(values=[f"{d.name}  ({d.kind_name})" for d in self.devices])
        keep = 0
        if self.dev is not None:
            for i, d in enumerate(self.devices):
                if d.name == self.dev.name:
                    keep = i
        self.dev_combo.current(keep)
        self.select(keep)
        if problems:
            self.say(" ".join(problems))

    def _failed(self, exc):
        self._busy = False
        self.say(f"Erro: {exc}")

    def select(self, i):
        if i < 0 or i >= len(self.devices):
            return
        self.dev = d = self.devices[i]
        self.dev_info.configure(text=f"{d.kind_name} · {d.connection} · HID++ {d.protocol[0]}.{d.protocol[1]}")
        self.clear_body()
        c = self.card("Aguarde")
        self.ttk.Label(c, text="Lendo configurações...", style="Card.TLabel").pack(anchor="w")
        self.say("")
        self.worker.submit(lambda: H.read_all(d), self._loaded, self._failed)

    def _loaded(self, s):
        self.state = s
        self.build()
        self.say("Pronto. As mudanças são aplicadas na hora e ficam salvas.")

    # ---- cartoes ----
    def build(self):
        self.clear_body()
        s = self.state
        self._build_battery(s.get("battery"))
        if s.get("dpi") or s.get("pointer_speed") is not None:
            self._build_sensitivity(s.get("dpi"), s.get("pointer_speed"))
        if s.get("report_rate"):
            self._build_rate(*s["report_rate"])
        if s.get("smartshift") or s.get("hires"):
            self._build_wheel(s.get("smartshift"), s.get("hires"))
        if s.get("host_mode") is not None:
            self._build_host(s["host_mode"])
        self._build_app_card()

    def _build_battery(self, b):
        ttk = self.ttk
        c = self.card("Bateria")
        if not b:
            ttk.Label(c, text="Este dispositivo não informa a bateria.", style="Muted.TLabel").pack(anchor="w")
            return
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        self.bat_big = ttk.Label(row, text=H.battery_text(b), style="Big.TLabel")
        self.bat_big.pack(side="left")
        self.bat_status = ttk.Label(row, text=b["status"] or "", style="Muted.TLabel")
        self.bat_status.pack(side="left", padx=(12, 0), pady=(10, 0))
        val = H.battery_value(b) or 0
        low = val <= 20 and not b["charging"]
        self.bat_bar = ttk.Progressbar(c, maximum=100, value=val,
                                       style=("Low" if low else "Good") + ".Horizontal.TProgressbar")
        self.bat_bar.pack(fill="x", pady=(8, 4))
        extra = b["source"]
        if b["voltage"]:
            extra = f"{b['voltage']} mV · " + extra
        if b["percent"] is None and b["level"]:
            extra = "o mouse só informa o nível aproximado · " + extra
        ttk.Label(c, text=extra, style="Muted.TLabel").pack(anchor="w")

    def _build_sensitivity(self, dpi, speed):
        tk, ttk = self.tk, self.ttk
        c = self.card("Sensibilidade")
        if dpi:
            choices, cur, dflt = dpi
            self.dpi_choices = choices
            head = ttk.Frame(c, style="Card.TFrame")
            head.pack(fill="x")
            ttk.Label(head, text="DPI", style="Card.TLabel").pack(side="left")
            self.dpi_label = ttk.Label(head, text=str(cur), style="Value.TLabel")
            self.dpi_label.pack(side="right")
            self.dpi_var = tk.DoubleVar(value=choices.index(cur) if cur in choices else 0)
            sc = ttk.Scale(c, from_=0, to=max(1, len(choices) - 1), variable=self.dpi_var,
                           command=self._dpi_moved)
            sc.pack(fill="x", pady=(6, 2))
            sc.bind("<ButtonRelease-1>", lambda e: self._dpi_apply())
            ends = ttk.Frame(c, style="Card.TFrame")
            ends.pack(fill="x")
            ttk.Label(ends, text=str(choices[0]), style="Muted.TLabel").pack(side="left")
            ttk.Label(ends, text=str(choices[-1]), style="Muted.TLabel").pack(side="right")
            pre = ttk.Frame(c, style="Card.TFrame")
            pre.pack(fill="x", pady=(8, 0))
            for p in (400, 800, 1000, 1600, 3200):
                v = min(choices, key=lambda x: abs(x - p))
                if abs(v - p) <= 50:
                    ttk.Button(pre, text=str(v), width=5,
                               command=lambda v=v: self._dpi_apply(v)).pack(side="left", padx=(0, 4))
            ttk.Label(c, text=f"padrão do mouse: {dflt}", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        if speed is not None:
            if dpi:
                ttk.Separator(c).pack(fill="x", pady=10)
            head = ttk.Frame(c, style="Card.TFrame")
            head.pack(fill="x")
            ttk.Label(head, text="Velocidade do ponteiro", style="Card.TLabel").pack(side="left")
            self.spd_label = ttk.Label(head, text=self._spd_text(speed), style="Value.TLabel")
            self.spd_label.pack(side="right")
            self.spd_var = tk.DoubleVar(value=speed)
            sc = ttk.Scale(c, from_=0x2E, to=0x1FF, variable=self.spd_var,
                           command=lambda v: self.spd_label.configure(text=self._spd_text(float(v))))
            sc.pack(fill="x", pady=(6, 0))
            sc.bind("<ButtonRelease-1>", lambda e: self._speed_apply())

    def _speed_apply(self):
        v = max(0x2E, min(0x1FF, int(round(self.spd_var.get()))))
        self._apply(lambda: self.dev.set_pointer_speed(v),
                    lambda r: (self.spd_var.set(r), self.spd_label.configure(text=self._spd_text(r))),
                    "Velocidade do ponteiro", {"pointer_speed": v}, expect=v)

    @staticmethod
    def _spd_text(v):
        return f"{v / 256:.2f}x"

    def _dpi_moved(self, v):
        self.dpi_label.configure(text=str(self.dpi_choices[int(round(float(v)))]))

    def _dpi_apply(self, value=None):
        if value is None:
            value = self.dpi_choices[int(round(self.dpi_var.get()))]

        def ok(v):
            if v in self.dpi_choices:
                self.dpi_var.set(self.dpi_choices.index(v))
            self.dpi_label.configure(text=str(v))
        self._apply(lambda: self.dev.set_dpi(value), ok, f"DPI {value}", {"dpi": int(value)}, expect=int(value),
                    hint="Se for um mouse G, ligue \"Controlar pelo computador\" em Perfis do mouse.")

    def _build_rate(self, choices, cur):
        tk, ttk = self.tk, self.ttk
        c = self.card("Taxa de atualização")
        self.rate_var = tk.IntVar(value=cur or 0)
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        for hz in sorted(choices):
            ttk.Radiobutton(row, text=f"{hz} Hz", value=hz, variable=self.rate_var, style="Card.TRadiobutton",
                            command=self._rate_apply).pack(side="left", padx=(0, 10))
        ttk.Label(c, text="Mais Hz = cursor mais suave, gasta mais bateria.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

    def _rate_apply(self):
        hz = self.rate_var.get()
        self._apply(lambda: self.dev.set_report_rate(hz), lambda v: self.rate_var.set(v or 0),
                    f"Taxa {hz} Hz", {"report_rate": hz}, expect=hz)

    def _build_wheel(self, ss, hw):
        tk, ttk = self.tk, self.ttk
        c = self.card("Roda de rolagem")
        if ss:
            mode, thr = ss
            self.ss_mode = tk.IntVar(value=mode)
            self.ss_auto = tk.BooleanVar(value=thr is not None)
            self.ss_thr = tk.DoubleVar(value=thr or 12)
            row = ttk.Frame(c, style="Card.TFrame")
            row.pack(fill="x")
            ttk.Radiobutton(row, text="Catraca (clique)", value=2, variable=self.ss_mode,
                            style="Card.TRadiobutton", command=self._ss_apply).pack(side="left", padx=(0, 12))
            ttk.Radiobutton(row, text="Livre", value=1, variable=self.ss_mode,
                            style="Card.TRadiobutton", command=self._ss_apply).pack(side="left")
            ttk.Checkbutton(c, text="SmartShift: solta sozinha quando gira rápido", variable=self.ss_auto,
                            style="Card.TCheckbutton", command=self._ss_apply).pack(anchor="w", pady=(8, 0))
            head = ttk.Frame(c, style="Card.TFrame")
            head.pack(fill="x", pady=(4, 0))
            ttk.Label(head, text="Força para soltar", style="Muted.TLabel").pack(side="left")
            self.ss_lbl = ttk.Label(head, text=str(int(self.ss_thr.get())), style="Card.TLabel")
            self.ss_lbl.pack(side="right")
            self.ss_scale = ttk.Scale(c, from_=1, to=49, variable=self.ss_thr,
                                      command=lambda v: self.ss_lbl.configure(text=str(int(float(v)))))
            self.ss_scale.pack(fill="x")
            self.ss_scale.bind("<ButtonRelease-1>", lambda e: self._ss_apply())
            self._ss_enable()
        if hw:
            if ss:
                ttk.Separator(c).pack(fill="x", pady=10)
            self.hw_hires = tk.BooleanVar(value=hw["hires"])
            self.hw_inv = tk.BooleanVar(value=hw["invert"])
            ttk.Checkbutton(c, text="Rolagem em alta resolução (mais suave)", variable=self.hw_hires,
                            style="Card.TCheckbutton", command=self._hires_apply).pack(anchor="w")
            if hw["can_invert"]:
                ttk.Checkbutton(c, text="Inverter direção da rolagem", variable=self.hw_inv,
                                style="Card.TCheckbutton", command=self._invert_apply).pack(anchor="w", pady=(4, 0))
            ttk.Label(c, text="Se a rolagem ficar rápida demais, desligue a alta resolução.",
                      style="Muted.TLabel", wraplength=360).pack(anchor="w", pady=(6, 0))

    def _hires_apply(self):
        v = self.hw_hires.get()
        self._apply(lambda: self.dev.set_hires_wheel(hires=v), self._hw_sync, "Alta resolução",
                    {"hires": v}, expect=lambda hw: hw["hires"] == v)

    def _invert_apply(self):
        v = self.hw_inv.get()
        self._apply(lambda: self.dev.set_hires_wheel(invert=v), self._hw_sync, "Inverter rolagem",
                    {"invert": v}, expect=lambda hw: hw["invert"] == v)

    def _hw_sync(self, hw):
        self.hw_hires.set(hw["hires"])
        self.hw_inv.set(hw["invert"])

    def _ss_enable(self):
        on = self.ss_mode.get() == 2 and self.ss_auto.get()
        self.ss_scale.state(["!disabled"] if on else ["disabled"])

    def _ss_apply(self):
        self._ss_enable()
        mode = self.ss_mode.get()
        thr = int(self.ss_thr.get()) if self.ss_auto.get() else None

        def ok(res):
            m, t = res
            self.ss_mode.set(m)
            if m == 2:
                self.ss_auto.set(t is not None)
            if t:
                self.ss_thr.set(t)
                self.ss_lbl.configure(text=str(t))
            self._ss_enable()
        self._apply(lambda: self.dev.set_smartshift(mode, thr), ok, "Roda",
                    {"smartshift": [mode, thr]}, expect=lambda res: res[0] == mode)

    def _build_host(self, on):
        tk, ttk = self.tk, self.ttk
        c = self.card("Perfis do mouse")
        self.host_var = tk.BooleanVar(value=on)
        ttk.Checkbutton(c, text="Controlar pelo computador (modo host)", variable=self.host_var,
                        style="Card.TCheckbutton", command=self._host_apply).pack(anchor="w")
        ttk.Label(c, text="Desligado, o mouse usa os perfis salvos nele e pode ignorar o DPI daqui. "
                          "Ligue se o DPI não estiver mudando.",
                  style="Muted.TLabel", wraplength=360, justify="left").pack(anchor="w", pady=(6, 0))

    def _host_apply(self):
        v = self.host_var.get()
        self._apply(lambda: self.dev.set_host_mode(v), self._host_done, "Modo host",
                    {"host_mode": v}, expect=v)

    def _host_done(self, v):
        self.host_var.set(v)
        self.select(self.devices.index(self.dev))  # trocar o modo muda DPI/taxa ativos: rele tudo

    # ---- cartao do aplicativo ----
    def _tray_checked(self, ok):
        self.tray_ok = bool(ok)
        if hasattr(self, "tray_hint") and self.tray_hint.winfo_exists():
            self._update_app_card()

    def _build_app_card(self):
        tk, ttk = self.tk, self.ttk
        c = self.card("Aplicativo")
        self.auto_var = tk.BooleanVar(value=config.autostart_enabled())
        self.reapply_var = tk.BooleanVar(value=bool(config.get_option("reapply")))
        self.auto_chk = ttk.Checkbutton(c, text="Iniciar com o sistema (ícone com a bateria na barra)",
                                        variable=self.auto_var, style="Card.TCheckbutton",
                                        command=self._autostart_toggle)
        self.auto_chk.pack(anchor="w")
        ttk.Checkbutton(c, text="Reaplicar meus ajustes quando o mouse reconectar",
                        variable=self.reapply_var, style="Card.TCheckbutton",
                        command=lambda: config.set_option("reapply", self.reapply_var.get())).pack(anchor="w", pady=(4, 0))
        self.autoupd_var = tk.BooleanVar(value=bool(config.get_option("auto_update")))
        ttk.Checkbutton(c, text="Atualizar automaticamente pelo GitHub",
                        variable=self.autoupd_var, style="Card.TCheckbutton",
                        command=lambda: config.set_option("auto_update", self.autoupd_var.get())).pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 0))
        self.tray_btn = ttk.Button(row, text="Mostrar ícone na barra agora", command=self._start_tray)
        self.tray_btn.pack(side="left")
        if self.dev is not None:
            ttk.Button(row, text="Esquecer ajustes", command=self._forget).pack(side="right")
        self.tray_hint = ttk.Label(c, text="", style="Muted.TLabel", wraplength=360, justify="left")
        self.tray_hint.pack(anchor="w", pady=(6, 0))
        ttk.Separator(c).pack(fill="x", pady=10)
        vrow = ttk.Frame(c, style="Card.TFrame")
        vrow.pack(fill="x")
        ttk.Label(vrow, text=f"Versão {__version__}", style="Card.TLabel").pack(side="left")
        ttk.Button(vrow, text="Procurar atualização", command=self._check_update).pack(side="right")
        self._update_app_card()

    def _update_app_card(self):
        running = config.tray_running()
        if self.tray_ok is False:
            self.tray_btn.state(["disabled"])
            self.tray_hint.configure(text="Para o ícone na barra instale: sudo apt install python3-gi "
                                          "gir1.2-ayatanaappindicator3-0.1 (ou rode o instalar.sh de novo).")
        elif running:
            self.tray_btn.state(["disabled"])
            self.tray_hint.configure(text="O ícone já está rodando na barra. Seus ajustes voltam sozinhos "
                                          "quando o mouse reconectar.")
        else:
            self.tray_btn.state(["!disabled"])
            self.tray_hint.configure(text="Sem o ícone rodando, os ajustes só voltam quando você abrir este painel.")

    def _autostart_toggle(self):
        on = self.auto_var.get()
        config.set_autostart(on)
        if on and self.tray_ok is not False and not config.tray_running():
            self._start_tray()
        self.say("Início com o sistema " + ("ligado." if on else "desligado."))

    def _start_tray(self):
        args = ["--tray"] + (["--demo"] if self.demo else [])
        try:
            subprocess.Popen(config.launcher_command(*args), env=config.launcher_env(),
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.say("Ícone iniciado na barra.")
        except OSError as e:
            self.say(f"Não deu para iniciar o ícone: {e}")
        self.root.after(1500, lambda: self.tray_btn.winfo_exists() and self._update_app_card())

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
                from tkinter import messagebox
                if messagebox.askyesno("Atualização disponível",
                                       f"A versão {info['latest']} do LogiMouse está disponível.\n"
                                       f"Você está na {info['current']}. Instalar agora?", parent=self.root):
                    self.say("Baixando e instalando...")
                    self.worker.submit(lambda: U.install(info["ref"], info["latest"]), self._updated,
                                       lambda e: self.say(f"A atualização falhou: {e}. Nada foi alterado."))
                else:
                    self.say("")
        self.worker.submit(U.check, done, lambda e: self.say(f"Não deu para procurar atualização: {e}"))

    def _updated(self, res):
        from tkinter import messagebox
        config.restart_tray()
        msg = f"Pronto! Agora você está na versão {res['version']}. O painel vai reabrir."
        if res["needs_installer"]:
            msg += "\n\nEsta versão mudou a permissão de acesso ao mouse: rode o instalar.sh de novo."
        messagebox.showinfo("LogiMouse atualizado", msg, parent=self.root)
        cmd = config.launcher_command()
        try:
            self.root.destroy()
        finally:
            os.execvpe(cmd[0], cmd, config.launcher_env())

    def _forget(self):
        if self.dev is not None:
            config.forget(self.dev.name)
            self.say(f"Ajustes salvos de {self.dev.name} apagados. O mouse fica como está agora.")

    # ---- aplicar ----
    def _remember(self, dev, wanted):
        """Salva o que a pessoa ESCOLHEU (nao o que o mouse respondeu). Devolve erro ou None."""
        if not wanted:
            return None
        try:
            config.remember(dev.name, **wanted)
        except OSError as e:
            return str(e)
        return None

    def _apply(self, fn, ok, what, wanted=None, expect=None, hint=""):
        """Manda o ajuste para o mouse, salva a escolha e confere a resposta.

        wanted: dict com o valor escolhido, salvo antes de mexer na tela.
        expect: valor esperado na resposta (ou funcao resposta -> bool) para avisar
                quando o mouse ficou com outro valor.
        """
        self.say(f"Aplicando: {what}...")
        dev = self.dev

        def done(res):
            err = self._remember(dev, wanted)
            try:
                ok(res)
            except self.tk.TclError:
                pass  # o cartao foi redesenhado enquanto o mouse respondia
            if err:
                self.say(f"{what}: aplicado, mas não deu para salvar ({err}).")
                return
            matches = True
            if callable(expect):
                matches = bool(expect(res))
            elif expect is not None:
                matches = res == expect
            if not matches:
                self.say(f"{what}: salvo, mas o mouse respondeu {res}. {hint}".strip())
            else:
                self.say(f"{what}: aplicado e salvo.")

        def fail(e):
            unreachable = isinstance(e, (H.HidppTimeout, OSError)) or (
                isinstance(e, H.HidppError) and e.hidpp10)
            if unreachable:
                # mouse dormindo ou fora de alcance: guarda a escolha para aplicar quando ele voltar
                err = self._remember(dev, wanted)
                if wanted and not err:
                    self.say(f"{what}: o mouse não respondeu. Salvei e aplico quando ele reconectar "
                             "(ou mexa o mouse e tente de novo).")
                    return
            self.say(f"{what}: não deu certo ({e}). Mexa o mouse e tente de novo.")
        self.worker.submit(fn, done, fail)

    def _auto_battery(self):
        d = self.dev
        if d is not None and not self._busy:
            def upd(b):
                if b and self.dev is d and hasattr(self, "bat_big") and self.bat_big.winfo_exists():
                    self.bat_big.configure(text=H.battery_text(b))
                    self.bat_status.configure(text=b["status"] or "")
                    v = H.battery_value(b)
                    if v is not None:
                        self.bat_bar.configure(value=v)
            self.worker.submit(lambda: H.read_battery(d), upd, lambda e: None)
        self.root.after(60_000, self._auto_battery)

    def run(self):
        self.root.mainloop()

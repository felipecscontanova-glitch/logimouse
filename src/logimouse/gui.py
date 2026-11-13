"""Abre o painel: o novo (GTK 4 + libadwaita) ou, se ele nao estiver instalado, o antigo (Tkinter)."""

from . import config


def gtk_available():
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
        gi.require_foreign("cairo")  # desenhos (anel da bateria, mouse, equalizador)
    except (ImportError, ValueError):
        return False
    return True


def run_gui(demo=False):
    if not gtk_available():
        print("GTK 4 + libadwaita não encontrados: abrindo o painel antigo.\n"
              "Para o painel novo: sudo apt install gir1.2-adw-1 python3-gi python3-gi-cairo")
        from .gui_tk import run_gui as run_tk
        return run_tk(demo=demo)
    if demo:
        config.DRY_RUN = True
    from .window import LogiApp
    return LogiApp(demo=demo).run(None)

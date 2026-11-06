"""Ponto de entrada: logimouse [--tray | --cli | --dpi N | --reapply | --autostart on|off] [--demo]"""

import argparse
import sys

from . import APP_NAME, __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="logimouse",
                                 description="Bateria, DPI e roda de mouses Logitech e bateria de headsets MCHOSE no Linux.")
    ap.add_argument("--tray", action="store_true", help="rodar na bandeja (bateria + reaplicar ajustes)")
    ap.add_argument("--cli", action="store_true", help="mostrar informações no terminal")
    ap.add_argument("--dpi", type=int, metavar="N", help="mudar o DPI pelo terminal")
    ap.add_argument("--reapply", action="store_true", help="reaplicar os ajustes salvos agora")
    ap.add_argument("--autostart", choices=["on", "off"], help="ligar/desligar o início com o sistema")
    ap.add_argument("--update", action="store_true", help="procurar e instalar a versão mais nova do GitHub")
    ap.add_argument("--check-update", action="store_true", help="só ver se há versão nova no GitHub")
    ap.add_argument("--rollback", action="store_true", help="voltar para a versão anterior à última atualização")
    ap.add_argument("--diagnostico", "--diagnose", dest="diagnose", action="store_true",
                    help="relatório para adaptar o app a um headset novo")
    ap.add_argument("--demo", action="store_true", help="usar um mouse simulado (não mexe nos seus ajustes)")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    a = ap.parse_args(argv)

    if a.autostart:
        from . import config
        on = config.set_autostart(a.autostart == "on")
        print("Início com o sistema:", "ligado" if on else "desligado")
        return 0
    if a.update or a.check_update or a.rollback:
        from .cli import run_update
        return run_update(install=a.update, rollback=a.rollback)
    if a.diagnose:
        from .cli import run_diagnose
        return run_diagnose()
    if a.tray:
        from .tray import run_tray
        return run_tray(demo=a.demo)
    if a.reapply:
        from .cli import run_reapply
        return run_reapply()
    if a.cli or a.dpi:
        from .cli import run_cli
        return run_cli(dpi=a.dpi, demo=a.demo)
    from .gui import run_gui
    return run_gui(demo=a.demo)


if __name__ == "__main__":
    sys.exit(main())

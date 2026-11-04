"""Modo terminal."""

from . import config
from . import hidpp as H


def run_cli(dpi=None, demo=False):
    if demo:
        from .demo import discover_demo
        config.DRY_RUN = True
        devices, problems = discover_demo()
    else:
        devices, problems = H.discover()
    for p in problems:
        print("!", p)
    if not devices:
        return 1
    for d in devices:
        print(f"\n== {d.name}  [{d.kind_name}, {d.connection}, HID++ {d.protocol[0]}.{d.protocol[1]}]")
        if dpi:
            try:
                v = d.set_dpi(dpi)
                config.remember(d.name, dpi=v)
                print("  DPI ajustado para", v)
            except (H.NotSupported, H.HidppError, H.HidppTimeout) as e:
                print("  Não deu para mudar o DPI:", e)
        s = H.read_all(d)
        b = s["battery"]
        if b:
            print(f"  Bateria: {H.battery_text(b)}  {b['status']}"
                  + (f"  ({b['voltage']} mV)" if b["voltage"] else ""))
        if s["dpi"]:
            ch, cur, _ = s["dpi"]
            print(f"  DPI: {cur}  (de {ch[0]} a {ch[-1]})")
        if s["pointer_speed"] is not None:
            print(f"  Velocidade do ponteiro: {s['pointer_speed']} (256 = normal)")
        if s["report_rate"]:
            print(f"  Taxa de atualização: {s['report_rate'][1]} Hz  (opções: {s['report_rate'][0]})")
        if s["smartshift"]:
            m, t = s["smartshift"]
            print(f"  Roda: {'catraca' if m == 2 else 'livre'}" + (f", SmartShift {t}" if t else ""))
        if s["hires"]:
            print(f"  Rolagem alta resolução: {'sim' if s['hires']['hires'] else 'não'}"
                  f", invertida: {'sim' if s['hires']['invert'] else 'não'}")
        if s["host_mode"] is not None:
            print(f"  Modo host: {'ligado' if s['host_mode'] else 'desligado (perfis da memória)'}")
        saved = config.device_settings(d.name)
        if saved:
            print("  Ajustes salvos:", ", ".join(f"{k}={v}" for k, v in sorted(saved.items())))
    return 0


def run_reapply():
    devices, problems = H.discover()
    for p in problems:
        print("!", p)
    for d in devices:
        saved = config.device_settings(d.name)
        if not saved:
            print(f"{d.name}: nenhum ajuste salvo")
            continue
        done, failed = H.apply_settings(d, saved)
        print(f"{d.name}: reaplicado {', '.join(done) or 'nada'}"
              + (f" (falhou: {', '.join(failed)})" if failed else ""))
    return 0 if devices else 1

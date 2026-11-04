#!/usr/bin/env bash
# Instala (ou atualiza) o LogiMouse para o usuario atual.
#
#   ./instalar.sh             instala, perguntando o que for preciso
#   ./instalar.sh -y          instala aceitando tudo
#   ./instalar.sh --remover   desinstala
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="$HOME/.local/share/logimouse"
BIN="$HOME/.local/bin/logimouse"
DESK="$HOME/.local/share/applications/logimouse.desktop"
AUTO="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/logimouse.desktop"
RULE=/etc/udev/rules.d/42-logimouse.rules
YES=0

PY="${LOGIMOUSE_PYTHON:-/usr/bin/python3}"
[ -x "$PY" ] || PY="$(command -v python3 || true)"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
ask() {
    [ "$YES" = 1 ] && return 0
    local ans=""
    read -r -p "$1 [S/n] " ans </dev/tty || true
    [[ -z "$ans" || "$ans" =~ ^[SsYy] ]]
}
stop_tray() { pkill -f -- "logimouse --tray" 2>/dev/null || true; }

remove() {
    stop_tray
    rm -f "$BIN" "$DESK" "$AUTO"
    rm -rf "$PREFIX"
    if [ -f "$RULE" ]; then
        sudo rm -f "$RULE" && sudo udevadm control --reload-rules
    fi
    echo "LogiMouse removido."
    echo "Seus ajustes salvos continuam em ~/.config/logimouse (apague a pasta se quiser)."
}

case "${1:-}" in
    --remover|--remove|--uninstall) remove; exit 0 ;;
    -y|--yes) YES=1 ;;
    "") ;;
    *) echo "uso: $0 [-y | --remover]"; exit 1 ;;
esac

if [ -z "$PY" ]; then
    echo "Python 3 não encontrado. Instale o pacote python3 e rode de novo."
    exit 1
fi

TRAY_CHECK='
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
for n in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(n, "0.1"); __import__("gi.repository." + n); break
    except (ImportError, ValueError):
        pass
else:
    raise SystemExit(1)
'
has_tk()     { "$PY" -c 'import tkinter' >/dev/null 2>&1; }
has_tray()   { "$PY" -c "$TRAY_CHECK" >/dev/null 2>&1; }
has_notify() { command -v notify-send >/dev/null 2>&1; }

# ---------------------------------------------------------------- 1. pacotes
bold "1/5  Dependências"
PM=""
for p in apt-get dnf pacman zypper; do command -v "$p" >/dev/null 2>&1 && { PM=$p; break; }; done

PKGS=()
case "$PM" in
    apt-get)
        has_tk     || PKGS+=(python3-tk)
        has_tray   || PKGS+=(python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1)
        has_notify || PKGS+=(libnotify-bin) ;;
    dnf)
        has_tk     || PKGS+=(python3-tkinter)
        has_tray   || PKGS+=(python3-gobject gtk3 libayatana-appindicator-gtk3)
        has_notify || PKGS+=(libnotify) ;;
    pacman)
        has_tk     || PKGS+=(tk)
        has_tray   || PKGS+=(python-gobject gtk3 libayatana-appindicator)
        has_notify || PKGS+=(libnotify) ;;
    zypper)
        has_tk     || PKGS+=(python3-tk)
        has_tray   || PKGS+=(python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-3_0 typelib-1_0-AyatanaAppIndicator3-0_1)
        has_notify || PKGS+=(libnotify-tools) ;;
esac

if [ ${#PKGS[@]} -gt 0 ]; then
    echo "Faltam estes pacotes: ${PKGS[*]}"
    if ask "Instalar agora (pede sua senha)?"; then
        case "$PM" in
            apt-get) sudo apt-get install -y "${PKGS[@]}" || { sudo apt-get update && sudo apt-get install -y "${PKGS[@]}"; } ;;
            dnf)     sudo dnf install -y "${PKGS[@]}" ;;
            pacman)  sudo pacman -S --needed --noconfirm "${PKGS[@]}" ;;
            zypper)  sudo zypper --non-interactive install "${PKGS[@]}" ;;
        esac
    fi
elif [ -z "$PM" ]; then
    has_tk || warn "Não reconheci seu gerenciador de pacotes. Instale o Tkinter do Python 3 manualmente."
fi

if ! has_tk; then
    echo "Sem o Tkinter o painel não abre. Instale-o e rode o instalar.sh de novo."
    exit 1
fi
TRAY_OK=0
has_tray && TRAY_OK=1
[ "$TRAY_OK" = 1 ] || warn "Bibliotecas do ícone na barra não encontradas: o painel funciona, a bandeja não."
echo "ok"

# ---------------------------------------------------------------- 2. permissao
bold "2/5  Permissão para falar com o mouse (pede sua senha)"
sudo install -D -m 644 "$DIR/data/42-logimouse.rules" "$RULE"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=change
echo "ok"

# ---------------------------------------------------------------- 3. arquivos
bold "3/5  Copiando o app"
stop_tray
mkdir -p "$PREFIX" "$(dirname "$BIN")"
rm -rf "$PREFIX/logimouse"
cp -r "$DIR/src/logimouse" "$PREFIX/"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "$BIN"
cat > "$BIN" <<EOF
#!/bin/sh
# Gerado pelo instalar.sh do LogiMouse
PYTHONPATH="$PREFIX\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPATH
exec "$PY" -m logimouse "\$@"
EOF
chmod 755 "$BIN"
echo "ok ($BIN)"

# ---------------------------------------------------------------- 4. menu
bold "4/5  Atalho no menu de aplicativos"
mkdir -p "$(dirname "$DESK")"
cat > "$DESK" <<EOF
[Desktop Entry]
Type=Application
Name=LogiMouse
Comment=Bateria, DPI e roda do mouse Logitech
Exec=$BIN
Icon=input-mouse
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=mouse;logitech;dpi;bateria;battery;
StartupWMClass=logimouse
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$(dirname "$DESK")" || true
echo "ok"

# ---------------------------------------------------------------- 5. bandeja
bold "5/5  Ícone na barra"
if [ "$TRAY_OK" = 1 ]; then
    if ask "Iniciar o LogiMouse junto com o sistema (bateria na barra + reaplicar seus ajustes)?"; then
        "$BIN" --autostart on >/dev/null
        echo "Início com o sistema: ligado"
    else
        "$BIN" --autostart off >/dev/null
    fi
    if command -v setsid >/dev/null 2>&1; then
        setsid -f "$BIN" --tray >/dev/null 2>&1 < /dev/null || true
    else
        nohup "$BIN" --tray >/dev/null 2>&1 &
    fi
    echo "Ícone iniciado."
    case "${XDG_CURRENT_DESKTOP:-}" in
        *ubuntu*|*Ubuntu*) ;;
        *GNOME*)
            if ! gnome-extensions list --enabled 2>/dev/null | grep -qi appindicator; then
                warn "No GNOME, ative a extensão 'AppIndicator and KStatusNotifierItem Support' para ver o ícone."
            fi ;;
    esac
else
    echo "pulado (faltam as bibliotecas)"
fi

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) warn "$HOME/.local/bin não está no seu PATH: abra pelo menu ou rode $BIN" ;;
esac

echo
bold "Pronto! Abra 'LogiMouse' no menu de aplicativos ou rode: logimouse"
echo "Se aparecer 'sem permissão', tire e recoloque o receptor (ou desligue e ligue o mouse)."

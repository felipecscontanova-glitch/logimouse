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
RULE_MACROS=/etc/udev/rules.d/71-logimouse-macros.rules
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/logimouse.svg"
ICON_SYM="$HOME/.local/share/icons/hicolor/symbolic/apps/logimouse-symbolic.svg"
LADSPA="$HOME/.local/lib/ladspa"
RNNOISE_URL="https://github.com/werman/noise-suppression-for-voice/releases/download/v1.10/linux-rnnoise.zip"
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
stop_tray() {
    # fecha so a bandeja do LogiMouse: pelo PID gravado na trava e, se preciso,
    # pelo comando exato (python... -m logimouse --tray)
    local lock pid=""
    lock="${XDG_RUNTIME_DIR:-/tmp}/logimouse-tray-$(id -u).lock"
    [ -r "$lock" ] && pid="$(tr -dc '0-9' < "$lock")"
    if [ -n "$pid" ] && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q -- "-m logimouse --tray"; then
        kill "$pid" 2>/dev/null || true
    fi
    pkill -f -- '^[^ ]*python[^ ]* -m logimouse --tray' 2>/dev/null || true
}

remove() {
    stop_tray
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable --now logimouse-audio.service >/dev/null 2>&1 || true
        rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/logimouse-audio.service"
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
    rm -f "$BIN" "$DESK" "$AUTO" "$ICON" "$ICON_SYM"
    rm -rf "$PREFIX"
    if [ -f "$RULE" ] || [ -f "$RULE_MACROS" ]; then
        sudo rm -f "$RULE" "$RULE_MACROS" && sudo udevadm control --reload-rules
    fi
    [ -f "$LADSPA/librnnoise_ladspa.so" ] && echo "O plugin RNNoise ficou em $LADSPA (apague se quiser)."
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
GTK4_CHECK='
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
gi.require_foreign("cairo")
'
has_tk()     { "$PY" -c 'import tkinter' >/dev/null 2>&1; }
has_gtk4()   { "$PY" -c "$GTK4_CHECK" >/dev/null 2>&1; }
has_tray()   { "$PY" -c "$TRAY_CHECK" >/dev/null 2>&1; }
has_notify() { command -v notify-send >/dev/null 2>&1; }

# ---------------------------------------------------------------- 1. pacotes
bold "1/6  Dependências"
PM=""
for p in apt-get dnf pacman zypper; do command -v "$p" >/dev/null 2>&1 && { PM=$p; break; }; done

PKGS=()
case "$PM" in
    apt-get)
        has_gtk4   || PKGS+=(python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1)
        has_gtk4   || has_tk || PKGS+=(python3-tk)
        has_tray   || PKGS+=(python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1)
        has_notify || PKGS+=(libnotify-bin) ;;
    dnf)
        has_gtk4   || PKGS+=(python3-gobject python3-cairo gtk4 libadwaita)
        has_gtk4   || has_tk || PKGS+=(python3-tkinter)
        has_tray   || PKGS+=(python3-gobject gtk3 libayatana-appindicator-gtk3)
        has_notify || PKGS+=(libnotify) ;;
    pacman)
        has_gtk4   || PKGS+=(python-gobject python-cairo gtk4 libadwaita)
        has_gtk4   || has_tk || PKGS+=(tk)
        has_tray   || PKGS+=(python-gobject gtk3 libayatana-appindicator)
        has_notify || PKGS+=(libnotify) ;;
    zypper)
        has_gtk4   || PKGS+=(python3-gobject python3-gobject-cairo typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1)
        has_gtk4   || has_tk || PKGS+=(python3-tk)
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
    has_gtk4 || warn "Não reconheci seu gerenciador de pacotes. Instale GTK 4, libadwaita e PyGObject (com cairo) manualmente."
fi

if ! has_gtk4; then
    if has_tk; then
        warn "GTK 4 + libadwaita não encontrados: vai abrir o painel antigo (Tkinter)."
    else
        echo "Sem GTK 4 + libadwaita (nem Tkinter) o painel não abre. Instale-os e rode o instalar.sh de novo."
        exit 1
    fi
fi
TRAY_OK=0
has_tray && TRAY_OK=1
[ "$TRAY_OK" = 1 ] || warn "Bibliotecas do ícone na barra não encontradas: o painel funciona, a bandeja não."
echo "ok"

# ---------------------------------------------------------------- 2. permissao
bold "2/6  Permissão para falar com o mouse, o headset e usar macros (pede sua senha)"
sudo install -D -m 644 "$DIR/data/42-logimouse.rules" "$RULE"
sudo install -D -m 644 "$DIR/data/71-logimouse-macros.rules" "$RULE_MACROS"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=change
sudo udevadm trigger --subsystem-match=input --action=change
sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput --action=change
echo "ok"

# ---------------------------------------------------------------- 3. arquivos
bold "3/6  Copiando o app"
stop_tray
mkdir -p "$PREFIX" "$(dirname "$BIN")"
rm -rf "$PREFIX/logimouse"
cp -r "$DIR/src/logimouse" "$PREFIX/"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} +
# marca que esta copia foi instalada aqui e pode se atualizar sozinha pelo GitHub
printf 'instalado pelo instalar.sh em %s\n' "$(date -Iseconds)" > "$PREFIX/.instalado"
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
bold "4/6  Atalho no menu de aplicativos"
install -D -m 644 "$DIR/src/logimouse/assets/logimouse.svg" "$ICON"
install -D -m 644 "$DIR/src/logimouse/assets/logimouse-symbolic.svg" "$ICON_SYM"
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" || true
mkdir -p "$(dirname "$DESK")"
cat > "$DESK" <<EOF
[Desktop Entry]
Type=Application
Name=LogiMouse
Comment=Mouse Logitech e headset MCHOSE: DPI, botões, macros, equalizador e microfone sem ruído
Exec=$BIN
Icon=logimouse
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=mouse;logitech;dpi;bateria;battery;headset;macro;equalizador;ruído;
StartupWMClass=logimouse
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$(dirname "$DESK")" || true
echo "ok"

# ---------------------------------------------------------------- 5. RNNoise
bold "5/6  Redução de ruído por IA do microfone (opcional)"
if [ -f "$LADSPA/librnnoise_ladspa.so" ]; then
    echo "já instalado ($LADSPA)"
elif [ "$(uname -m)" != "x86_64" ]; then
    echo "pulado: o plugin pronto só existe para x86_64"
elif ask "Baixar o plugin RNNoise (rede neural de redução de ruído, ~36 MB, github.com/werman/noise-suppression-for-voice)?"; then
    TMPZ="$(mktemp -d)"
    if curl -fL --retry 2 -o "$TMPZ/rnnoise.zip" "$RNNOISE_URL"; then
        "$PY" - "$TMPZ/rnnoise.zip" "$LADSPA" <<'PYEOF'
import os, sys, zipfile
src, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(src) as z:
    names = [n for n in z.namelist() if n.endswith("/ladspa/librnnoise_ladspa.so")]
    if not names:
        raise SystemExit("plugin não encontrado no arquivo baixado")
    os.makedirs(dest, exist_ok=True)
    with z.open(names[0]) as fh, open(os.path.join(dest, "librnnoise_ladspa.so"), "wb") as out:
        out.write(fh.read())
PYEOF
        echo "ok ($LADSPA/librnnoise_ladspa.so)"
    else
        warn "Não deu para baixar o RNNoise. O resto funciona; rode o instalar.sh de novo depois."
    fi
    rm -rf "$TMPZ"
else
    echo "pulado (o equalizador e o EQ da voz funcionam sem ele)"
fi

# ---------------------------------------------------------------- 6. bandeja
bold "6/6  Ícone na barra"
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
# o servico de som (equalizador/microfone) e recriado pelo painel com o caminho novo
if [ -f "${XDG_CONFIG_HOME:-$HOME/.config}/logimouse/audio.conf" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user try-restart logimouse-audio.service >/dev/null 2>&1 || true
fi

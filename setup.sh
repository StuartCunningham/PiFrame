#!/usr/bin/env bash
# PiFrame setup script for Raspberry Pi OS (Bookworm / Bullseye)
set -e

PIFRAME_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Setting up PiFrame in $PIFRAME_DIR"
echo ""

# ── Detect OS ─────────────────────────────────────────────────────────────────
OS_CODENAME=$(. /etc/os-release 2>/dev/null && echo "${VERSION_CODENAME:-unknown}")
IS_WAYLAND=false
[ "$OS_CODENAME" = "bookworm" ] && IS_WAYLAND=true

echo "Detected OS: Raspberry Pi OS ${OS_CODENAME^}"
[ "$IS_WAYLAND" = "true" ] && echo "Display: Wayland (labwc)" || echo "Display: X11 (LXDE)"
echo ""

# ── System packages ────────────────────────────────────────────────────────────
echo "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y \
    python3 python3-venv python3-pip \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    libfreetype6-dev libjpeg-dev \
    fonts-dejavu-core fonts-freefont-ttf \
    x11-xserver-utils \
    mpv ffmpeg \
    git

# ── Python venv ────────────────────────────────────────────────────────────────
echo "Creating Python virtual environment..."
python3 -m venv "$PIFRAME_DIR/venv"
source "$PIFRAME_DIR/venv/bin/activate"

pip install --upgrade pip -q
pip install -r "$PIFRAME_DIR/requirements.txt" -q
echo "Python dependencies installed."
echo ""

# ── Optional: Inky Impression e-ink display ───────────────────────────────────
read -p "Install Inky Impression e-ink support? [y/N] " eink_answer
if [[ "$eink_answer" =~ ^[Yy]$ ]]; then
    pip install "inky[rpi,fonts]" -q
    sudo raspi-config nonint do_spi 0
    echo "SPI enabled."
fi
echo ""

# ── Photos folder ──────────────────────────────────────────────────────────────
mkdir -p "$PIFRAME_DIR/photos"

# ── secrets.yaml ──────────────────────────────────────────────────────────────
SECRETS_FILE="$PIFRAME_DIR/secrets.yaml"
if [ ! -f "$SECRETS_FILE" ]; then
    echo "Creating secrets.yaml (gitignored — safe to store credentials here)..."
    read -sp "Set a web UI password (leave blank for no password): " WEB_PASSWORD
    echo ""

    export WEB_PASSWORD SECRETS_FILE
    "$PIFRAME_DIR/venv/bin/python3" - <<'PYEOF'
import os, secrets, yaml
data = {
    'web': {
        'secret_key': secrets.token_hex(32),
        'password': os.environ.get('WEB_PASSWORD', ''),
    },
    'overlays': {'weather': {'api_key': ''}},
    'onedrive': {'client_id': ''},
}
with open(os.environ['SECRETS_FILE'], 'w') as f:
    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
PYEOF
    unset WEB_PASSWORD

    echo "secrets.yaml created with a random session secret."
    echo "Add API keys / credentials directly to: $SECRETS_FILE"
else
    echo "secrets.yaml already exists — skipping generation."
fi
echo ""

# ── systemd service ────────────────────────────────────────────────────────────
read -p "Install and enable systemd service (auto-start on boot)? [y/N] " svc_answer
if [[ "$svc_answer" =~ ^[Yy]$ ]]; then
    SERVICE_SRC="$PIFRAME_DIR/service/piframe.service"
    USER_UID=$(id -u "$USER")

    sed \
        -e "s|WorkingDirectory=.*|WorkingDirectory=$PIFRAME_DIR|" \
        -e "s|ExecStart=.*|ExecStart=$PIFRAME_DIR/venv/bin/python $PIFRAME_DIR/run.py|" \
        -e "s|User=.*|User=$USER|" \
        -e "s|/run/user/1000|/run/user/$USER_UID|" \
        "$SERVICE_SRC" | sudo tee /etc/systemd/system/piframe.service > /dev/null

    sudo systemctl daemon-reload
    sudo systemctl enable piframe.service
    echo "Service installed and enabled."
fi
echo ""

# ── Auto-login to desktop ──────────────────────────────────────────────────────
# Required for HDMI display mode — pygame needs an active graphical session.
read -p "Enable auto-login to desktop (required for HDMI mode)? [y/N] " autologin_answer
if [[ "$autologin_answer" =~ ^[Yy]$ ]]; then
    # B4 = auto-login to desktop session
    sudo raspi-config nonint do_boot_behaviour B4
    echo "Auto-login to desktop enabled."
fi
echo ""

# ── Disable screen blanking ────────────────────────────────────────────────────
echo "Disabling screen blanking..."

if [ "$IS_WAYLAND" = "true" ]; then
    # Pi OS Bookworm — Wayland (labwc)
    # xset commands reach the display via XWayland
    LABWC_AUTOSTART="$HOME/.config/labwc/autostart"
    mkdir -p "$(dirname "$LABWC_AUTOSTART")"
    if ! grep -q "xset s off" "$LABWC_AUTOSTART" 2>/dev/null; then
        cat >> "$LABWC_AUTOSTART" <<'EOF'
xset s off
xset -dpms
xset s noblank
EOF
        echo "Screen blanking disabled (labwc autostart)."
    else
        echo "Screen blanking already configured."
    fi
else
    # Pi OS Bullseye — X11 (LXDE)
    AUTOSTART="/etc/xdg/lxsession/LXDE-pi/autostart"
    if [ -f "$AUTOSTART" ]; then
        if ! grep -q "xset s off" "$AUTOSTART" 2>/dev/null; then
            echo "@xset s off"    | sudo tee -a "$AUTOSTART" > /dev/null
            echo "@xset -dpms"   | sudo tee -a "$AUTOSTART" > /dev/null
            echo "@xset s noblank" | sudo tee -a "$AUTOSTART" > /dev/null
            echo "Screen blanking disabled (LXDE autostart)."
        else
            echo "Screen blanking already configured."
        fi
    fi
fi
echo ""

# ── Optional: passwordless reboot for web UI ──────────────────────────────────
read -p "Allow restart and reboot from the web UI without a sudo password? [y/N] " reboot_answer
if [[ "$reboot_answer" =~ ^[Yy]$ ]]; then
    SYSTEMCTL="$(which systemctl)"
    SUDOERS_FILE=/etc/sudoers.d/piframe
    {
        echo "$USER ALL=(ALL) NOPASSWD: $SYSTEMCTL restart piframe"
        echo "$USER ALL=(ALL) NOPASSWD: $SYSTEMCTL reboot"
    } | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 0440 "$SUDOERS_FILE"
    echo "Sudoers rules added for restart and reboot."
fi
echo ""

# ── Done ──────────────────────────────────────────────────────────────────────
PI_IP=$(hostname -I | awk '{print $1}')

echo "========================================"
echo " PiFrame setup complete!"
echo "========================================"
echo ""
echo "Configuration files:"
echo "  config.yaml    — general settings (tracked in git)"
echo "  secrets.yaml   — credentials (gitignored, safe to edit)"
echo ""
echo "Add credentials to secrets.yaml:"
echo "  onedrive.client_id   — Azure app registration ID"
echo "  overlays.weather.api_key — OpenWeatherMap key"
echo "  web.password         — web UI login password"
echo ""
if [[ "$svc_answer" =~ ^[Yy]$ ]]; then
    echo "Start PiFrame:"
    echo "  sudo systemctl start piframe"
    echo "  journalctl -u piframe -f   # follow logs"
else
    echo "Run PiFrame manually:"
    echo "  source venv/bin/activate && python run.py"
fi
echo ""
echo "Web UI: http://${PI_IP}:8080"
echo ""
if [[ "$autologin_answer" =~ ^[Yy]$ ]]; then
    echo "NOTE: Reboot to apply auto-login before starting PiFrame."
    echo "  sudo reboot"
fi

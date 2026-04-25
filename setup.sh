#!/usr/bin/env bash
# PiFrame setup script for Raspberry Pi OS (Bookworm/Bullseye)
set -e

PIFRAME_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Setting up PiFrame in $PIFRAME_DIR"

# ── System packages ────────────────────────────────────────────────────────────
echo "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y \
    python3 python3-venv python3-pip \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    libfreetype6-dev libjpeg-dev \
    fonts-dejavu-core \
    git

# ── Python venv ────────────────────────────────────────────────────────────────
echo "Creating Python virtual environment..."
python3 -m venv "$PIFRAME_DIR/venv"
source "$PIFRAME_DIR/venv/bin/activate"

pip install --upgrade pip
pip install -r "$PIFRAME_DIR/requirements.txt"

# ── Optional: Inky Impression e-ink display ───────────────────────────────────
read -p "Install Inky Impression e-ink support? [y/N] " eink_answer
if [[ "$eink_answer" =~ ^[Yy]$ ]]; then
    pip install "inky[rpi,fonts]"
    # Enable SPI
    sudo raspi-config nonint do_spi 0
    echo "SPI enabled. Reboot may be required."
fi

# ── Photos folder ──────────────────────────────────────────────────────────────
mkdir -p "$PIFRAME_DIR/photos"

# ── systemd service ────────────────────────────────────────────────────────────
read -p "Install and enable systemd service (auto-start on boot)? [y/N] " svc_answer
if [[ "$svc_answer" =~ ^[Yy]$ ]]; then
    SERVICE_FILE="$PIFRAME_DIR/service/piframe.service"

    # Patch the service file with real paths
    sed \
        -e "s|WorkingDirectory=.*|WorkingDirectory=$PIFRAME_DIR|" \
        -e "s|ExecStart=.*|ExecStart=$PIFRAME_DIR/venv/bin/python $PIFRAME_DIR/run.py|" \
        -e "s|User=pi|User=$USER|" \
        "$SERVICE_FILE" | sudo tee /etc/systemd/system/piframe.service > /dev/null

    sudo systemctl daemon-reload
    sudo systemctl enable piframe.service
    echo "Service installed. Start with: sudo systemctl start piframe"
fi

# ── HDMI: disable screen blank/screensaver ────────────────────────────────────
AUTOSTART="/etc/xdg/lxsession/LXDE-pi/autostart"
if [ -f "$AUTOSTART" ]; then
    if ! grep -q "xset s off" "$AUTOSTART" 2>/dev/null; then
        echo "@xset s off" | sudo tee -a "$AUTOSTART" > /dev/null
        echo "@xset -dpms" | sudo tee -a "$AUTOSTART" > /dev/null
        echo "@xset s noblank" | sudo tee -a "$AUTOSTART" > /dev/null
        echo "Screen blanking disabled."
    fi
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit config.yaml to match your preferences"
echo "  2. If using OneDrive, register an Azure app and paste the client ID"
echo "     into config.yaml (or via the web UI after starting)"
echo "  3. Run: source venv/bin/activate && python run.py"
echo "  4. Open http://$(hostname -I | awk '{print $1}'):8080 on any device"

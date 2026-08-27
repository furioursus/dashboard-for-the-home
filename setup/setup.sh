#!/usr/bin/env bash
# Office Pi Dashboard - one-shot kiosk setup.
#
# Target: Raspberry Pi OS Lite (64-bit), freshly flashed, run as the `pi`
# user (or edit RUN_USER below). Handles everything that *can* be
# automated; the manual one-time steps that can't (Hue press-link pairing,
# Bambu access code, CalDAV app password, filling in .env/config.yaml) are
# printed at the end and covered in the top-level README.
#
# Usage (from the repo root, after cloning to ~/dashboard-for-the-home):
#   chmod +x setup/setup.sh && ./setup/setup.sh
set -euo pipefail

RUN_USER="${SUDO_USER:-$(whoami)}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Office Pi Dashboard setup"
echo "    user: $RUN_USER"
echo "    home: $RUN_HOME"
echo "    repo: $REPO_DIR"
echo

if [ "$REPO_DIR" != "$RUN_HOME/dashboard-for-the-home" ]; then
  echo "NOTE: repo is not at $RUN_HOME/dashboard-for-the-home."
  echo "The systemd unit files assume that path - edit setup/dashboard-backend.service"
  echo "and setup/kiosk-chromium.service if you keep it elsewhere."
  echo
fi

echo "==> Installing packages (apt)"
sudo apt-get update
sudo apt-get install -y \
  xserver-xorg \
  xinit \
  openbox \
  chromium-browser \
  unclutter \
  python3 \
  python3-venv \
  python3-pip

echo "==> Enabling console autologin on tty1 (raspi-config)"
if command -v raspi-config >/dev/null 2>&1; then
  sudo raspi-config nonint do_boot_behavior B2
else
  echo "raspi-config not found - enable console autologin on tty1 manually."
fi

echo "==> Python virtualenv + backend dependencies"
cd "$REPO_DIR/backend"
python3 -m venv .venv
"$REPO_DIR/backend/.venv/bin/pip" install --upgrade pip
"$REPO_DIR/backend/.venv/bin/pip" install -r requirements.txt
cd "$REPO_DIR"

echo "==> Installing kiosk X session files"
install -m 644 "$REPO_DIR/setup/.xinitrc" "$RUN_HOME/.xinitrc"

BASH_PROFILE="$RUN_HOME/.bash_profile"
touch "$BASH_PROFILE"
if ! grep -q "office-pi-dashboard: start X on tty1" "$BASH_PROFILE" 2>/dev/null; then
  {
    echo ""
    echo "# office-pi-dashboard: start X on tty1"
    cat "$REPO_DIR/setup/bash_profile.append"
  } >> "$BASH_PROFILE"
  echo "    appended startx block to $BASH_PROFILE"
else
  echo "    $BASH_PROFILE already has the startx block, skipping"
fi

echo "==> Installing systemd units"
sudo sed "s#/home/pi#$RUN_HOME#g; s#User=pi#User=$RUN_USER#g" \
  "$REPO_DIR/setup/dashboard-backend.service" \
  | sudo tee /etc/systemd/system/dashboard-backend.service >/dev/null

mkdir -p "$RUN_HOME/.config/systemd/user"
install -m 644 "$REPO_DIR/setup/kiosk-chromium.service" \
  "$RUN_HOME/.config/systemd/user/kiosk-chromium.service"

sudo systemctl daemon-reload
sudo systemctl enable dashboard-backend.service

# Let the user's systemd --user instance (and therefore kiosk-chromium.service)
# start at boot without needing an interactive login session first.
sudo loginctl enable-linger "$RUN_USER"
sudo -u "$RUN_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$RUN_USER")" \
  systemctl --user daemon-reload
sudo -u "$RUN_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$RUN_USER")" \
  systemctl --user enable kiosk-chromium.service

echo
echo "==> Done with automated setup."
echo
echo "Still needed before this is usable (all manual, one-time):"
echo "  1. cp .env.example .env            and fill in every value"
echo "  2. cp config.yaml.example config.yaml   and adjust room/group settings"
echo "  3. Hue bridge pairing: press the bridge's link button, then run"
echo "       python3 setup/pair_hue.py <bridge-ip>"
echo "     and copy the printed HUE_BRIDGE_IP / HUE_API_KEY into .env."
echo "  4. Fastmail app password: Settings -> Privacy & Security -> Integrations"
echo "     -> App passwords (grant Calendar access) -> put it in CALDAV_APP_PASSWORD."
echo "  5. Bambu P1S: enable LAN Only Mode (Settings -> WLAN on the printer's"
echo "     touchscreen) and copy the Access Code + Serial shown there into .env."
echo
echo "Then reboot. tty1 will autologin, startx will bring up openbox, and"
echo "systemd will start the backend + Chromium kiosk automatically."

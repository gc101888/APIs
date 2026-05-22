#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/gc101888/trading-engine.git"
INSTALL_DIR="/opt/trading-engine"
SERVICE_USER="trading"

echo "=============================="
echo "  Trading Engine — VPS Setup  "
echo "=============================="
echo ""

# Must run as root
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Run this script as root (sudo ./setup.sh)"
  exit 1
fi

echo "[1/8] Updating system packages..."
apt-get update -y
apt-get upgrade -y

echo "[2/8] Installing Python 3.12, pip, git..."
apt-get install -y python3.12 python3.12-venv python3.12-dev python3-pip git curl

# Ensure python3 points to 3.12
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 || true

echo "[3/8] Cloning repository..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "  Repo exists — pulling latest from main..."
  git -C "$INSTALL_DIR" fetch origin
  git -C "$INSTALL_DIR" checkout main
  git -C "$INSTALL_DIR" pull origin main
else
  git clone --branch main "$REPO_URL" "$INSTALL_DIR"
fi

echo "[4/8] Creating virtual environment..."
python3 -m venv "$INSTALL_DIR/.venv"

echo "[5/8] Installing Python dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "[6/8] Setting up environment file..."
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  echo ""
  echo "  ⚠️  IMPORTANT: Edit $INSTALL_DIR/.env with your API keys before starting."
  echo ""
else
  echo "  .env already exists — skipping copy"
fi

echo "[7/8] Creating service user and setting permissions..."
if ! id "$SERVICE_USER" &>/dev/null; then
  useradd --system --no-create-home --shell /bin/false "$SERVICE_USER"
  echo "  Created user: $SERVICE_USER"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "[8/8] Installing and enabling systemd service..."
cp "$INSTALL_DIR/deploy/trading-engine.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable trading-engine

echo ""
echo "=============================="
echo "  Setup Complete!             "
echo "=============================="
echo ""
echo "Next steps:"
echo "  1. Fill in your API keys:"
echo "       nano $INSTALL_DIR/.env"
echo ""
echo "  2. Start the service:"
echo "       systemctl start trading-engine"
echo ""
echo "  3. Check it's running:"
echo "       systemctl status trading-engine"
echo ""
echo "  4. Follow live logs:"
echo "       journalctl -u trading-engine -f"
echo ""

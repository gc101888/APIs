#!/bin/bash
# ============================================================
#  Trading Engine — VPS Setup Script
#  Ubuntu 24.04 LTS
#
#  Usage (as root):
#    curl -fsSL https://raw.githubusercontent.com/gc101888/APIs/main/deploy/setup.sh | bash
#  Or:
#    chmod +x setup.sh && sudo ./setup.sh
# ============================================================
set -euo pipefail

REPO_URL="https://github.com/gc101888/APIs.git"
REPO_BRANCH="main"
INSTALL_DIR="/opt/trading-engine"
SERVICE_USER="trading"
SERVICE_FILE="trading-engine.service"
LOG_FILE="/var/log/trading-engine-setup.log"

# ── Colours ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC}  $*"; }
info() { echo -e "${BLUE}→${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
die()  { echo -e "${RED}✗  ERROR: $*${NC}"; exit 1; }

# ── Header ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Trading Engine — VPS Setup v1.0   ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""

# Log everything
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Root check ─────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Run as root: sudo $0"

# ── 1. System packages ─────────────────────────────────────
echo -e "\n${BOLD}[1/8] System packages${NC}"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3.12-dev \
    python3-pip git curl ca-certificates \
    build-essential libssl-dev libffi-dev \
    2>/dev/null
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 &>/dev/null || true
ok "Python $(python3 --version), git $(git --version | awk '{print $3}')"

# ── 2. Clone / update repo ─────────────────────────────────
echo -e "\n${BOLD}[2/8] Repository${NC}"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Existing install found — pulling latest..."
    git -C "$INSTALL_DIR" fetch origin
    git -C "$INSTALL_DIR" checkout "$REPO_BRANCH"
    git -C "$INSTALL_DIR" pull origin "$REPO_BRANCH"
    ok "Repository updated"
else
    info "Cloning $REPO_URL (branch: $REPO_BRANCH)..."
    git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    ok "Repository cloned to $INSTALL_DIR"
fi

# ── 3. Virtual environment ─────────────────────────────────
echo -e "\n${BOLD}[3/8] Python virtual environment${NC}"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    python3 -m venv "$INSTALL_DIR/.venv"
    ok "Virtual environment created"
else
    ok "Virtual environment exists"
fi

# ── 4. Python dependencies ─────────────────────────────────
echo -e "\n${BOLD}[4/8] Python dependencies${NC}"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip --quiet
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet
ok "All packages installed"

# ── 5. Environment file ────────────────────────────────────
echo -e "\n${BOLD}[5/8] Environment configuration${NC}"
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    warn ".env created from template — you MUST fill in your API keys before starting!"
    warn "Run:  nano $INSTALL_DIR/.env"
else
    ok ".env already exists"
fi

# ── 6. Service user ────────────────────────────────────────
echo -e "\n${BOLD}[6/8] Service user${NC}"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /bin/false "$SERVICE_USER"
    ok "User '$SERVICE_USER' created"
else
    ok "User '$SERVICE_USER' already exists"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 750 "$INSTALL_DIR"
ok "Permissions set"

# ── 7. Log directory ───────────────────────────────────────
echo -e "\n${BOLD}[7/8] Log directory${NC}"
mkdir -p /var/log/trading-engine
chown "$SERVICE_USER:$SERVICE_USER" /var/log/trading-engine
ok "/var/log/trading-engine ready"

# ── 8. Systemd service ─────────────────────────────────────
echo -e "\n${BOLD}[8/8] Systemd service${NC}"
cp "$INSTALL_DIR/deploy/$SERVICE_FILE" /etc/systemd/system/
systemctl daemon-reload
systemctl enable trading-engine
ok "Service installed and enabled (not started yet)"

# ── Summary ────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║           Setup Complete!            ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""

# Check if .env is still the template (empty keys)
if grep -q "^GEMINI_API_KEY=$" "$INSTALL_DIR/.env" 2>/dev/null; then
    echo -e "${YELLOW}⚠  REQUIRED: Your .env still has empty keys.${NC}"
    echo -e "   Fill in ALL values before starting:\n"
    echo -e "   ${BOLD}nano $INSTALL_DIR/.env${NC}\n"
    echo "   Keys needed:"
    echo "     GEMINI_API_KEY      — aistudio.google.com (free)"
    echo "     SUPABASE_URL        — your Supabase project URL"
    echo "     SUPABASE_KEY        — your Supabase anon key"
    echo "     TELEGRAM_BOT_TOKEN  — from @BotFather"
    echo "     TELEGRAM_CHAT_ID    — your Telegram user/chat ID"
    echo ""
fi

echo "  Once .env is filled in, run:"
echo ""
echo -e "    ${BOLD}systemctl start trading-engine${NC}       # start now"
echo -e "    ${BOLD}systemctl status trading-engine${NC}      # check status"
echo -e "    ${BOLD}journalctl -u trading-engine -f${NC}      # live logs"
echo ""
echo "  To run the test pipeline first (recommended):"
echo ""
echo -e "    ${BOLD}cd $INSTALL_DIR${NC}"
echo -e "    ${BOLD}sudo -u $SERVICE_USER .venv/bin/python test_pipeline.py${NC}"
echo ""
echo -e "  Dashboard: ${BLUE}https://gc101888.github.io/APIs/${NC}"
echo ""
echo "  Setup log: $LOG_FILE"
echo ""

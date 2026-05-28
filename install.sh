#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────
# CityBot2 Installer
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/ericrosenberg1/CityBot2/main/install.sh | sudo bash
#
# Options (env vars):
#   CITYBOT_DIR      Install directory       (default: /opt/citybot2)
#   CITYBOT_PORT     Web UI port             (default: 8080)
#   CITYBOT_DOMAIN   Domain name             (e.g. ventura.news — enables HTTPS)
#   CITYBOT_METHOD   "docker" or "native"    (default: auto-detect)
#   TZ               Timezone                (default: America/Los_Angeles)
# ──────────────────────────────────────────────────────────────────────

REPO="https://github.com/ericrosenberg1/CityBot2.git"
DIR="${CITYBOT_DIR:-/opt/citybot2}"
PORT="${CITYBOT_PORT:-8080}"
DOMAIN="${CITYBOT_DOMAIN:-}"
TZ_VAL="${TZ:-America/Los_Angeles}"

# Colors
G='\033[0;32m'; B='\033[0;34m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'
info()  { echo -e "${B}>>>${N} $*"; }
ok()    { echo -e "${G} ✓${N}  $*"; }
warn()  { echo -e "${Y} !${N}  $*"; }
fail()  { echo -e "${R} ✗${N}  $*"; exit 1; }

[[ $EUID -eq 0 ]] || fail "Run with sudo:  curl … | sudo bash"

echo ""
echo -e "${G}  ╔═══════════════════════════════╗${N}"
echo -e "${G}  ║      CityBot2  Installer      ║${N}"
echo -e "${G}  ╚═══════════════════════════════╝${N}"
echo ""

# ── Decide method ────────────────────────────────────────────────────
METHOD="${CITYBOT_METHOD:-}"
if [[ -z "$METHOD" ]]; then
    if command -v docker &>/dev/null; then
        METHOD="docker"
    else
        METHOD="native"
    fi
fi

# ── Clone / update repo ─────────────────────────────────────────────
if [[ -d "$DIR/.git" ]]; then
    info "Updating $DIR …"
    git -C "$DIR" pull --ff-only 2>/dev/null || warn "git pull failed — using existing"
else
    info "Cloning CityBot2 → $DIR"
    git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"

# ── Docker install ───────────────────────────────────────────────────
if [[ "$METHOD" == "docker" ]]; then
    # Ensure docker compose is available
    if ! docker compose version &>/dev/null 2>&1; then
        info "Installing Docker Compose plugin …"
        apt-get update -qq && apt-get install -y -qq docker-compose-plugin >/dev/null 2>&1 \
            || fail "Could not install docker-compose-plugin. Install Docker first: https://docs.docker.com/engine/install/"
    fi

    # Write .env
    cat > .env <<EOF
CITYBOT_PORT=$PORT
CITYBOT_MODE=all
TZ=$TZ_VAL
CITYBOT_DOMAIN=$DOMAIN
EOF

    info "Building image …"
    docker compose build --quiet

    # Start with or without Caddy
    if [[ -n "$DOMAIN" ]]; then
        info "Domain: $DOMAIN — starting with Caddy for automatic HTTPS"
        docker compose --profile caddy up -d
        SETUP_URL="https://${DOMAIN}/setup"
    else
        info "No domain set — starting without reverse proxy"
        docker compose up -d
        IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
        SETUP_URL="http://${IP}:${PORT}/setup"
    fi

    echo ""
    ok "CityBot2 is running!"
    echo ""
    echo -e "  ${G}Setup:${N}     ${SETUP_URL}"
    echo -e "  ${G}Logs:${N}      docker compose -f ${DIR}/docker-compose.yml logs -f"
    echo -e "  ${G}Stop:${N}      docker compose -f ${DIR}/docker-compose.yml down"
    echo -e "  ${G}Restart:${N}   docker compose -f ${DIR}/docker-compose.yml restart"
    echo -e "  ${G}Update:${N}    cd ${DIR} && git pull && docker compose up -d --build"
    echo ""
    if [[ -n "$DOMAIN" ]]; then
        echo "  HTTPS is handled automatically by Caddy + Let's Encrypt."
        echo "  Make sure DNS for ${DOMAIN} points to this server."
    else
        echo "  To add a domain later:"
        echo "    CITYBOT_DOMAIN=yourdomain.com docker compose --profile caddy up -d"
    fi
    echo ""
    exit 0
fi

# ── Native install ───────────────────────────────────────────────────
info "Installing without Docker …"

# Packages
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-dev git \
        gcc g++ libgeos-dev libproj-dev proj-data proj-bin libffi-dev >/dev/null 2>&1
elif command -v dnf &>/dev/null; then
    dnf install -y -q python3 python3-devel git gcc gcc-c++ \
        geos-devel proj-devel libffi-devel >/dev/null 2>&1
else
    fail "Need apt or dnf."
fi
ok "System packages"

# User
id citybot &>/dev/null || useradd --system --shell /usr/sbin/nologin --home-dir "$DIR" citybot
ok "Service user"

# Venv
python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt"
ok "Python environment"

mkdir -p data config/cities logs cache/weather_maps cache/maps
chown -R citybot:citybot "$DIR"

# Systemd
cat > /etc/systemd/system/citybot2.service <<EOF
[Unit]
Description=CityBot2
After=network.target

[Service]
Type=simple
User=citybot
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python -m citybot
Restart=on-failure
RestartSec=5
Environment=CITYBOT_PORT=$PORT
Environment=CITYBOT_MODE=all
Environment=CITYBOT_DOMAIN=$DOMAIN
Environment=TZ=$TZ_VAL
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$DIR/data $DIR/logs $DIR/cache $DIR/config

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now citybot2
ok "Systemd service"

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
if [[ -n "$DOMAIN" ]]; then
    SETUP_URL="https://${DOMAIN}/setup"
else
    SETUP_URL="http://${IP}:${PORT}/setup"
fi
echo ""
ok "CityBot2 is running!"
echo ""
echo -e "  ${G}Setup:${N}     ${SETUP_URL}"
echo -e "  ${G}Logs:${N}      journalctl -u citybot2 -f"
echo -e "  ${G}Restart:${N}   systemctl restart citybot2"
echo -e "  ${G}Update:${N}    cd ${DIR} && git pull && systemctl restart citybot2"
echo ""
if [[ -n "$DOMAIN" ]]; then
    echo "  For HTTPS, set up a reverse proxy (Caddy/nginx) pointing to port ${PORT}."
fi
echo ""

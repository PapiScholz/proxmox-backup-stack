#!/usr/bin/env bash
# Instala SOLO el dashboard de backups, sin Ansible, en un Debian fresco.
#
# Uso (como root, dentro del CT/VM que va a servir el dashboard):
#   cp dashboard.env.example dashboard.env   # y completar los tokens
#   bash scripts/bootstrap-dashboard.sh [ruta/a/dashboard.env]
#
# Idempotente: re-correrlo reinstala los mismos archivos y reinicia el timer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${1:-$REPO_DIR/dashboard.env}"

APP_DIR=/opt/backup-dashboard
CONF_DIR=/etc/backup-dashboard
UNIT_DIR=/etc/systemd/system

log() { printf '[bootstrap] %s\n' "$*"; }
die() { printf '[bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "correr como root"
[ -f "$ENV_FILE" ] || die "no existe $ENV_FILE (copiar dashboard.env.example y completarlo)"
[ -f "$REPO_DIR/dashboard/collector.py" ] || die "no encuentro dashboard/collector.py junto al script"

set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a

for var in PVE_HOST PVE_TOKEN_ID PVE_TOKEN_SECRET PBS_HOST PBS_TOKEN_ID PBS_TOKEN_SECRET PBS_STORE; do
    [ -n "${!var:-}" ] || die "falta $var en $ENV_FILE"
done
for var in PVE_CA_FILE PBS_CA_FILE; do
    if [ -n "${!var:-}" ] && [ ! -r "${!var}" ]; then
        die "$var apunta a ${!var}, que no existe o no se puede leer"
    fi
done

REFRESH_MINUTES="${REFRESH_MINUTES:-5}"
case "$REFRESH_MINUTES" in
    ''|*[!0-9]*) die "REFRESH_MINUTES tiene que ser un entero de minutos" ;;
esac
OUTPUT="${OUTPUT:-/var/www/html/index.html}"

missing=()
for pkg in python3 nginx; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [ "${#missing[@]}" -gt 0 ]; then
    log "instalando paquetes: ${missing[*]}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends "${missing[@]}"
else
    log "paquetes ya instalados"
fi

log "instalando colector y units"
install -D -m 0755 "$REPO_DIR/dashboard/collector.py" "$APP_DIR/collector.py"
install -m 0644 "$REPO_DIR/dashboard/backup-dashboard.service" "$UNIT_DIR/backup-dashboard.service"
install -m 0644 "$REPO_DIR/dashboard/backup-dashboard.timer" "$UNIT_DIR/backup-dashboard.timer"
install -d -m 0700 "$CONF_DIR"
install -m 0600 "$ENV_FILE" "$CONF_DIR/dashboard.env"
install -d -m 0755 "$(dirname "$OUTPUT")"

install -d -m 0755 "$UNIT_DIR/backup-dashboard.timer.d"
cat > "$UNIT_DIR/backup-dashboard.timer.d/interval.conf" <<EOF
[Timer]
OnUnitActiveSec=
OnUnitActiveSec=${REFRESH_MINUTES}min
EOF

systemctl daemon-reload
systemctl enable --now nginx >/dev/null 2>&1
systemctl enable backup-dashboard.timer >/dev/null 2>&1
systemctl restart backup-dashboard.timer

log "primera corrida del colector"
systemctl start backup-dashboard.service || die "el colector fallo: journalctl -u backup-dashboard.service"

if [ -s "$OUTPUT" ] && grep -q "class='banner'" "$OUTPUT"; then
    log "AVISO: el dashboard se genero con errores; revisar el banner de la pagina"
    grep -o "<div class='banner'>[^<]*" "$OUTPUT" | sed 's/<div class=.banner.>/  - /' >&2 || true
fi

ip_addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
log "listo: http://${ip_addr:-<ip-del-ct>}/  (timer cada ${REFRESH_MINUTES} min)"

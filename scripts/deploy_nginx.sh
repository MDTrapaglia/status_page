#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_SRC="${ROOT_DIR}/configs/nginx/matiastrapaglia_status.conf"
SITE_DST="/etc/nginx/sites-available/matiastrapaglia_status.conf"
SITE_LINK="/etc/nginx/sites-enabled/matiastrapaglia_status.conf"

if [[ ! -f "${SITE_SRC}" ]]; then
  echo "Config file not found: ${SITE_SRC}" >&2
  exit 1
fi

echo "[nginx] Copying config to ${SITE_DST}"
sudo cp "${SITE_SRC}" "${SITE_DST}"

echo "[nginx] Enabling site ${SITE_LINK}"
sudo ln -sf "${SITE_DST}" "${SITE_LINK}"

echo "[nginx] Testing configuration"
sudo nginx -t

echo "[nginx] Reloading nginx"
sudo systemctl reload nginx

echo "Done. Verify with: curl -I https://matiastrapaglia.space/status/"

#!/usr/bin/env bash
# Instala o agente como serviço do systemd: liga junto com a máquina e religa sozinho se cair.
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
USUARIO="${SUDO_USER:-$USER}"
DESTINO=/etc/systemd/system/empresa-auto.service

if [ ! -x "$RAIZ/.venv/bin/python" ]; then
  echo "Ambiente virtual não encontrado. Rode ./install.sh primeiro."
  exit 1
fi

sed -e "s|USUARIO|$USUARIO|g" -e "s|CAMINHO|$RAIZ|g" "$RAIZ/deploy/empresa-auto.service" | sudo tee "$DESTINO" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now empresa-auto.service

echo "Serviço instalado e iniciado."
echo "Situação:   systemctl status empresa-auto"
echo "Registros:  journalctl -u empresa-auto -f"
echo "Parar:      sudo systemctl stop empresa-auto"

#!/usr/bin/env bash
# Instalador da Empresa Automática para Linux.
#
#   ./install.sh            instala o agente e o navegador
#   ./install.sh --ollama   também instala o Ollama e baixa o modelo padrão
#
# Variável opcional: EA_MODELO (padrão: qwen3:8b)
set -euo pipefail

cd "$(dirname "$0")"
MODELO="${EA_MODELO:-qwen3:8b}"
COM_OLLAMA=0
[ "${1:-}" = "--ollama" ] && COM_OLLAMA=1

dizer() { printf '\n== %s\n' "$1"; }

dizer "Conferindo o Python"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 não encontrado. Instale o Python 3.10 ou mais novo (ex.: sudo apt install python3 python3-venv)."
  exit 1
fi
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python {sys.version.split()[0]} é antigo demais. É necessário 3.10 ou mais novo.")
print(f"Python {sys.version.split()[0]}")
PY
command -v git >/dev/null 2>&1 || echo "Aviso: git não encontrado. Instale-o (ex.: sudo apt install git): o agente usa git para publicar código."

dizer "Criando o ambiente virtual e instalando o agente"
python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .

dizer "Instalando o navegador Chromium"
if ! .venv/bin/python -m playwright install --with-deps chromium; then
  echo "Não foi possível instalar as bibliotecas de sistema (talvez falte sudo). Tentando só o navegador."
  .venv/bin/python -m playwright install chromium
fi

if [ "$COM_OLLAMA" = "1" ]; then
  if ! command -v ollama >/dev/null 2>&1; then
    dizer "Instalando o Ollama"
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  dizer "Baixando o modelo $MODELO (pode demorar)"
  ollama pull "$MODELO"
elif ! command -v ollama >/dev/null 2>&1; then
  echo
  echo "O Ollama não está instalado. Instale com:  curl -fsSL https://ollama.com/install.sh | sh"
  echo "ou rode este instalador novamente com:     ./install.sh --ollama"
fi

dizer "Pronto"
cat <<FIM
Verifique a máquina:   .venv/bin/python -m empresa_auto verificar
Ligue o agente:        .venv/bin/python -m empresa_auto
Ligar junto com o sistema (systemd):   ./deploy/instalar-servico.sh
FIM

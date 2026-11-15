#!/usr/bin/env bash
# Instalador da Empresa Automática para Linux.
#
#   ./install.sh              instala o agente e o navegador
#   ./install.sh --ollama     também instala o Ollama e baixa o modelo padrão
#   ./install.sh --completo   também instala os programas usados pelas habilidades de mídia,
#                             dados e infraestrutura (ffmpeg, ImageMagick, SoX, Node.js, uv e outros)
#   As opções podem ser combinadas: ./install.sh --ollama --completo
#
# Variável opcional: EA_MODELO (padrão: qwen3:8b)
set -euo pipefail

cd "$(dirname "$0")"
MODELO="${EA_MODELO:-qwen3:8b}"
COM_OLLAMA=0
COMPLETO=0
for opcao in "$@"; do
  case "$opcao" in
    --ollama) COM_OLLAMA=1 ;;
    --completo) COMPLETO=1 ;;
    *) echo "Opção desconhecida: $opcao"; exit 1 ;;
  esac
done

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

if [ "$COMPLETO" = "1" ]; then
  dizer "Instalando os programas do perfil completo"
  PACOTES="ffmpeg imagemagick sox jq sqlite3 pandoc nodejs npm inkscape fonts-inter fonts-noto-core"
  if command -v apt-get >/dev/null 2>&1; then
    SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
    $SUDO apt-get update -qq || true
    for pacote in $PACOTES; do
      $SUDO apt-get install -y -qq "$pacote" >/dev/null 2>&1 && echo "  ok     $pacote" || echo "  falhou $pacote (instale manualmente se precisar)"
    done
  else
    echo "Gerenciador apt não encontrado. Instale manualmente: $PACOTES"
  fi
  # uv: instala ferramentas Python isoladas (uv tool install) e roda extensões com uvx
  .venv/bin/python -m pip install --quiet uv && mkdir -p "$HOME/.local/bin" && ln -sf "$PWD/.venv/bin/uv" "$HOME/.local/bin/uv" && ln -sf "$PWD/.venv/bin/uvx" "$HOME/.local/bin/uvx" && echo "  ok     uv"
  echo "As demais ferramentas (voz, transcrição, remoção de fundo, yt-dlp, verificadores de segurança) são"
  echo "instaladas pelo próprio agente quando uma tarefa precisar, seguindo as habilidades."
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

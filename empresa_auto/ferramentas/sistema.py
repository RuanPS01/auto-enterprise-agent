"""Ferramentas de terminal e de arquivos."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

from .base import Ambiente, Catalogo, P, limitar

EH_WINDOWS = sys.platform.startswith("win")

# Barreira mínima contra comandos que destruiriam a própria máquina do agente.
# Não é uma caixa de areia: rode o agente em uma máquina ou usuário dedicado.
_PROIBIDOS = [
    r"\brm\s+(?:-\S+\s+)*-\S*[rR]\S*\s+(?:-\S+\s+)*(?:/|~|\$HOME|/\*)(?:\s|$|[;&|])",
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\s+[^|;&]*of=/dev/(sd|nvme|vd|hd|mmcblk)",
    r"\b(shutdown|reboot|poweroff|halt)\b",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r"\bformat\s+[a-zA-Z]:",
    r"\b(del|rd|rmdir)\s+(/[sSqQ]\s+)+[cC]:\\\s*($|[&|])",
    r">\s*/dev/(sd|nvme|vd|hd)",
]


def comando_proibido(comando: str) -> bool:
    return any(re.search(padrao, comando) for padrao in _PROIBIDOS)


def linha_de_comando(comando: str) -> list[str]:
    """Monta a chamada do interpretador adequado ao sistema operacional."""
    if EH_WINDOWS:
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando]
    bash = shutil.which("bash")
    return [bash, "-lc", comando] if bash else ["/bin/sh", "-c", comando]


# Programas que as habilidades usam. O agente informa ao modelo quais existem nesta máquina.
PROGRAMAS_UTEIS = [
    "git", "gh", "node", "npm", "npx", "python3", "uv", "uvx", "docker", "ffmpeg", "magick", "convert", "inkscape",
    "sox", "blender", "pandoc", "soffice", "sqlite3", "psql", "jq", "curl", "rsync", "cloudflared", "caddy",
    "semgrep", "gitleaks", "trivy", "markitdown", "rembg", "manim", "postiz", "whisper-cli", "java",
]
_cache_ambiente: tuple[float, dict] | None = None


def _pastas_extras_do_path() -> list[str]:
    """Pastas onde ferramentas instaladas pelo próprio agente costumam ficar (uv tool, pip --user, npm -g)."""
    casa = Path.home()
    candidatas = [casa / ".local" / "bin", casa / ".cargo" / "bin", casa / ".npm-global" / "bin"]
    return [str(c) for c in candidatas if c.is_dir()]


def inspecionar_ambiente(validade: float = 600) -> dict:
    """Descobre o que a máquina oferece: programas, permissão de instalar pacotes e placa de vídeo."""
    global _cache_ambiente
    if _cache_ambiente is not None and time.time() - _cache_ambiente[0] < validade:
        return _cache_ambiente[1]
    caminho = os.pathsep.join(_pastas_extras_do_path() + [os.environ.get("PATH", "")])
    presentes = [nome for nome in PROGRAMAS_UTEIS if shutil.which(nome, path=caminho)]
    pode_instalar = False
    if not EH_WINDOWS:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pode_instalar = True
        elif shutil.which("sudo"):
            try:
                pode_instalar = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5).returncode == 0
            except (OSError, subprocess.SubprocessError):
                pode_instalar = False
    placa = ""
    if shutil.which("nvidia-smi"):
        try:
            saida = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
            )
            if saida.returncode == 0:
                placa = saida.stdout.strip().splitlines()[0] if saida.stdout.strip() else ""
        except (OSError, subprocess.SubprocessError):
            placa = ""
    dados = {"programas": presentes, "pode_instalar_pacotes": pode_instalar, "placa_de_video": placa}
    _cache_ambiente = (time.time(), dados)
    return dados


def ambiente_de_processo() -> dict:
    env = dict(os.environ)
    extras = [pasta for pasta in _pastas_extras_do_path() if pasta not in env.get("PATH", "").split(os.pathsep)]
    if extras:
        env["PATH"] = os.pathsep.join(extras + [env.get("PATH", "")])
    env.update(
        {
            "CI": "1",
            "DEBIAN_FRONTEND": "noninteractive",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONUNBUFFERED": "1",
            "NPM_CONFIG_YES": "true",
        }
    )
    # A senha mestra do cofre nunca é repassada aos processos criados pelo agente.
    env.pop("EA_SENHA_MESTRA", None)
    return env


def encerrar_arvore(pid: int) -> None:
    """Encerra um processo e todos os seus descendentes."""
    try:
        pai = psutil.Process(pid)
    except psutil.Error:
        return
    processos = pai.children(recursive=True) + [pai]
    for processo in processos:
        try:
            processo.terminate()
        except psutil.Error:
            pass
    _, vivos = psutil.wait_procs(processos, timeout=5)
    for processo in vivos:
        try:
            processo.kill()
        except psutil.Error:
            pass


def resolver_caminho(base: Path, caminho: str) -> Path:
    """Resolve um caminho dentro da pasta de trabalho, recusando saídas dela."""
    base = base.resolve()
    alvo = Path(caminho or ".").expanduser()
    alvo = (alvo if alvo.is_absolute() else base / alvo).resolve()
    if alvo != base and base not in alvo.parents:
        raise ValueError(f"o caminho precisa ficar dentro da pasta de trabalho ({base})")
    return alvo


def rodar_comando(comando: str, diretorio: Path, tempo_limite: int) -> tuple[int | None, str]:
    """Executa um comando e devolve (código de saída, saída combinada)."""
    opcoes: dict = {}
    if EH_WINDOWS:
        opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        opcoes["start_new_session"] = True
    processo = subprocess.Popen(
        linha_de_comando(comando),
        cwd=str(diretorio),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=ambiente_de_processo(),
        **opcoes,
    )
    try:
        bruto, _ = processo.communicate(timeout=tempo_limite)
        return processo.returncode, bruto.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        encerrar_arvore(processo.pid)
        try:
            bruto, _ = processo.communicate(timeout=10)
        except Exception:
            bruto = b""
        return None, bruto.decode("utf-8", errors="replace")


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    trabalho = amb.cfg.dir_trabalho

    @cat.ferramenta(
        "executar_comando",
        "Executa um comando no terminal da máquina (bash no Linux, PowerShell no Windows) dentro da pasta de "
        "trabalho. Use para instalar dependências, compilar, testar, usar git, fazer deploy e chamar CLIs. "
        "O comando não pode pedir entrada interativa. Para processos que ficam rodando, use servico_iniciar.",
        comando=P("string", "Comando completo a executar."),
        diretorio=P("string", "Subpasta da pasta de trabalho onde rodar.", obrigatorio=False),
        tempo_limite=P("integer", "Segundos até interromper (padrão 300, máximo 3600).", obrigatorio=False),
    )
    def executar_comando(comando: str, diretorio: str = "", tempo_limite: int = 0) -> str:
        if comando_proibido(comando):
            return "ERRO: comando recusado por colocar a máquina do agente em risco."
        pasta = resolver_caminho(trabalho, diretorio)
        pasta.mkdir(parents=True, exist_ok=True)
        limite = max(5, min(3600, tempo_limite or amb.cfg.tempo_limite_comando))
        codigo, saida = rodar_comando(comando, pasta, limite)
        saida = saida.strip() or "(sem saída)"
        if codigo is None:
            return f"TEMPO ESGOTADO após {limite}s. Saída parcial:\n{saida}"
        return f"código de saída: {codigo}\n{saida}"

    @cat.ferramenta(
        "ler_arquivo",
        "Lê um arquivo de texto da pasta de trabalho, com números de linha.",
        caminho=P("string", "Caminho relativo à pasta de trabalho."),
        inicio=P("integer", "Primeira linha a ler (padrão 1).", obrigatorio=False),
        linhas=P("integer", "Quantidade de linhas (padrão 200).", obrigatorio=False),
    )
    def ler_arquivo(caminho: str, inicio: int = 1, linhas: int = 200) -> str:
        alvo = resolver_caminho(trabalho, caminho)
        if not alvo.is_file():
            return f"ERRO: arquivo não encontrado: {caminho}"
        conteudo = alvo.read_text(encoding="utf-8", errors="replace").splitlines()
        inicio = max(1, inicio)
        trecho = conteudo[inicio - 1 : inicio - 1 + max(1, linhas)]
        corpo = "\n".join(f"{inicio + i:>5}  {linha}" for i, linha in enumerate(trecho))
        return f"{caminho} ({len(conteudo)} linhas no total)\n{corpo}"

    @cat.ferramenta(
        "escrever_arquivo",
        "Cria ou substitui por completo um arquivo de texto na pasta de trabalho (cria as pastas necessárias).",
        caminho=P("string", "Caminho relativo à pasta de trabalho."),
        conteudo=P("string", "Conteúdo completo do arquivo."),
    )
    def escrever_arquivo(caminho: str, conteudo: str) -> str:
        alvo = resolver_caminho(trabalho, caminho)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(conteudo, encoding="utf-8")
        return f"Arquivo gravado: {caminho} ({len(conteudo)} caracteres)."

    @cat.ferramenta(
        "editar_arquivo",
        "Troca um trecho exato de um arquivo existente por outro. O trecho antigo precisa aparecer uma única vez.",
        caminho=P("string", "Caminho relativo à pasta de trabalho."),
        trecho_antigo=P("string", "Texto exato a substituir."),
        trecho_novo=P("string", "Texto que entra no lugar."),
    )
    def editar_arquivo(caminho: str, trecho_antigo: str, trecho_novo: str) -> str:
        alvo = resolver_caminho(trabalho, caminho)
        if not alvo.is_file():
            return f"ERRO: arquivo não encontrado: {caminho}"
        texto = alvo.read_text(encoding="utf-8", errors="replace")
        ocorrencias = texto.count(trecho_antigo)
        if ocorrencias == 0:
            return "ERRO: o trecho antigo não foi encontrado. Leia o arquivo e copie o trecho exato."
        if ocorrencias > 1:
            return f"ERRO: o trecho antigo aparece {ocorrencias} vezes. Inclua mais contexto para torná-lo único."
        alvo.write_text(texto.replace(trecho_antigo, trecho_novo, 1), encoding="utf-8")
        return f"Arquivo editado: {caminho}."

    @cat.ferramenta(
        "listar_arquivos",
        "Lista arquivos e pastas da pasta de trabalho.",
        caminho=P("string", "Subpasta a listar (padrão: raiz da pasta de trabalho).", obrigatorio=False),
        profundidade=P("integer", "Níveis de subpastas a mostrar (padrão 2).", obrigatorio=False),
    )
    def listar_arquivos(caminho: str = "", profundidade: int = 2) -> str:
        raiz = resolver_caminho(trabalho, caminho)
        if not raiz.exists():
            return f"ERRO: pasta não encontrada: {caminho}"
        ignorar = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
        linhas: list[str] = []

        def percorrer(pasta: Path, nivel: int) -> None:
            try:
                itens = sorted(pasta.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return
            for item in itens:
                if len(linhas) >= 300:
                    return
                recuo = "  " * nivel
                if item.is_dir():
                    linhas.append(f"{recuo}{item.name}/")
                    if item.name not in ignorar and nivel + 1 < max(1, profundidade):
                        percorrer(item, nivel + 1)
                else:
                    linhas.append(f"{recuo}{item.name} ({item.stat().st_size} bytes)")

        percorrer(raiz, 0)
        if not linhas:
            return "(pasta vazia)"
        return limitar("\n".join(linhas), amb.cfg.limite_saida_ferramenta)

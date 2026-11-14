"""Configuração do agente.

Ordem de precedência (do menor para o maior): valores padrão, arquivo
``config.toml`` dentro do diretório de dados, variáveis de ambiente ``EA_*`` e,
por fim, argumentos de linha de comando.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from urllib.parse import urlparse

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - apenas Python 3.10
    import tomli as tomllib


MODELO_CONFIG = """\
# Configuração da Empresa Automática.
# Todas as chaves são opcionais. Remova o "#" da linha para alterar um valor.

# --- Modelo de linguagem (sempre local e de código aberto) ---
# provedor = "ollama"        # "ollama" ou "openai" (API compatível: llama.cpp, LM Studio, vLLM, LocalAI)
# url_llm = "http://127.0.0.1:11434"
# modelo = "qwen3:8b"
# contexto_tokens = 16384    # janela de contexto pedida ao modelo
# temperatura = 0.4
# modo_ferramentas = "auto"  # "auto", "nativo" ou "json"
# permitir_llm_remoto = false  # mantenha false para garantir que o LLM roda na sua rede local

# --- Painel web ---
# host = "127.0.0.1"         # use "0.0.0.0" para acessar de outra máquina da rede (exige token)
# porta = 8787

# --- Comportamento do agente ---
# max_passos_tarefa = 40
# max_tentativas_tarefa = 3
# tarefas_por_planejamento = 5
# intervalo_resumo_horas = 6

# --- Ferramentas ---
# tempo_limite_comando = 300
# navegador_headless = true
# navegador_executavel = ""  # caminho de um Chromium ou Chrome já instalado (opcional)
# url_searxng = ""           # instância própria do SearXNG para pesquisas (opcional)
# limite_emails_dia = 50
# limite_emails_hora = 15
"""


@dataclass
class Config:
    dir_dados: Path = field(default_factory=lambda: Path.home() / ".empresa-auto")

    # Modelo de linguagem
    provedor: str = "ollama"
    url_llm: str = "http://127.0.0.1:11434"
    modelo: str = "qwen3:8b"
    contexto_tokens: int = 16384
    temperatura: float = 0.4
    tempo_limite_llm: int = 1200
    modo_ferramentas: str = "auto"
    permitir_llm_remoto: bool = False

    # Painel
    host: str = "127.0.0.1"
    porta: int = 8787

    # Agente
    max_passos_tarefa: int = 40
    max_tentativas_tarefa: int = 3
    tarefas_por_planejamento: int = 5
    max_tarefas_abertas: int = 30
    intervalo_ocioso_seg: int = 30
    intervalo_resumo_horas: float = 6.0

    # Ferramentas
    tempo_limite_comando: int = 300
    navegador_headless: bool = True
    navegador_executavel: str = ""
    url_searxng: str = ""
    limite_saida_ferramenta: int = 6000
    limite_emails_dia: int = 50
    limite_emails_hora: int = 15

    # ------------------------------------------------------------------
    @property
    def dir_trabalho(self) -> Path:
        """Pasta onde o agente cria os projetos da empresa."""
        return self.dir_dados / "trabalho"

    @property
    def dir_habilidades(self) -> Path:
        return self.dir_dados / "habilidades"

    @property
    def dir_navegador(self) -> Path:
        return self.dir_dados / "navegador"

    @property
    def dir_logs(self) -> Path:
        return self.dir_dados / "logs"

    @property
    def dir_capturas(self) -> Path:
        return self.dir_dados / "capturas"

    @property
    def caminho_banco(self) -> Path:
        return self.dir_dados / "empresa.db"

    def preparar_diretorios(self) -> None:
        for pasta in (
            self.dir_dados,
            self.dir_trabalho,
            self.dir_habilidades,
            self.dir_navegador,
            self.dir_logs,
            self.dir_capturas,
        ):
            pasta.mkdir(parents=True, exist_ok=True)
        arquivo = self.dir_dados / "config.toml"
        if not arquivo.exists():
            arquivo.write_text(MODELO_CONFIG, encoding="utf-8")

    @property
    def painel_exposto(self) -> bool:
        """Verdadeiro quando o painel aceita conexões de fora da própria máquina."""
        return self.host not in ("127.0.0.1", "localhost", "::1")


def _converter(valor: str, tipo_atual: object) -> object:
    if isinstance(tipo_atual, bool):
        return str(valor).strip().lower() in ("1", "true", "sim", "yes", "on")
    if isinstance(tipo_atual, int):
        return int(valor)
    if isinstance(tipo_atual, float):
        return float(valor)
    if isinstance(tipo_atual, Path):
        return Path(valor).expanduser()
    return valor


def carregar_config(dir_dados: str | os.PathLike | None = None, **sobrescritas: object) -> Config:
    """Monta a configuração final aplicando arquivo, ambiente e sobrescritas."""
    cfg = Config()
    base = dir_dados or os.environ.get("EA_DIR_DADOS") or os.environ.get("EA_DADOS")
    if base:
        cfg.dir_dados = Path(base).expanduser().resolve()

    nomes = {f.name for f in fields(Config)}

    arquivo = cfg.dir_dados / "config.toml"
    if arquivo.exists():
        try:
            dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
        except Exception as erro:  # arquivo inválido não pode derrubar o agente
            print(f"[config] config.toml inválido, usando padrões: {erro}", file=sys.stderr)
            dados = {}
        for chave, valor in dados.items():
            if chave in nomes and chave != "dir_dados":
                setattr(cfg, chave, _converter(valor, getattr(cfg, chave)))

    for nome in nomes:
        if nome == "dir_dados":
            continue
        bruto = os.environ.get(f"EA_{nome.upper()}")
        if bruto is not None and bruto != "":
            setattr(cfg, nome, _converter(bruto, getattr(cfg, nome)))

    for nome, valor in sobrescritas.items():
        if valor is not None and nome in nomes:
            setattr(cfg, nome, _converter(valor, getattr(cfg, nome)) if isinstance(valor, str) else valor)

    cfg.url_llm = cfg.url_llm.rstrip("/")
    return cfg


def url_e_local(url: str) -> bool:
    """Indica se a URL aponta para esta máquina ou para a rede privada.

    O projeto exige que o modelo de linguagem rode localmente. Esta verificação
    impede que alguém configure por engano um serviço de LLM hospedado na internet.
    """
    host = urlparse(url).hostname
    if not host:
        return False
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".lan"):
        return True
    try:
        enderecos = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        enderecos = []
        for info in infos:
            try:
                enderecos.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
        if not enderecos:
            return False
    return all(e.is_loopback or e.is_private or e.is_link_local for e in enderecos)

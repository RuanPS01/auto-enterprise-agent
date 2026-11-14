"""Habilidades (skills) do agente.

Uma habilidade é uma pasta com um arquivo ``SKILL.md``: um cabeçalho com
``name`` e ``description`` e, em seguida, instruções em Markdown. É o mesmo
formato aberto usado pela comunidade (Agent Skills), então o agente consegue
instalar habilidades publicadas em repositórios git, além de escrever as suas.

Só o nome e a descrição ficam sempre no contexto do modelo. O conteúdo completo
é lido sob demanda com ``habilidade_ler``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import Ambiente, Catalogo, P

DIR_EMBUTIDAS = Path(__file__).resolve().parent.parent / "habilidades_embutidas"
TAMANHO_PARTE = 5000
MAX_BYTES_HABILIDADE = 5 * 1024 * 1024
MAX_POR_INSTALACAO = 30


def ler_cabecalho(texto: str) -> tuple[dict, str]:
    """Separa o cabeçalho (YAML simples) do corpo de um SKILL.md."""
    if not texto.startswith("---"):
        return {}, texto
    linhas = texto.splitlines()
    fim = next((i for i in range(1, len(linhas)) if linhas[i].strip() == "---"), None)
    if fim is None:
        return {}, texto
    campos: dict[str, str] = {}
    chave = None
    for linha in linhas[1:fim]:
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        encontrado = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", linha)
        if encontrado and not linha[0].isspace():
            chave = encontrado.group(1).lower()
            valor = encontrado.group(2).strip()
            campos[chave] = "" if valor in (">", "|", ">-", "|-", ">+", "|+") else valor.strip("\"'")
        elif chave and linha[0].isspace():
            campos[chave] = (campos[chave] + " " + linha.strip()).strip()
    return campos, "\n".join(linhas[fim + 1 :]).lstrip("\n")


def nome_seguro(nome: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", nome.strip().lower()).strip("-")[:64]


def _tamanho(pasta: Path) -> int:
    return sum(f.stat().st_size for f in pasta.rglob("*") if f.is_file())


class GerenciadorHabilidades:
    def __init__(self, amb: Ambiente):
        self.amb = amb
        self.dir_instaladas = amb.cfg.dir_habilidades

    # ------------------------------------------------------------------ consulta
    def listar(self) -> list[dict]:
        achadas: dict[str, dict] = {}
        for origem, raiz in (("embutida", DIR_EMBUTIDAS), ("instalada", self.dir_instaladas)):
            if not raiz.is_dir():
                continue
            for pasta in sorted(raiz.iterdir()):
                arquivo = pasta / "SKILL.md"
                if not arquivo.is_file():
                    continue
                try:
                    campos, _ = ler_cabecalho(arquivo.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                nome = nome_seguro(campos.get("name") or pasta.name) or pasta.name
                achadas[nome] = {
                    "nome": nome,
                    "descricao": campos.get("description", "").strip(),
                    "origem": origem,
                    "pasta": pasta,
                }
        return sorted(achadas.values(), key=lambda h: h["nome"])

    def _localizar(self, nome: str) -> dict | None:
        alvo = nome_seguro(nome)
        return next((h for h in self.listar() if h["nome"] == alvo), None)

    def catalogo_resumido(self, limite: int = 25) -> str:
        habilidades = self.listar()
        linhas = [f"- {h['nome']}: {h['descricao'][:170]}" for h in habilidades[:limite]]
        if len(habilidades) > limite:
            linhas.append(f"(mais {len(habilidades) - limite} habilidades: ative o grupo 'expansao' e use habilidade_listar)")
        return "\n".join(linhas) or "(nenhuma habilidade instalada)"

    def ler(self, nome: str, arquivo: str = "", parte: int = 1) -> str:
        habilidade = self._localizar(nome)
        if not habilidade:
            nomes = ", ".join(h["nome"] for h in self.listar())
            return f"ERRO: habilidade '{nome}' não encontrada. Disponíveis: {nomes}."
        pasta: Path = habilidade["pasta"]
        alvo = (pasta / (arquivo or "SKILL.md")).resolve()
        if pasta.resolve() not in alvo.parents or not alvo.is_file():
            arquivos = ", ".join(sorted(str(f.relative_to(pasta)) for f in pasta.rglob("*") if f.is_file())[:40])
            return f"ERRO: arquivo não encontrado na habilidade. Arquivos existentes: {arquivos}"
        texto = alvo.read_text(encoding="utf-8", errors="replace")
        if alvo.name == "SKILL.md":
            _, texto = ler_cabecalho(texto)
        total = max(1, -(-len(texto) // TAMANHO_PARTE))
        parte = max(1, min(total, parte))
        trecho = texto[(parte - 1) * TAMANHO_PARTE : parte * TAMANHO_PARTE]
        outros = sorted(str(f.relative_to(pasta)) for f in pasta.rglob("*") if f.is_file() and f.name != "SKILL.md")
        rodape = f"\n\nOutros arquivos desta habilidade: {', '.join(outros[:30])}" if outros and parte == total else ""
        return f"Habilidade {habilidade['nome']} (parte {parte} de {total}), pasta: {pasta}\n\n{trecho}{rodape}"

    # ------------------------------------------------------------------ criação e instalação
    def criar(self, nome: str, descricao: str, conteudo: str) -> str:
        seguro = nome_seguro(nome)
        if not seguro:
            return "ERRO: informe um nome válido (letras, números e hífen)."
        pasta = self.dir_instaladas / seguro
        pasta.mkdir(parents=True, exist_ok=True)
        descricao_linha = " ".join(descricao.split())
        (pasta / "SKILL.md").write_text(
            f"---\nname: {seguro}\ndescription: {descricao_linha}\n---\n\n{conteudo.strip()}\n", encoding="utf-8"
        )
        self.amb.registro.evento("habilidade", f"Habilidade criada: {seguro}", descricao_linha)
        return f"Habilidade '{seguro}' criada em {pasta}."

    def remover(self, nome: str) -> str:
        habilidade = self._localizar(nome)
        if not habilidade or habilidade["origem"] != "instalada":
            return "ERRO: só é possível remover habilidades instaladas ou criadas pelo agente."
        shutil.rmtree(habilidade["pasta"], ignore_errors=True)
        self.amb.registro.evento("habilidade", f"Habilidade removida: {habilidade['nome']}")
        return f"Habilidade '{habilidade['nome']}' removida."

    def instalar(self, origem: str, subpasta: str = "") -> str:
        """Instala habilidades de um repositório git (ou de uma pasta local)."""
        origem = origem.strip()
        ramo = ""
        # Aceita links do GitHub no formato .../tree/<ramo>/<caminho>
        encontrado = re.match(r"^(https://github\.com/[^/]+/[^/]+?)(?:\.git)?/tree/([^/]+)/?(.*)$", origem)
        if encontrado:
            origem, ramo, caminho = encontrado.group(1), encontrado.group(2), encontrado.group(3)
            subpasta = subpasta or caminho
        with tempfile.TemporaryDirectory(prefix="ea_habilidade_") as temporario:
            if Path(origem).is_dir():
                raiz = Path(origem)
            else:
                if not shutil.which("git"):
                    return "ERRO: o git não está instalado nesta máquina. Instale o git para baixar habilidades."
                comando = ["git", "clone", "--depth", "1"]
                if ramo:
                    comando += ["--branch", ramo]
                comando += [origem, str(Path(temporario) / "repo")]
                resultado = subprocess.run(comando, capture_output=True, text=True, timeout=300)
                if resultado.returncode != 0:
                    return f"ERRO ao clonar {origem}: {resultado.stderr.strip()[-400:]}"
                raiz = Path(temporario) / "repo"
            base = (raiz / subpasta).resolve() if subpasta else raiz.resolve()
            if not base.is_dir() or (base != raiz.resolve() and raiz.resolve() not in base.parents):
                return f"ERRO: a subpasta '{subpasta}' não existe nesse repositório."
            arquivos = [a for a in sorted(base.rglob("SKILL.md")) if ".git" not in a.parts][:MAX_POR_INSTALACAO]
            if not arquivos:
                return "ERRO: nenhum arquivo SKILL.md encontrado nessa origem."
            instaladas, ignoradas = [], []
            for arquivo in arquivos:
                pasta = arquivo.parent
                campos, _ = ler_cabecalho(arquivo.read_text(encoding="utf-8", errors="replace"))
                nome = nome_seguro(campos.get("name") or pasta.name)
                if not nome or _tamanho(pasta) > MAX_BYTES_HABILIDADE:
                    ignoradas.append(pasta.name)
                    continue
                destino = self.dir_instaladas / nome
                shutil.rmtree(destino, ignore_errors=True)
                shutil.copytree(pasta, destino, ignore=shutil.ignore_patterns(".git"))
                instaladas.append(nome)
        if not instaladas:
            return "ERRO: nenhuma habilidade válida encontrada nessa origem."
        self.amb.registro.evento("habilidade", f"Habilidades instaladas: {', '.join(instaladas)}", f"origem: {origem}")
        aviso = f" Ignoradas: {', '.join(ignoradas)}." if ignoradas else ""
        return f"Instaladas {len(instaladas)} habilidades: {', '.join(instaladas)}.{aviso} Use habilidade_ler para estudar cada uma."


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    gerenciador = GerenciadorHabilidades(amb)
    amb.habilidades = gerenciador

    @cat.ferramenta(
        "habilidade_ler",
        "Lê as instruções completas de uma habilidade (guia passo a passo para um tipo de trabalho). Leia a "
        "habilidade relevante antes de começar um trabalho que ela cobre.",
        nome=P("string", "Nome da habilidade."),
        arquivo=P("string", "Arquivo auxiliar dentro da habilidade (padrão: SKILL.md).", obrigatorio=False),
        parte=P("integer", "Parte do texto quando for longo (padrão 1).", obrigatorio=False),
    )
    def habilidade_ler(nome: str, arquivo: str = "", parte: int = 1) -> str:
        return gerenciador.ler(nome, arquivo, parte)

    @cat.ferramenta("habilidade_listar", "Lista todas as habilidades disponíveis.", _grupo="expansao")
    def habilidade_listar() -> str:
        return "\n".join(f"- {h['nome']} ({h['origem']}): {h['descricao'][:200]}" for h in gerenciador.listar())

    @cat.ferramenta(
        "habilidade_instalar",
        "Instala habilidades da comunidade a partir de um repositório git que contenha arquivos SKILL.md "
        "(por exemplo https://github.com/anthropics/skills). Encontre repositórios com pesquisar_web.",
        _grupo="expansao",
        origem=P("string", "URL do repositório git (aceita links .../tree/ramo/pasta do GitHub)."),
        subpasta=P("string", "Pasta dentro do repositório, para instalar só uma parte.", obrigatorio=False),
    )
    def habilidade_instalar(origem: str, subpasta: str = "") -> str:
        return gerenciador.instalar(origem, subpasta)

    @cat.ferramenta(
        "habilidade_criar",
        "Escreve uma habilidade nova com um procedimento que deu certo, para repetir no futuro sem redescobrir.",
        _grupo="expansao",
        nome=P("string", "Nome curto com hífens, por exemplo publicar-no-github-pages."),
        descricao=P("string", "Uma frase dizendo o que a habilidade ensina e quando usar."),
        conteudo=P("string", "Instruções em Markdown: passos, comandos, cuidados e exemplos."),
    )
    def habilidade_criar(nome: str, descricao: str, conteudo: str) -> str:
        return gerenciador.criar(nome, descricao, conteudo)

    @cat.ferramenta(
        "habilidade_remover",
        "Remove uma habilidade instalada ou criada pelo agente.",
        _grupo="expansao",
        nome=P("string", "Nome da habilidade."),
    )
    def habilidade_remover(nome: str) -> str:
        return gerenciador.remover(nome)

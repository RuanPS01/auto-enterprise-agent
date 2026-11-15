"""Habilidades (skills) do agente.

Uma habilidade é uma pasta com um arquivo ``SKILL.md``: um cabeçalho com
``name`` e ``description`` e, em seguida, instruções em Markdown. É o mesmo
formato aberto usado pela comunidade (Agent Skills), então o agente consegue
instalar habilidades publicadas em repositórios git, além de escrever as suas.

Só o nome e a descrição ficam sempre no contexto do modelo. O conteúdo completo
é lido sob demanda com ``habilidade_ler``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import Ambiente, Catalogo, P

DIR_EMBUTIDAS = Path(__file__).resolve().parent.parent / "habilidades_embutidas"
ARQUIVO_CATALOGO = Path(__file__).resolve().parent.parent / "catalogo" / "habilidades.json"
ARQUIVO_META = ".empresa-auto.json"
TAMANHO_PARTE = 5000
MAX_BYTES_HABILIDADE = 5 * 1024 * 1024
MAX_BYTES_HABILIDADE_DO_CATALOGO = 40 * 1024 * 1024  # itens conferidos podem trazer fontes e modelos
MAX_POR_INSTALACAO = 30

# Habilidades da comunidade foram escritas para outros agentes. Este aviso acompanha a leitura
# e diz ao modelo como traduzir os nomes de ferramentas para as que ele realmente tem.
NOTA_COMPATIBILIDADE = (
    "NOTA: esta habilidade veio da comunidade e pode citar ferramentas de outros agentes. Equivalências aqui: "
    "Bash ou terminal = executar_comando; Read = ler_arquivo; Write = escrever_arquivo; Edit = editar_arquivo; "
    "WebSearch = pesquisar_web; WebFetch = buscar_pagina; navegador ou Playwright = grupo navegador; "
    "listas de tarefas = tarefa_criar; perguntar ao usuário = decida sozinho com base nas evidências; "
    "subagentes = faça você mesmo, uma etapa por vez. Arquivos e scripts da habilidade ficam na pasta indicada "
    "acima: leia com habilidade_ler (parâmetro arquivo) e execute com executar_comando usando o caminho completo."
)

# Áreas de habilidade mais prováveis para cada área de tarefa (reforço na ordenação por relevância).
AREAS_AFINS = {
    "pesquisa": {"pesquisa", "web", "dados"},
    "produto": {"gestao", "produto", "pesquisa", "privacidade"},
    "engenharia": {"programacao", "infraestrutura", "seguranca", "privacidade"},
    "marketing": {"marketing", "social", "midia"},
    "atendimento": {"atendimento", "marketing"},
    "operacoes": {"infraestrutura", "seguranca", "operacao"},
    "financeiro": {"gestao", "dados"},
}

_PALAVRAS_VAZIAS = set(
    "a o e as os um uma de da do das dos em no na nos nas para por com sem que se ou ao aos como mais menos muito "
    "ser ter fazer usar use quando onde qual quais sobre entre ate apos antes depois cada toda todo todos todas "
    "the and for with from that this when what which into your you are use using user wants asks how".split()
)


def palavras(texto: str) -> set[str]:
    """Palavras significativas de um texto, sem acento e em minúsculas."""
    import unicodedata

    plano = unicodedata.normalize("NFKD", texto.lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return {p for p in re.findall(r"[a-z0-9]+", plano) if len(p) >= 3 and p not in _PALAVRAS_VAZIAS}


def radicais(texto: str) -> set[str]:
    """Reduz um texto a radicais comparáveis (prefixo de 5 letras absorve plural e conjugação)."""
    return {p[:5] for p in palavras(texto)}


def carregar_catalogo() -> dict:
    """Lê o catálogo curado de habilidades da comunidade que acompanha o agente."""
    try:
        return json.loads(ARQUIVO_CATALOGO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"versao": 0, "fontes": []}


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
        self._cache: tuple[float, list[dict]] | None = None

    # ------------------------------------------------------------------ consulta
    def listar(self) -> list[dict]:
        if self._cache is not None and time.time() - self._cache[0] < 20:
            return self._cache[1]
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
                meta: dict = {}
                try:
                    meta = json.loads((pasta / ARQUIVO_META).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
                nome = nome_seguro(campos.get("name") or pasta.name) or pasta.name
                descricao = (meta.get("descricao") or campos.get("description", "")).strip()
                area = (meta.get("area") or campos.get("area", "")).strip().lower()
                achadas[nome] = {
                    "nome": nome,
                    "descricao": descricao,
                    "area": area,
                    "origem": origem,
                    "fonte": meta.get("fonte", ""),
                    "licenca": meta.get("licenca", ""),
                    "pasta": pasta,
                    "_radicais_nome": radicais(nome.replace("-", " ")),
                    "_palavras_nome": palavras(nome.replace("-", " ")),
                    "_radicais": radicais(f"{descricao} {area}"),
                    "_pago": "pago por créditos" in descricao,
                }
        lista = sorted(achadas.values(), key=lambda h: h["nome"])
        self._cache = (time.time(), lista)
        return lista

    def _invalidar(self) -> None:
        self._cache = None

    def _localizar(self, nome: str) -> dict | None:
        alvo = nome_seguro(nome)
        return next((h for h in self.listar() if h["nome"] == alvo), None)

    def ordenar_por_relevancia(self, consulta: str, area_tarefa: str = "") -> list[tuple[float, dict]]:
        """Pontua cada habilidade contra um texto (título e descrição da tarefa, ou termos de busca)."""
        alvo = radicais(consulta)
        alvo_exato = palavras(consulta)
        afins = AREAS_AFINS.get(area_tarefa, set())
        pontuadas = []
        for h in self.listar():
            if h["origem"] == "embutida":
                no_nome = len(alvo & h["_radicais_nome"])
            else:
                # Nomes da comunidade são em inglês: só contam quando a palavra aparece inteira na consulta
                # (hyperframes, remotion, lgpd, pdf), para "relatório" não casar com "relations".
                no_nome = len(alvo_exato & h["_palavras_nome"])
            pontos = 3.0 * no_nome + 1.0 * len(alvo & h["_radicais"])
            if pontos and h["area"] in afins:
                pontos += 1.5
            if h["origem"] == "embutida" and pontos:
                pontos += 0.5  # as embutidas foram escritas para este agente e para modelos locais
            if h["_pago"]:
                pontos *= 0.6  # serviços pagos ficam atrás das opções gratuitas e locais
            pontuadas.append((pontos, h))
        pontuadas.sort(key=lambda par: (-par[0], par[1]["nome"]))
        return pontuadas

    def catalogo_resumido(self, consulta: str = "", area_tarefa: str = "", limite: int = 10) -> str:
        """Lista curta para o contexto do modelo: as habilidades mais relevantes para a tarefa."""
        todas = self.listar()
        if not todas:
            return "(nenhuma habilidade instalada)"
        escolhidas = [h for pontos, h in self.ordenar_por_relevancia(consulta, area_tarefa) if pontos > 0][:limite]
        if len(escolhidas) < min(limite, 6):
            afins = AREAS_AFINS.get(area_tarefa, set())
            for h in todas:
                if len(escolhidas) >= min(limite, 6):
                    break
                if h not in escolhidas and h["origem"] == "embutida" and (not afins or h["area"] in afins):
                    escolhidas.append(h)
        linhas = [f"- {h['nome']}: {h['descricao'][:150]}" for h in escolhidas]
        resto = len(todas) - len(escolhidas)
        if resto > 0:
            linhas.append(f"(há mais {resto} habilidades instaladas: encontre com habilidade_buscar)")
        return "\n".join(linhas)

    def buscar(self, consulta: str, limite: int = 8) -> str:
        achadas = [h for pontos, h in self.ordenar_por_relevancia(consulta) if pontos > 0][:limite]
        if not achadas:
            return (
                "Nenhuma habilidade instalada combina com essa busca. Tente outras palavras (em português ou inglês) "
                "ou ative o grupo 'expansao' para instalar ou criar uma habilidade."
            )
        return "\n".join(f"- {h['nome']} [{h['area'] or 'geral'}]: {h['descricao'][:220]}" for h in achadas)

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
        nota = f"{NOTA_COMPATIBILIDADE}\n\n" if habilidade["origem"] == "instalada" and habilidade["fonte"] and parte == 1 else ""
        return f"Habilidade {habilidade['nome']} (parte {parte} de {total}), pasta: {pasta}\n\n{nota}{trecho}{rodape}"

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
        self._invalidar()
        self.amb.registro.evento("habilidade", f"Habilidade criada: {seguro}", descricao_linha)
        return f"Habilidade '{seguro}' criada em {pasta}."

    def remover(self, nome: str) -> str:
        habilidade = self._localizar(nome)
        if not habilidade or habilidade["origem"] != "instalada":
            return "ERRO: só é possível remover habilidades instaladas ou criadas pelo agente."
        shutil.rmtree(habilidade["pasta"], ignore_errors=True)
        self._invalidar()
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
        self._invalidar()
        if not instaladas:
            return "ERRO: nenhuma habilidade válida encontrada nessa origem."
        self.amb.registro.evento("habilidade", f"Habilidades instaladas: {', '.join(instaladas)}", f"origem: {origem}")
        aviso = f" Ignoradas: {', '.join(ignoradas)}." if ignoradas else ""
        return f"Instaladas {len(instaladas)} habilidades: {', '.join(instaladas)}.{aviso} Use habilidade_ler para estudar cada uma."


    def instalar_fonte_do_catalogo(self, fonte: dict, tempo_limite: int = 180) -> tuple[list[str], str]:
        """Instala de uma vez as habilidades escolhidas de um repositório do catálogo.

        Clona o repositório uma única vez e copia só as pastas listadas, gravando junto a descrição em
        português, a área e a licença. Devolve (nomes instalados, mensagem de erro ou texto vazio).
        """
        origem = fonte["origem"]
        with tempfile.TemporaryDirectory(prefix="ea_catalogo_") as temporario:
            if Path(origem).is_dir():
                raiz = Path(origem)
            else:
                if not shutil.which("git"):
                    return [], "o git não está instalado"
                comando = ["git", "clone", "--depth", "1"]
                if fonte.get("ramo"):
                    comando += ["--branch", fonte["ramo"]]
                comando += [origem, str(Path(temporario) / "repo")]
                try:
                    resultado = subprocess.run(comando, capture_output=True, text=True, timeout=tempo_limite)
                except subprocess.TimeoutExpired:
                    return [], f"tempo esgotado ao clonar {origem}"
                if resultado.returncode != 0:
                    return [], f"falha ao clonar {origem}: {resultado.stderr.strip()[-300:]}"
                raiz = Path(temporario) / "repo"
            instaladas, ausentes, grandes = [], [], []
            for item in fonte.get("itens", []):
                pasta = (raiz / item["pasta"]).resolve()
                if raiz.resolve() not in pasta.parents or not (pasta / "SKILL.md").is_file():
                    ausentes.append(item["pasta"])
                    continue
                if _tamanho(pasta) > MAX_BYTES_HABILIDADE_DO_CATALOGO:
                    grandes.append(item["pasta"])
                    continue
                campos, _ = ler_cabecalho((pasta / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
                nome = nome_seguro(item.get("nome") or campos.get("name") or pasta.name)
                destino = self.dir_instaladas / nome
                shutil.rmtree(destino, ignore_errors=True)
                shutil.copytree(pasta, destino, ignore=shutil.ignore_patterns(".git"))
                (destino / ARQUIVO_META).write_text(
                    json.dumps(
                        {
                            "descricao": item.get("descricao", ""),
                            "area": item.get("area", ""),
                            "fonte": origem,
                            "licenca": fonte.get("licenca", ""),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                instaladas.append(nome)
        self._invalidar()
        problemas = []
        if ausentes:
            problemas.append(f"pastas não encontradas em {origem}: {', '.join(ausentes)}")
        if grandes:
            problemas.append(f"pastas grandes demais em {origem}: {', '.join(grandes)}")
        return instaladas, "; ".join(problemas)


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    gerenciador = GerenciadorHabilidades(amb)
    amb.habilidades = gerenciador

    @cat.ferramenta(
        "habilidade_buscar",
        "Procura, entre as habilidades já instaladas, as que ensinam o que você precisa. Há dezenas instaladas "
        "(programação, infraestrutura, segurança, vídeo, imagem, áudio, marketing, redes sociais, documentos).",
        consulta=P("string", "Palavras-chave do trabalho, em português ou inglês."),
    )
    def habilidade_buscar(consulta: str) -> str:
        return gerenciador.buscar(consulta)

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
        return "\n".join(f"- {h['nome']} [{h['area'] or 'geral'}, {h['origem']}]: {h['descricao'][:120]}" for h in gerenciador.listar())

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

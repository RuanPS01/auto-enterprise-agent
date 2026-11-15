"""Pesquisa na web e leitura de páginas por HTTP (sem navegador)."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .base import Ambiente, Catalogo, P

AGENTE_HTTP = "Mozilla/5.0 (X11; Linux x86_64) EmpresaAutomatica/0.1 (agente autonomo; leitura de paginas)"
TAMANHO_PAGINA = 5000


class _ExtratorTexto(HTMLParser):
    """Converte HTML em texto legível, preservando títulos e links."""

    IGNORAR = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
    BLOCOS = {"p", "div", "br", "li", "tr", "section", "article", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.titulo = ""
        self._ignorando = 0
        self._no_titulo = False
        self._link: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "title":
            self._no_titulo = True
            return
        if tag in self.IGNORAR:
            self._ignorando += 1
            return
        if self._ignorando:
            return
        if tag in self.BLOCOS:
            self.partes.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.partes.append("# ")
        if tag == "li":
            self.partes.append("- ")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self._link = href if href.startswith("http") else None

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._no_titulo = False
            return
        if tag in self.IGNORAR:
            self._ignorando = max(0, self._ignorando - 1)
            return
        if self._ignorando:
            return
        if tag == "a" and self._link:
            self.partes.append(f" ({self._link})")
            self._link = None
        if tag in self.BLOCOS:
            self.partes.append("\n")

    def handle_data(self, dados: str) -> None:
        if self._no_titulo:
            self.titulo += dados
        elif not self._ignorando:
            self.partes.append(dados)


def html_para_texto(html: str) -> tuple[str, str]:
    """Devolve (título, texto) de um documento HTML."""
    extrator = _ExtratorTexto()
    try:
        extrator.feed(html)
    except Exception:
        pass
    texto = "".join(extrator.partes)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    texto = re.sub(r" ?\n ?", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return extrator.titulo.strip(), texto.strip()


def _formatar_resultados(resultados: list[dict]) -> str:
    if not resultados:
        return "Nenhum resultado encontrado. Tente outras palavras ou use o navegador."
    linhas = []
    for i, r in enumerate(resultados, 1):
        linhas.append(f"{i}. {r.get('titulo', '').strip()}\n   {r.get('url', '').strip()}\n   {r.get('resumo', '').strip()}")
    return "\n".join(linhas)


def _buscar_searxng(base: str, consulta: str, maximo: int) -> list[dict]:
    resposta = httpx.get(
        f"{base.rstrip('/')}/search",
        params={"q": consulta, "format": "json", "language": "pt-BR"},
        timeout=30,
        headers={"User-Agent": AGENTE_HTTP},
    )
    resposta.raise_for_status()
    return [
        {"titulo": r.get("title", ""), "url": r.get("url", ""), "resumo": r.get("content", "")}
        for r in resposta.json().get("results", [])[:maximo]
    ]


def _buscar_ddgs(consulta: str, maximo: int) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:  # nome antigo do pacote
        from duckduckgo_search import DDGS  # type: ignore[no-redef]
    resultados = DDGS().text(consulta, max_results=maximo, region="br-pt")
    return [
        {"titulo": r.get("title", ""), "url": r.get("href") or r.get("url", ""), "resumo": r.get("body", "")}
        for r in (resultados or [])[:maximo]
    ]


class _ExtratorDDG(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.resultados: list[dict] = []
        self._alvo: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        atributos = dict(attrs)
        classes = atributos.get("class") or ""
        if tag == "a" and "result__a" in classes:
            url = atributos.get("href") or ""
            if "uddg=" in url:
                url = unquote(parse_qs(urlparse(url).query).get("uddg", [url])[0])
            self.resultados.append({"titulo": "", "url": url, "resumo": ""})
            self._alvo = "titulo"
        elif "result__snippet" in classes and self.resultados:
            self._alvo = "resumo"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("a", "div", "td") and self._alvo:
            self._alvo = None

    def handle_data(self, dados: str) -> None:
        if self._alvo and self.resultados:
            self.resultados[-1][self._alvo] += dados


def _buscar_ddg_html(consulta: str, maximo: int) -> list[dict]:
    resposta = httpx.post(
        "https://html.duckduckgo.com/html/",
        data={"q": consulta, "kl": "br-pt"},
        timeout=30,
        headers={"User-Agent": AGENTE_HTTP},
        follow_redirects=True,
    )
    resposta.raise_for_status()
    extrator = _ExtratorDDG()
    extrator.feed(resposta.text)
    return [r for r in extrator.resultados if r["url"].startswith("http")][:maximo]


def pesquisar(consulta: str, maximo: int, url_searxng: str = "") -> list[dict]:
    """Tenta as fontes de pesquisa gratuitas em ordem até uma responder."""
    fontes = []
    if url_searxng:
        fontes.append(lambda: _buscar_searxng(url_searxng, consulta, maximo))
    fontes.append(lambda: _buscar_ddgs(consulta, maximo))
    fontes.append(lambda: _buscar_ddg_html(consulta, maximo))
    ultimo_erro: Exception | None = None
    for fonte in fontes:
        try:
            resultados = fonte()
            if resultados:
                return resultados
        except Exception as erro:
            ultimo_erro = erro
    if ultimo_erro:
        raise RuntimeError(f"todas as fontes de pesquisa falharam ({ultimo_erro})")
    return []


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    @cat.ferramenta(
        "pesquisar_web",
        "Pesquisa na internet e devolve títulos, links e resumos. Use para pesquisa de mercado, concorrentes, "
        "documentação, tendências e para achar serviços gratuitos.",
        consulta=P("string", "Termos da pesquisa."),
        max_resultados=P("integer", "Quantidade de resultados (padrão 6, máximo 15).", obrigatorio=False),
    )
    def pesquisar_web(consulta: str, max_resultados: int = 6) -> str:
        maximo = max(1, min(15, max_resultados))
        try:
            return _formatar_resultados(pesquisar(consulta, maximo, amb.cfg.url_searxng))
        except Exception as erro:
            return (
                f"ERRO na pesquisa: {erro}. Alternativa: ative o grupo 'navegador' e pesquise por "
                "https://duckduckgo.com/?q=termos"
            )

    @cat.ferramenta(
        "buscar_pagina",
        "Baixa uma URL por HTTP e devolve o texto legível (rápido, sem JavaScript). Para sites que exigem "
        "login, cliques ou JavaScript, use as ferramentas do navegador.",
        url=P("string", "Endereço completo, começando com http ou https."),
        parte=P("integer", "Parte do texto a ler quando a página é longa (padrão 1).", obrigatorio=False),
    )
    def buscar_pagina(url: str, parte: int = 1) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            resposta = httpx.get(
                url,
                timeout=40,
                follow_redirects=True,
                headers={"User-Agent": AGENTE_HTTP, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
            )
        except httpx.HTTPError as erro:
            return f"ERRO ao acessar {url}: {erro}"
        tipo = resposta.headers.get("content-type", "")
        if resposta.status_code >= 400:
            return f"ERRO: {url} respondeu HTTP {resposta.status_code}. Se for bloqueio a robôs, tente o navegador."
        if "json" in tipo:
            try:
                texto = json.dumps(resposta.json(), ensure_ascii=False, indent=1)
            except json.JSONDecodeError:
                texto = resposta.text
            titulo = "(JSON)"
        elif "html" in tipo or "<html" in resposta.text[:500].lower():
            titulo, texto = html_para_texto(resposta.text)
        elif tipo.startswith("text/") or "xml" in tipo:
            titulo, texto = "(texto)", resposta.text
        else:
            return f"O conteúdo de {url} não é texto ({tipo or 'tipo desconhecido'}, {len(resposta.content)} bytes)."
        total = max(1, -(-len(texto) // TAMANHO_PAGINA))
        parte = max(1, min(total, parte))
        trecho = texto[(parte - 1) * TAMANHO_PAGINA : parte * TAMANHO_PAGINA]
        return f"URL: {resposta.url}\nTítulo: {titulo}\nParte {parte} de {total}\n\n{trecho}"

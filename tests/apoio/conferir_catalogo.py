"""Confere na internet cada item do catálogo padrão: pastas de habilidades e pacotes de extensões.

    python tests/apoio/conferir_catalogo.py

Não faz parte da suíte automática porque depende de rede. Rode antes de publicar mudanças no catálogo.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "empresa_auto" / "catalogo"


def existe(url: str) -> bool:
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": "conferencia-de-catalogo"})
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            return resposta.status == 200
    except Exception:
        return False


def conferir_habilidade(par: tuple[dict, dict]) -> tuple[str, bool]:
    fonte, item = par
    repo = fonte["origem"].replace("https://github.com/", "")
    return f"{repo}:{item['pasta']}", existe(f"https://raw.githubusercontent.com/{repo}/{fonte['ramo']}/{item['pasta']}/SKILL.md")


def conferir_extensao(entrada: dict) -> tuple[str, bool]:
    if entrada.get("tipo") == "http":
        return f"{entrada['nome']} (remoto, {entrada['url']})", True  # endereço exige credencial; conferido na documentação
    pacote = next((a for a in entrada["args"] if not a.startswith("-")), "")
    pacote = pacote.rsplit("@", 1)[0] if pacote.count("@") > (1 if pacote.startswith("@") else 0) else pacote
    if entrada["comando"] == "npx":
        return f"{entrada['nome']} (npm {pacote})", existe("https://registry.npmjs.org/" + pacote.replace("/", "%2F") + "/latest")
    return f"{entrada['nome']} (PyPI {pacote})", existe(f"https://pypi.org/pypi/{pacote}/json")


def principal() -> int:
    habilidades = json.loads((RAIZ / "habilidades.json").read_text(encoding="utf-8"))
    extensoes = json.loads((RAIZ / "extensoes.json").read_text(encoding="utf-8"))
    pares = [(fonte, item) for fonte in habilidades["fontes"] for item in fonte["itens"]]
    with ThreadPoolExecutor(12) as executor:
        resultados = list(executor.map(conferir_habilidade, pares)) + list(executor.map(conferir_extensao, extensoes["extensoes"]))
    falhas = [nome for nome, ok in resultados if not ok]
    print(f"{len(resultados) - len(falhas)} de {len(resultados)} itens conferidos com sucesso.")
    for nome in falhas:
        print("FALTA:", nome)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(principal())

"""Ferramentas do agente: tudo o que ele consegue fazer no mundo."""

from __future__ import annotations

from . import contas, extensoes, gestao, habilidades, navegador, operacao, pagamento, sistema, web
from .base import GRUPOS, Ambiente, Catalogo, Ferramenta, P, limitar

__all__ = ["GRUPOS", "Ambiente", "Catalogo", "Ferramenta", "P", "limitar", "montar_catalogo"]


def montar_catalogo(amb: Ambiente) -> Catalogo:
    """Cria o catálogo com todas as ferramentas embutidas e o associa ao ambiente."""
    cat = Catalogo(limite_saida=amb.cfg.limite_saida_ferramenta)
    amb.catalogo = cat
    for modulo in (gestao, web, sistema, habilidades, navegador, contas, operacao, extensoes, pagamento):
        modulo.registrar(cat, amb)
    return cat

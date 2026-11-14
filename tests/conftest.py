"""Recursos compartilhados pelos testes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from empresa_auto.agente import Agente  # noqa: E402
from empresa_auto.config import carregar_config  # noqa: E402
from empresa_auto.llm import Chamada, Resposta  # noqa: E402


def chamar(nome: str, **argumentos) -> Resposta:
    """Resposta do modelo que usa uma ferramenta."""
    return Resposta(chamadas=[Chamada(id=f"c_{nome}_{id(argumentos)}", nome=nome, argumentos=argumentos)])


def falar(texto: str) -> Resposta:
    """Resposta do modelo sem ferramenta."""
    return Resposta(texto=texto)


class LLMRoteirizado:
    """Modelo de mentira: devolve respostas de um roteiro ou de uma função."""

    modo_atual = "nativo"

    def __init__(self, roteiro=None):
        self.roteiro = roteiro if callable(roteiro) else list(roteiro or [])
        self.historico: list[tuple[list[dict], list[dict]]] = []
        self.textos_pedidos: list[str] = []

    def conversar(self, mensagens, ferramentas=None, temperatura=None) -> Resposta:
        self.historico.append(([dict(m) for m in mensagens], list(ferramentas or [])))
        if callable(self.roteiro):
            return self.roteiro(mensagens, ferramentas or [])
        if not self.roteiro:
            return chamar("concluir_tarefa", resultado="fim do roteiro")
        return self.roteiro.pop(0)

    def texto_simples(self, sistema, pedido, temperatura=None) -> str:
        self.textos_pedidos.append(pedido)
        return "Texto gerado pelo modelo de teste."


@pytest.fixture
def cfg(tmp_path):
    config = carregar_config(tmp_path / "dados")
    config.preparar_diretorios()
    config.intervalo_ocioso_seg = 1
    return config


@pytest.fixture
def agente(cfg):
    instancia = Agente(cfg, llm=LLMRoteirizado(), imprimir=False)
    yield instancia
    instancia.amb.supervisor.encerrar_todos()
    instancia.amb.extensoes.encerrar_todas()
    instancia.amb.navegador.fechar()

"""Registro de eventos: tudo o que o agente faz passa por aqui.

Cada evento é gravado no banco (para o painel em tempo real e para o resumo
semanal) e impresso no terminal. Segredos conhecidos pelo cofre são mascarados
antes de qualquer gravação.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Iterable

from .banco import Banco

LIMITE_DETALHE = 4000


class Registro:
    def __init__(self, banco: Banco, imprimir: bool = True):
        self.banco = banco
        self.imprimir = imprimir
        self._fontes_segredos: list[Callable[[], Iterable[str]]] = []
        self._trava = threading.Lock()

    def adicionar_fonte_de_segredos(self, fonte: Callable[[], Iterable[str]]) -> None:
        self._fontes_segredos.append(fonte)

    def mascarar(self, texto: str) -> str:
        if not texto:
            return texto
        for fonte in self._fontes_segredos:
            try:
                segredos = sorted(fonte(), key=len, reverse=True)
            except Exception:
                continue
            for segredo in segredos:
                if segredo and len(segredo) >= 4 and segredo in texto:
                    texto = texto.replace(segredo, "********")
        return texto

    def evento(
        self,
        tipo: str,
        titulo: str,
        detalhe: str = "",
        nivel: str = "info",
        tarefa_id: int | None = None,
    ) -> int:
        titulo = self.mascarar(str(titulo))[:300]
        detalhe = self.mascarar(str(detalhe or ""))
        if len(detalhe) > LIMITE_DETALHE:
            detalhe = detalhe[:LIMITE_DETALHE] + "\n[... conteúdo truncado ...]"
        try:
            evento_id = self.banco.adicionar_evento(tipo, titulo, detalhe, nivel, tarefa_id)
        except Exception as erro:  # o registro nunca pode derrubar o agente
            evento_id = 0
            print(f"[registro] falha ao gravar evento: {erro}", file=sys.stderr)
        if self.imprimir:
            hora = time.strftime("%H:%M:%S")
            marcador = {"erro": "ERRO", "aviso": "AVISO"}.get(nivel, tipo.upper())
            with self._trava:
                try:
                    print(f"{hora} [{marcador}] {titulo}", flush=True)
                except Exception:
                    pass
        return evento_id

    # Atalhos usados pelo restante do código -------------------------------
    def sistema(self, titulo: str, detalhe: str = "", nivel: str = "info") -> int:
        return self.evento("sistema", titulo, detalhe, nivel)

    def erro(self, titulo: str, detalhe: str = "", tarefa_id: int | None = None) -> int:
        return self.evento("erro", titulo, detalhe, "erro", tarefa_id)

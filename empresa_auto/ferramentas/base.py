"""Infraestrutura comum das ferramentas do agente."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from ..banco import Banco
from ..cofre import Cofre
from ..config import Config
from ..registro import Registro

# Grupos de ferramentas. O grupo "base" está sempre disponível; os demais são
# ligados conforme a área da tarefa ou a pedido do modelo (ativar_ferramentas).
# Manter poucas ferramentas visíveis por vez ajuda muito os modelos locais.
GRUPOS = {
    "base": "pesquisa na web, arquivos, terminal, memória e tarefas",
    "navegador": "navegador real para usar sites: abrir páginas, clicar, preencher formulários",
    "contas": "cofre de credenciais, geração de senhas e e-mail (enviar e ler)",
    "operacao": "serviços em segundo plano e automações recorrentes",
    "gestao": "dados da empresa, decisões, métricas e gestão da fila de tarefas",
    "expansao": "instalar ou criar habilidades e extensões (servidores MCP) da comunidade",
    "pagamento": "cartão autorizado pelo dono para compras indispensáveis",
}


def P(tipo: str, descricao: str, obrigatorio: bool = True, enum: list[str] | None = None) -> dict:
    """Declara um parâmetro de ferramenta."""
    esquema: dict[str, Any] = {"type": tipo, "description": descricao, "_obrigatorio": obrigatorio}
    if enum:
        esquema["enum"] = enum
    return esquema


def limitar(texto: str, limite: int) -> str:
    """Corta saídas longas preservando o começo e o fim."""
    if len(texto) <= limite:
        return texto
    cabeca = int(limite * 0.7)
    cauda = limite - cabeca
    omitido = len(texto) - limite
    return f"{texto[:cabeca]}\n[... {omitido} caracteres omitidos ...]\n{texto[-cauda:]}"


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict
    funcao: Callable[..., str]
    grupo: str = "base"
    sensivel: bool = False

    def esquema(self) -> dict:
        return {"nome": self.nome, "descricao": self.descricao, "parametros": self.parametros}


@dataclass
class Ambiente:
    """Tudo o que as ferramentas precisam para trabalhar."""

    cfg: Config
    banco: Banco
    registro: Registro
    cofre: Cofre
    llm: Any = None
    catalogo: Any = None
    navegador: Any = None
    supervisor: Any = None
    habilidades: Any = None
    extensoes: Any = None
    # Estado da tarefa em execução
    tarefa_atual: dict | None = None
    grupos_ativos: set[str] = field(default_factory=lambda: {"base"})
    conclusao: dict | None = None
    pagamento_autorizado: bool = False


def _coagir(valor: Any, tipo: str) -> Any:
    """Modelos locais erram tipos com frequência; aqui consertamos o que for possível."""
    try:
        if tipo == "integer" and not isinstance(valor, bool):
            return int(float(valor))
        if tipo == "number" and not isinstance(valor, bool):
            return float(valor)
        if tipo == "boolean" and not isinstance(valor, bool):
            return str(valor).strip().lower() in ("true", "1", "sim", "yes", "verdadeiro")
        if tipo == "string" and not isinstance(valor, str):
            import json

            return valor if valor is None else (json.dumps(valor, ensure_ascii=False) if isinstance(valor, (dict, list)) else str(valor))
    except (TypeError, ValueError):
        return valor
    return valor


class Catalogo:
    """Registro de todas as ferramentas conhecidas pelo agente."""

    def __init__(self, limite_saida: int = 6000):
        self._ferramentas: dict[str, Ferramenta] = {}
        self.limite_saida = limite_saida
        self.grupos_extras: dict[str, str] = {}

    # ------------------------------------------------------------------ registro
    def ferramenta(
        self, nome: str, descricao: str, /, _grupo: str = "base", _sensivel: bool = False, **parametros: dict
    ) -> Callable[[Callable[..., str]], Callable[..., str]]:
        """Registra uma função como ferramenta.

        ``_grupo`` e ``_sensivel`` levam sublinhado para não colidir com os nomes
        dos parâmetros das próprias ferramentas (há ferramentas com parâmetro "grupo").
        """

        def decorador(funcao: Callable[..., str]) -> Callable[..., str]:
            propriedades = {}
            obrigatorios = []
            for nome_param, declarado in parametros.items():
                esquema = dict(declarado)
                if esquema.pop("_obrigatorio", True):
                    obrigatorios.append(nome_param)
                propriedades[nome_param] = esquema
            self.adicionar(
                Ferramenta(
                    nome=nome,
                    descricao=descricao,
                    parametros={"type": "object", "properties": propriedades, "required": obrigatorios},
                    funcao=funcao,
                    grupo=_grupo,
                    sensivel=_sensivel,
                )
            )
            return funcao

        return decorador

    def adicionar(self, ferramenta: Ferramenta) -> None:
        self._ferramentas[ferramenta.nome] = ferramenta

    def remover_grupo(self, grupo: str) -> None:
        for nome in [n for n, f in self._ferramentas.items() if f.grupo == grupo]:
            del self._ferramentas[nome]
        self.grupos_extras.pop(grupo, None)

    # ------------------------------------------------------------------ consulta
    def obter(self, nome: str) -> Ferramenta | None:
        return self._ferramentas.get(nome)

    def grupos(self) -> dict[str, str]:
        presentes = {f.grupo for f in self._ferramentas.values()}
        todos = {**GRUPOS, **self.grupos_extras}
        return {nome: descricao for nome, descricao in todos.items() if nome in presentes}

    def esquemas(self, grupos: set[str]) -> list[dict]:
        return [f.esquema() for f in self._ferramentas.values() if f.grupo in grupos]

    def nomes(self, grupos: set[str] | None = None) -> list[str]:
        return [n for n, f in self._ferramentas.items() if grupos is None or f.grupo in grupos]

    # ------------------------------------------------------------------ execução
    def executar(self, nome: str, argumentos: dict | None) -> str:
        ferramenta = self._ferramentas.get(nome)
        if ferramenta is None:
            return f"ERRO: a ferramenta '{nome}' não existe. Use apenas as ferramentas listadas."
        argumentos = dict(argumentos or {})
        propriedades = ferramenta.parametros.get("properties", {})
        limpos = {}
        for chave, valor in argumentos.items():
            if chave in propriedades and valor is not None:
                limpos[chave] = _coagir(valor, propriedades[chave].get("type", "string"))
        faltando = [p for p in ferramenta.parametros.get("required", []) if p not in limpos]
        if faltando:
            return f"ERRO: faltam os parâmetros obrigatórios: {', '.join(faltando)}."
        try:
            saida = ferramenta.funcao(**limpos)
        except Exception as erro:  # nenhuma ferramenta pode derrubar o agente
            resumo = traceback.format_exception_only(type(erro), erro)[-1].strip()
            return f"ERRO ao executar {nome}: {resumo}"
        if saida is None:
            saida = "OK"
        return limitar(str(saida), self.limite_saida)

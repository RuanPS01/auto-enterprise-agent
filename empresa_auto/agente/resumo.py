"""Resumo semanal: números calculados do banco e uma narrativa escrita pelo modelo."""

from __future__ import annotations

import datetime as dt
import time

from ..banco import Banco


def limites_semana(instante: float | None = None) -> tuple[float, float, str]:
    """Devolve (início, fim, chave) da semana que contém o instante. A semana começa na segunda-feira."""
    momento = dt.datetime.fromtimestamp(instante if instante is not None else time.time())
    segunda = (momento - dt.timedelta(days=momento.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    fim = segunda + dt.timedelta(days=7)
    return segunda.timestamp(), fim.timestamp(), segunda.strftime("%Y-%m-%d")


def limites_da_chave(chave: str) -> tuple[float, float, str]:
    segunda = dt.datetime.strptime(chave, "%Y-%m-%d")
    return limites_semana(segunda.timestamp() + 3600)


def estatisticas(banco: Banco, inicio: float, fim: float) -> dict:
    tarefas = [t for t in banco.tarefas_periodo(inicio, fim) if t["tipo"] == "trabalho"]
    concluidas = [t for t in tarefas if t["status"] == "concluida"]
    falhas = [t for t in tarefas if t["status"] == "falhou"]
    por_area: dict[str, int] = {}
    for t in concluidas:
        por_area[t["area"]] = por_area.get(t["area"], 0) + 1
    eventos = banco.eventos_periodo(
        inicio, fim, ("conta", "servico", "habilidade", "extensao", "bloqueio", "pagamento", "comunicacao", "automacao")
    )
    por_tipo: dict[str, list[str]] = {}
    for e in eventos:
        por_tipo.setdefault(e["tipo"], []).append(e["titulo"])
    gastos = banco.gastos(100, inicio, fim)
    return {
        "tarefas_concluidas": len(concluidas),
        "tarefas_falharam": len(falhas),
        "por_area": por_area,
        "concluidas": [{"id": t["id"], "titulo": t["titulo"], "area": t["area"], "resultado": t["resultado"][:400]} for t in concluidas],
        "falhas": [{"id": t["id"], "titulo": t["titulo"], "area": t["area"], "resultado": t["resultado"][:300]} for t in falhas],
        "decisoes": [{"titulo": d["titulo"], "justificativa": d["justificativa"][:300]} for d in banco.decisoes(30, inicio, fim)],
        "contas_criadas": por_tipo.get("conta", []),
        "servicos": por_tipo.get("servico", []),
        "habilidades": por_tipo.get("habilidade", []) + por_tipo.get("extensao", []),
        "automacoes": por_tipo.get("automacao", []),
        "impedimentos": por_tipo.get("bloqueio", []),
        "comunicacoes": len(por_tipo.get("comunicacao", [])),
        "gasto_total": round(sum(g["valor"] for g in gastos), 2),
        "gastos": [{"valor": g["valor"], "motivo": g["motivo"]} for g in gastos],
        "indicadores": [{"nome": m["nome"], "valor": m["valor"]} for m in banco.metricas_atuais()],
    }


def _fatos_para_o_modelo(empresa: dict, numeros: dict) -> str:
    linhas = [
        f"Empresa: {empresa.get('nome') or 'ainda sem nome'} (fase: {empresa.get('fase', 'descoberta')})",
        f"Tarefas concluídas: {numeros['tarefas_concluidas']}; tarefas que falharam: {numeros['tarefas_falharam']}",
    ]
    if numeros["concluidas"]:
        linhas.append("Trabalhos concluídos:")
        linhas += [f"- [{t['area']}] {t['titulo']}: {t['resultado'][:260]}" for t in numeros["concluidas"][-25:]]
    if numeros["falhas"]:
        linhas.append("Trabalhos que falharam:")
        linhas += [f"- [{t['area']}] {t['titulo']}: {t['resultado'][:200]}" for t in numeros["falhas"][-10:]]
    if numeros["decisoes"]:
        linhas.append("Decisões tomadas:")
        linhas += [f"- {d['titulo']}" for d in numeros["decisoes"][:12]]
    for rotulo, chave in (
        ("Contas criadas", "contas_criadas"),
        ("Serviços", "servicos"),
        ("Capacidades novas", "habilidades"),
        ("Automações", "automacoes"),
        ("Impedimentos relatados ao dono", "impedimentos"),
    ):
        if numeros[chave]:
            linhas.append(f"{rotulo}:")
            linhas += [f"- {item}" for item in numeros[chave][:10]]
    if numeros["indicadores"]:
        linhas.append("Indicadores atuais: " + "; ".join(f"{m['nome']} = {m['valor']}" for m in numeros["indicadores"][:12]))
    linhas.append(f"Mensagens enviadas a clientes: {numeros['comunicacoes']}")
    linhas.append(f"Gasto com o cartão do dono: R$ {numeros['gasto_total']:.2f}")
    return "\n".join(linhas)


def gerar_narrativa(llm, banco: Banco, chave: str | None = None) -> str:
    """Pede ao modelo o texto do resumo da semana e o grava no banco."""
    inicio, fim, chave = limites_da_chave(chave) if chave else limites_semana()
    numeros = estatisticas(banco, inicio, fim)
    if numeros["tarefas_concluidas"] + numeros["tarefas_falharam"] + len(numeros["decisoes"]) == 0:
        texto = "Ainda não houve trabalho concluído nesta semana."
    else:
        texto = llm.texto_simples(
            "Você escreve o resumo semanal de uma empresa operada por um agente autônomo, para o dono ler em um "
            "minuto. Escreva em português do Brasil, texto corrido e direto, sem títulos, sem listas e sem "
            "exageros. Use apenas os fatos fornecidos e não invente nada.",
            "Escreva o resumo desta semana em três parágrafos curtos: (1) o que avançou, (2) problemas e "
            "impedimentos, (3) o que vem a seguir.\n\nFATOS DA SEMANA\n" + _fatos_para_o_modelo(banco.empresa(), numeros),
            temperatura=0.3,
        )
        texto = texto.strip() or "Não foi possível gerar o texto do resumo nesta rodada."
    banco.salvar_resumo(chave, texto)
    return texto


def dados_do_resumo(banco: Banco, chave: str | None = None) -> dict:
    """Tudo o que o painel precisa para mostrar o resumo de uma semana."""
    inicio, fim, chave = limites_da_chave(chave) if chave else limites_semana()
    salvo = banco.resumo(chave)
    atual = limites_semana()[2]
    semanas = sorted(set(banco.semanas_com_resumo()) | {atual}, reverse=True)
    return {
        "semana": chave,
        "inicio": inicio,
        "fim": fim,
        "semana_atual": chave == atual,
        "semanas": semanas,
        "texto": salvo["texto"] if salvo else "",
        "atualizado_em": salvo["atualizado_em"] if salvo else None,
        "numeros": estatisticas(banco, inicio, fim),
    }

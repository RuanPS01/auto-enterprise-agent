"""Uso do cartão informado pelo dono (opcional).

Regras de segurança:

* Sem cartão cadastrado no painel, não existe pagamento: tudo precisa ser gratuito.
* Cada uso é autorizado contra o limite mensal definido pelo dono e fica
  registrado no painel.
* Os dados do cartão nunca entram no contexto do modelo nem nos registros. O
  modelo recebe apenas marcadores como ``{{cartao:numero}}``, trocados pelo
  valor real somente no instante de digitar no formulário de pagamento.
"""

from __future__ import annotations

import re
import time

from .base import Ambiente, Catalogo, P

_RE_MARCADOR = re.compile(r"\{\{\s*cartao:(\w+)\s*\}\}")


def inicio_do_mes() -> float:
    agora = time.localtime()
    return time.mktime((agora.tm_year, agora.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def resolver_marcadores(amb: Ambiente, texto: str) -> str:
    """Troca ``{{cartao:campo}}`` pelo dado real, apenas com pagamento autorizado na tarefa atual."""
    if "{{" not in texto or not amb.pagamento_autorizado:
        return texto
    campos = amb.cofre.campos_cartao()
    return _RE_MARCADOR.sub(lambda m: campos.get(m.group(1), m.group(0)), texto)


def situacao_cartao(amb: Ambiente) -> dict:
    resumo = amb.cofre.resumo_cartao()
    if resumo["configurado"]:
        gasto = amb.banco.gasto_desde(inicio_do_mes())
        resumo["gasto_mes"] = round(gasto, 2)
        resumo["disponivel"] = round(max(0.0, resumo["limite_mensal"] - gasto), 2)
    return resumo


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    @cat.ferramenta(
        "cartao_autorizar",
        "Pede autorização para usar o cartão do dono em uma compra indispensável. Só use quando não existir "
        "alternativa gratuita. Informe o valor total em reais. Se autorizado, preencha o formulário de pagamento "
        "no navegador usando os marcadores devolvidos.",
        _grupo="pagamento",
        motivo=P("string", "O que será comprado e por que é indispensável."),
        valor=P("number", "Valor total da compra em reais."),
    )
    def cartao_autorizar(motivo: str, valor: float) -> str:
        situacao = situacao_cartao(amb)
        if not situacao["configurado"]:
            return (
                "NEGADO: o dono não cadastrou cartão. Nada pode gerar custo. Procure uma alternativa gratuita "
                "ou de código aberto."
            )
        if valor <= 0:
            return "ERRO: informe o valor total da compra."
        if valor > situacao["disponivel"]:
            return (
                f"NEGADO: o valor de R$ {valor:.2f} ultrapassa o saldo do limite mensal "
                f"(disponível: R$ {situacao['disponivel']:.2f}). Procure uma alternativa mais barata ou gratuita."
            )
        amb.banco.registrar_gasto(valor, motivo)
        amb.pagamento_autorizado = True
        amb.registro.evento(
            "pagamento",
            f"Uso do cartão autorizado: R$ {valor:.2f}",
            motivo,
            nivel="aviso",
            tarefa_id=(amb.tarefa_atual or {}).get("id"),
        )
        return (
            f"AUTORIZADO: R$ {valor:.2f} lançados no limite mensal. Ative o grupo 'navegador' se preciso e "
            "preencha o formulário com navegador_digitar usando exatamente estes marcadores como texto:\n"
            "- número do cartão: {{cartao:numero}}\n"
            "- validade completa: {{cartao:validade}} (ou mês {{cartao:mes}} e ano {{cartao:ano}} ou {{cartao:ano_curto}})\n"
            "- código de segurança: {{cartao:cvv}}\n"
            "- nome do titular: {{cartao:titular}}\n"
            "Os marcadores só funcionam nas ferramentas navegador_digitar e navegador_selecionar, nesta tarefa."
        )

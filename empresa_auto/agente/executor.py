"""Execução de uma tarefa: o laço de raciocínio e ação do agente."""

from __future__ import annotations

import json
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ..ferramentas.base import Ambiente
from ..ferramentas.pagamento import situacao_cartao
from ..llm import estimar_tokens
from .prompts import (
    CONSTITUICAO,
    FERRAMENTAS_PLANEJAMENTO,
    GRUPOS_POR_AREA,
    GUIA_FASES,
    INSTRUCOES_PLANEJAMENTO,
    LEMBRETE_REPETICAO,
    LEMBRETE_SEM_ACAO,
)


class Interrompido(Exception):
    """O agente está sendo desligado no meio de uma tarefa."""


@dataclass
class Atividade:
    """O que o agente está fazendo neste instante (exibido no painel)."""

    estado: str = "iniciando"
    detalhe: str = ""
    tarefa: dict | None = None
    passo: int = 0
    max_passos: int = 0
    ferramenta: str = ""
    desde: float = field(default_factory=time.time)
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def definir(self, estado: str, detalhe: str = "", tarefa: dict | None = None) -> None:
        with self._trava:
            if estado != self.estado or (tarefa or {}).get("id") != (self.tarefa or {}).get("id"):
                self.desde = time.time()
            self.estado, self.detalhe, self.tarefa = estado, detalhe, tarefa
            self.passo, self.ferramenta = 0, ""

    def progresso(self, passo: int, max_passos: int, ferramenta: str = "") -> None:
        with self._trava:
            self.passo, self.max_passos, self.ferramenta = passo, max_passos, ferramenta

    def como_dict(self) -> dict:
        with self._trava:
            tarefa = self.tarefa
            return {
                "estado": self.estado,
                "detalhe": self.detalhe,
                "tarefa": (
                    {"id": tarefa["id"], "titulo": tarefa["titulo"], "area": tarefa["area"], "tipo": tarefa["tipo"]}
                    if tarefa
                    else None
                ),
                "passo": self.passo,
                "max_passos": self.max_passos,
                "ferramenta": self.ferramenta,
                "desde": self.desde,
            }


def _resumir_argumentos(argumentos: dict, limite: int = 160) -> str:
    partes = []
    for chave, valor in argumentos.items():
        texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
        texto = " ".join(str(texto).split())
        partes.append(f"{chave}={texto[:80] + '...' if len(texto) > 80 else texto}")
    resumo = ", ".join(partes)
    return resumo[:limite] + ("..." if len(resumo) > limite else "")


class Executor:
    def __init__(
        self,
        amb: Ambiente,
        atividade: Atividade,
        deve_parar: Callable[[], bool] = lambda: False,
        esta_pausado: Callable[[], bool] = lambda: False,
    ):
        self.amb = amb
        self.atividade = atividade
        self.deve_parar = deve_parar
        self.esta_pausado = esta_pausado

    # ------------------------------------------------------------------ montagem do contexto
    def _bloco_empresa(self) -> str:
        empresa = self.amb.banco.empresa()
        linhas = []
        for chave in (
            "nome",
            "fase",
            "ideia",
            "missao",
            "proposta_de_valor",
            "publico_alvo",
            "produto",
            "modelo_de_receita",
            "estrategia",
            "site",
            "canais",
        ):
            valor = empresa.get(chave)
            if valor:
                linhas.append(f"{chave}: {str(valor)[:500]}")
        if empresa.get("modo") == "auto" and not empresa.get("nome"):
            linhas.append("negócio: ainda não escolhido (o dono deixou a escolha por sua conta)")
        return "\n".join(linhas) or "(empresa ainda sem definições)"

    def _bloco_ambiente(self) -> str:
        cfg = self.amb.cfg
        sistema = platform.system()
        terminal = "PowerShell" if sistema == "Windows" else "bash"
        cartao = situacao_cartao(self.amb)
        texto_cartao = (
            f"cadastrado, R$ {cartao['disponivel']:.2f} disponíveis neste mês (use só se for indispensável)"
            if cartao["configurado"]
            else "não cadastrado (tudo precisa ser gratuito)"
        )
        contas = ", ".join(c["servico"] for c in self.amb.cofre.listar()) or "nenhuma"
        servicos = (
            ", ".join(f"{s['nome']} ({'rodando' if s['rodando'] else 'parado'})" for s in self.amb.supervisor.estado())
            if self.amb.supervisor
            else ""
        ) or "nenhum"
        return (
            f"sistema: {sistema} ({terminal})\n"
            f"pasta de trabalho: {cfg.dir_trabalho}\n"
            f"data e hora: {time.strftime('%d/%m/%Y %H:%M')}\n"
            f"cartão do dono: {texto_cartao}\n"
            f"contas no cofre: {contas}\n"
            f"serviços da empresa: {servicos}"
        )

    def _sistema(self, tarefa: dict) -> str:
        partes = [CONSTITUICAO, "EMPRESA\n" + self._bloco_empresa(), "AMBIENTE\n" + self._bloco_ambiente()]
        if tarefa["tipo"] != "planejamento":
            if self.amb.habilidades:
                partes.append("HABILIDADES DISPONÍVEIS (leia com habilidade_ler)\n" + self.amb.habilidades.catalogo_resumido())
            grupos = self.amb.catalogo.grupos()
            if not self.amb.cofre.obter_cartao():
                grupos.pop("pagamento", None)
            partes.append(
                "GRUPOS DE FERRAMENTAS (ligue outros com ativar_ferramentas)\n"
                + "\n".join(f"- {nome}: {descricao}" for nome, descricao in grupos.items())
            )
        return "\n\n".join(partes)

    def _situacao_para_planejamento(self) -> str:
        banco = self.amb.banco
        fase = banco.obter("fase", "descoberta")
        blocos = [f"ORIENTAÇÃO DA FASE ATUAL ({fase})\n{GUIA_FASES.get(fase, GUIA_FASES['descoberta'])}"]

        finalizadas = banco.tarefas_finalizadas(8)
        if finalizadas:
            linhas = []
            for t in finalizadas:
                situacao = {"concluida": "concluída", "falhou": "FALHOU", "cancelada": "cancelada"}[t["status"]]
                linhas.append(f"#{t['id']} [{t['area']}] {t['titulo']} ({situacao}): {t['resultado'][:500]}")
            blocos.append("TAREFAS FINALIZADAS RECENTEMENTE (da mais nova para a mais antiga)\n" + "\n".join(linhas))

        abertas = [t for t in banco.tarefas_abertas() if t["tipo"] == "trabalho"]
        blocos.append(
            "TAREFAS ABERTAS\n"
            + ("\n".join(f"#{t['id']} [{t['area']}, prioridade {t['prioridade']}] {t['titulo']}" for t in abertas) or "nenhuma")
        )

        bloqueios = banco.bloqueios("aberto", 8)
        if bloqueios:
            blocos.append("IMPEDIMENTOS RELATADOS AO DONO (sem resposta garantida)\n" + "\n".join(f"- {b['titulo']}" for b in bloqueios))

        metricas = banco.metricas_atuais()
        if metricas:
            blocos.append("INDICADORES\n" + "\n".join(f"- {m['nome']}: {m['valor']}" for m in metricas[:15]))

        decisoes = banco.decisoes(5)
        if decisoes:
            blocos.append("DECISÕES RECENTES\n" + "\n".join(f"- {d['titulo']}" for d in decisoes))

        automacoes = banco.automacoes()
        if automacoes:
            blocos.append("AUTOMAÇÕES ATIVAS\n" + "\n".join(f"- {a['titulo']}" for a in automacoes))

        memorias = banco.memorias_recentes(6)
        if memorias:
            blocos.append("CONHECIMENTOS MAIS RECENTES NA MEMÓRIA\n" + "\n".join(f"- {m['titulo']}: {m['conteudo'][:220]}" for m in memorias))
        return "\n\n".join(blocos)

    def _pedido(self, tarefa: dict) -> str:
        if tarefa["tipo"] == "planejamento":
            return INSTRUCOES_PLANEJAMENTO + "\n\n" + self._situacao_para_planejamento()
        cfg = self.amb.cfg
        partes = [
            f"TAREFA #{tarefa['id']} (área: {tarefa['area']}, tentativa {tarefa['tentativas']} de {cfg.max_tentativas_tarefa})",
            f"Título: {tarefa['titulo']}",
            f"Descrição: {tarefa['descricao'] or '(sem descrição)'}",
        ]
        if tarefa.get("notas"):
            partes.append("ANOTAÇÕES DA TENTATIVA ANTERIOR (continue de onde parou)\n" + tarefa["notas"])
        memorias = self.amb.banco.buscar_memorias(f"{tarefa['titulo']} {tarefa['descricao'][:200]}", limite=4)
        if memorias:
            partes.append(
                "CONHECIMENTOS DA MEMÓRIA QUE PODEM AJUDAR\n"
                + "\n".join(f"- {m['titulo']}: {m['conteudo'][:400]}" for m in memorias)
            )
        return "\n\n".join(partes)

    def _ferramentas(self, tarefa: dict) -> list[dict]:
        cat = self.amb.catalogo
        if tarefa["tipo"] == "planejamento":
            return [e for e in cat.esquemas({"base", "gestao"}) if e["nome"] in FERRAMENTAS_PLANEJAMENTO]
        return cat.esquemas(self.amb.grupos_ativos)

    # ------------------------------------------------------------------ gestão da janela de contexto
    @staticmethod
    def _digest(mensagens: list[dict]) -> list[str]:
        """Resumo determinístico de uma sequência de passos (ação e começo do resultado)."""
        linhas = []
        resultados = {m.get("id"): m for m in mensagens if m["role"] == "tool"}
        for m in mensagens:
            if m["role"] == "assistant" and m.get("chamadas"):
                for c in m["chamadas"]:
                    saida = " ".join((resultados.get(c["id"], {}).get("content") or "").split())
                    linhas.append(f"- {c['nome']}({_resumir_argumentos(c['argumentos'], 120)}) resultou em: {saida[:220]}")
            elif m.get("resumo"):
                linhas.extend(m["content"].splitlines()[1:])
        return linhas

    def _compactar(self, mensagens: list[dict], custo_ferramentas: int) -> list[dict]:
        orcamento = int(self.amb.cfg.contexto_tokens * 0.72) - custo_ferramentas
        if estimar_tokens(mensagens) <= orcamento or len(mensagens) <= 4:
            return mensagens
        cabeca, corpo = mensagens[:2], mensagens[2:]
        manter = 8
        while manter > 2:
            inicio = len(corpo) - manter
            # A cauda precisa começar em uma mensagem do assistente (nunca em um resultado órfão).
            while 0 < inicio < len(corpo) and corpo[inicio]["role"] == "tool":
                inicio += 1
            antigas, recentes = corpo[: max(0, inicio)], corpo[max(0, inicio) :]
            linhas = self._digest(antigas)
            while sum(len(l) for l in linhas) > 3500 and len(linhas) > 4:
                linhas.pop(0)
            resumo = {
                "role": "user",
                "resumo": True,
                "content": "RESUMO DOS PASSOS ANTERIORES DESTA TAREFA (os mais antigos podem ter sido omitidos)\n" + "\n".join(linhas),
            }
            candidata = cabeca + ([resumo] if linhas else []) + recentes
            if estimar_tokens(candidata) <= orcamento:
                return candidata
            manter -= 2
        # Último recurso: encurtar os resultados restantes.
        for m in candidata:
            if m["role"] == "tool" and len(m.get("content") or "") > 1500:
                m["content"] = m["content"][:1500] + "\n[... resultado encurtado para caber no contexto ...]"
        return candidata

    def _anotar_progresso(self, mensagens: list[dict]) -> str:
        """Ao esgotar os passos, guarda o que já foi feito para a próxima tentativa."""
        linhas = self._digest(mensagens[2:])[-25:]
        digest = "\n".join(linhas)
        try:
            notas = self.amb.llm.texto_simples(
                "Você resume o andamento de uma tarefa para que ela seja retomada depois. Seja factual e conciso.",
                "Com base nos passos abaixo, escreva em até 10 linhas: o que já foi feito e funciona, o que falhou e "
                f"por quê, e qual deve ser o próximo passo.\n\n{digest}",
                temperatura=0.2,
            )
            if notas:
                return notas[:2500]
        except Exception:
            pass
        return digest[-2500:]

    # ------------------------------------------------------------------ laço principal
    def _aguardar_se_pausado(self) -> None:
        while self.esta_pausado() and not self.deve_parar():
            time.sleep(1)
        if self.deve_parar():
            raise Interrompido()

    def executar(self, tarefa: dict) -> dict:
        """Roda a tarefa até concluir, falhar ou esgotar os passos.

        Devolve ``{"situacao": "concluida" | "falhou" | "incompleta", "resultado": str, "notas": str}``.
        """
        amb = self.amb
        registro = amb.registro
        planejamento = tarefa["tipo"] == "planejamento"
        amb.tarefa_atual = tarefa
        amb.conclusao = None
        amb.pagamento_autorizado = False
        amb.grupos_ativos = set(GRUPOS_POR_AREA.get(tarefa["area"], {"base"}))
        max_passos = 14 if planejamento else amb.cfg.max_passos_tarefa

        mensagens: list[dict] = [
            {"role": "system", "content": self._sistema(tarefa)},
            {"role": "user", "content": self._pedido(tarefa)},
        ]
        sem_acao = 0
        ultima_assinatura, repeticoes = "", 0
        ultimo_texto = ""

        try:
            for passo in range(1, max_passos + 1):
                self._aguardar_se_pausado()
                self.atividade.progresso(passo, max_passos, "pensando")
                ferramentas = self._ferramentas(tarefa)
                permitidas = {f["nome"] for f in ferramentas}
                custo = len(json.dumps(ferramentas, ensure_ascii=False)) // 3
                mensagens = self._compactar(mensagens, custo)
                resposta = amb.llm.conversar(mensagens, ferramentas)

                raciocinio = (resposta.texto or resposta.pensamento or "").strip()
                if raciocinio:
                    registro.evento("pensamento", raciocinio.splitlines()[0][:200], raciocinio, tarefa_id=tarefa["id"])
                if resposta.texto:
                    ultimo_texto = resposta.texto

                if not resposta.chamadas:
                    sem_acao += 1
                    if sem_acao >= 3:
                        break
                    mensagens.append({"role": "assistant", "content": resposta.texto or "(sem conteúdo)"})
                    mensagens.append({"role": "user", "content": LEMBRETE_SEM_ACAO})
                    continue
                sem_acao = 0

                mensagens.append(
                    {
                        "role": "assistant",
                        "content": resposta.texto,
                        "chamadas": [{"id": c.id, "nome": c.nome, "argumentos": c.argumentos} for c in resposta.chamadas],
                    }
                )
                repetiu = False
                for chamada in resposta.chamadas:
                    self._aguardar_se_pausado()
                    self.atividade.progresso(passo, max_passos, chamada.nome)
                    registro.evento(
                        "ferramenta",
                        f"{chamada.nome}({_resumir_argumentos(chamada.argumentos)})",
                        json.dumps(chamada.argumentos, ensure_ascii=False, indent=1),
                        tarefa_id=tarefa["id"],
                    )
                    if chamada.nome in permitidas:
                        saida = amb.catalogo.executar(chamada.nome, chamada.argumentos)
                    elif amb.catalogo.obter(chamada.nome):
                        grupo = amb.catalogo.obter(chamada.nome).grupo
                        saida = (
                            f"ERRO: a ferramenta '{chamada.nome}' pertence ao grupo '{grupo}', que não está ativo. "
                            f"Chame ativar_ferramentas com grupo='{grupo}' e repita."
                        )
                    else:
                        saida = f"ERRO: a ferramenta '{chamada.nome}' não existe. Use apenas as ferramentas disponíveis."
                    ferramenta = amb.catalogo.obter(chamada.nome)
                    sensivel = bool(ferramenta and ferramenta.sensivel)
                    registro.evento(
                        "resultado",
                        f"{chamada.nome}: {'(conteúdo protegido)' if sensivel else ' '.join(saida.split())[:140]}",
                        "(conteúdo protegido, não exibido no painel)" if sensivel else saida,
                        nivel="erro" if saida.startswith("ERRO") else "info",
                        tarefa_id=tarefa["id"],
                    )
                    mensagens.append({"role": "tool", "id": chamada.id, "nome": chamada.nome, "content": saida})

                    assinatura = f"{chamada.nome}|{json.dumps(chamada.argumentos, sort_keys=True, ensure_ascii=False)}|{saida[:200]}"
                    if assinatura == ultima_assinatura:
                        repeticoes += 1
                        repetiu = True
                    else:
                        ultima_assinatura, repeticoes = assinatura, 0
                    if amb.conclusao is not None:
                        break

                if amb.conclusao is not None:
                    conclusao = amb.conclusao
                    return {
                        "situacao": "concluida" if conclusao["sucesso"] else "falhou",
                        "resultado": conclusao["resultado"],
                        "notas": "",
                    }
                if repetiu and repeticoes >= 4:
                    break
                if repetiu and repeticoes >= 2:
                    mensagens.append({"role": "user", "content": LEMBRETE_REPETICAO})

            # Saiu do laço sem concluir_tarefa.
            if sem_acao >= 3 and len(ultimo_texto) > 200 and not planejamento:
                return {
                    "situacao": "concluida",
                    "resultado": ultimo_texto[:4000] + "\n(encerrada sem chamada explícita de concluir_tarefa)",
                    "notas": "",
                }
            if planejamento:
                return {"situacao": "concluida", "resultado": ultimo_texto[:1500] or "Ciclo de planejamento encerrado.", "notas": ""}
            self.atividade.progresso(max_passos, max_passos, "anotando progresso")
            return {"situacao": "incompleta", "resultado": "", "notas": self._anotar_progresso(mensagens)}
        finally:
            amb.tarefa_atual = None
            amb.conclusao = None
            amb.pagamento_autorizado = False

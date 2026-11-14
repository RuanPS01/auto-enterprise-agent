"""Orquestrador: o laço que mantém a empresa funcionando 24 horas por dia.

A cada volta o agente cuida da manutenção (serviços, automações, resumo
semanal), escolhe a próxima tarefa da fila e a executa. Quando a fila esvazia,
ou depois de algumas tarefas concluídas, ele roda um ciclo de planejamento, no
qual o próprio modelo decide os próximos passos da empresa. Nenhuma exceção
encerra o laço: erros são registrados e o trabalho continua.
"""

from __future__ import annotations

import threading
import time
import traceback

from ..banco import Banco
from ..cofre import Cofre
from ..config import Config
from ..ferramentas import Ambiente, montar_catalogo
from ..ferramentas.pagamento import situacao_cartao
from ..llm import ClienteLLM, ErroLLM, LLMIndisponivel
from ..registro import Registro
from . import resumo as modulo_resumo
from .executor import Atividade, Executor, Interrompido
from .prompts import tarefas_iniciais

TITULO_PLANEJAMENTO = "Ciclo de planejamento"


class Agente:
    def __init__(self, cfg: Config, llm: object | None = None, imprimir: bool = True):
        cfg.preparar_diretorios()
        self.cfg = cfg
        self.banco = Banco(cfg.caminho_banco)
        self.registro = Registro(self.banco, imprimir=imprimir)
        self.cofre = Cofre(cfg.dir_dados)
        self.registro.adicionar_fonte_de_segredos(self.cofre.segredos)
        self.llm = llm if llm is not None else ClienteLLM(cfg)
        self.amb = Ambiente(cfg=cfg, banco=self.banco, registro=self.registro, cofre=self.cofre, llm=self.llm)
        self.catalogo = montar_catalogo(self.amb)
        self.atividade = Atividade()
        self._parar = threading.Event()
        self._acordar = threading.Event()
        self._trava_inicio = threading.Lock()
        self.executor = Executor(self.amb, self.atividade, self._parar.is_set, self.pausado)
        self._llm_ok: bool | None = None
        self._llm_erro = ""
        self._ultima_vigia = 0.0
        self._ultima_poda = 0.0
        self._planejamentos_vazios = 0
        self._proximo_planejamento = 0.0

    # ------------------------------------------------------------------ controle externo (painel)
    def empresa_iniciada(self) -> bool:
        return bool(self.banco.obter("iniciada", False))

    def pausado(self) -> bool:
        return bool(self.banco.obter("pausado", False))

    def iniciar_empresa(self, modo: str, ideia: str = "") -> None:
        """Ponto de partida, acionado uma única vez pelo dono no painel."""
        modo = "ideia" if modo == "ideia" else "auto"
        ideia = (ideia or "").strip()
        if modo == "ideia" and len(ideia) < 10:
            raise ValueError("Descreva a ideia da empresa com um pouco mais de detalhe.")
        with self._trava_inicio:
            if self.empresa_iniciada():
                raise ValueError("A empresa já foi iniciada.")
            self.banco.definir("modo", modo)
            self.banco.definir("ideia", ideia if modo == "ideia" else "")
            self.banco.definir("fase", "descoberta")
            self.banco.definir("iniciada_em", time.time())
            for tarefa in tarefas_iniciais(modo, ideia):
                self.banco.criar_tarefa(
                    tarefa["titulo"], tarefa["descricao"], tarefa["area"], tarefa["prioridade"], origem="partida"
                )
            self.banco.definir("iniciada", True)
        if modo == "ideia":
            self.registro.evento("sistema", "Empresa iniciada a partir da ideia do dono", ideia)
        else:
            self.registro.evento("sistema", "Empresa iniciada: o agente vai escolher o negócio")
        self._acordar.set()

    def pausar(self) -> None:
        if not self.pausado():
            self.banco.definir("pausado", True)
            self.registro.sistema("Agente pausado pelo dono")

    def retomar(self) -> None:
        if self.pausado():
            self.banco.definir("pausado", False)
            self.registro.sistema("Agente retomado pelo dono")
            self._acordar.set()

    def parar(self) -> None:
        self._parar.set()
        self._acordar.set()

    # ------------------------------------------------------------------ estado para o painel
    def estado(self) -> dict:
        empresa = self.banco.empresa()
        abertas = self.banco.tarefas_abertas()
        return {
            "iniciada": bool(empresa.get("iniciada")),
            "pausado": bool(empresa.get("pausado")),
            "empresa": {
                chave: empresa.get(chave, "")
                for chave in (
                    "modo",
                    "ideia",
                    "nome",
                    "fase",
                    "missao",
                    "proposta_de_valor",
                    "publico_alvo",
                    "produto",
                    "modelo_de_receita",
                    "estrategia",
                    "site",
                    "canais",
                    "iniciada_em",
                )
            },
            "atividade": self.atividade.como_dict(),
            "llm": {
                "modelo": self.cfg.modelo,
                "provedor": self.cfg.provedor,
                "url": self.cfg.url_llm,
                "ok": self._llm_ok,
                "erro": self._llm_erro,
                "modo_ferramentas": getattr(self.llm, "modo_atual", ""),
            },
            "contagem": self.banco.contagem_tarefas(),
            "tarefas_abertas": [self._tarefa_publica(t) for t in abertas if t["tipo"] == "trabalho"][:40],
            "tarefas_finalizadas": [self._tarefa_publica(t) for t in self.banco.tarefas_finalizadas(15)],
            "bloqueios": self.banco.bloqueios("aberto", 20),
            "decisoes": self.banco.decisoes(8),
            "indicadores": self.banco.metricas_atuais(),
            "servicos": self.amb.supervisor.estado(),
            "automacoes": [
                {"id": a["id"], "titulo": a["titulo"], "intervalo_min": a["intervalo_min"], "proxima": a["proxima"]}
                for a in self.banco.automacoes()
            ],
            "habilidades": [
                {"nome": h["nome"], "descricao": h["descricao"], "origem": h["origem"]} for h in self.amb.habilidades.listar()
            ],
            "extensoes": self.amb.extensoes.listar(),
            "contas": self.cofre.listar(),
            "cartao": situacao_cartao(self.amb),
            "gastos": self.banco.gastos(10),
            "memorias": self.banco.contar_memorias(),
            "captura": self._instante_da_captura(),
            "agora": time.time(),
        }

    def _instante_da_captura(self) -> float | None:
        """Momento da última imagem do navegador do agente (None se ainda não houver)."""
        try:
            return (self.cfg.dir_capturas / "atual.png").stat().st_mtime
        except OSError:
            return None

    @staticmethod
    def _tarefa_publica(t: dict) -> dict:
        return {
            "id": t["id"],
            "titulo": t["titulo"],
            "descricao": t["descricao"][:600],
            "area": t["area"],
            "prioridade": t["prioridade"],
            "status": t["status"],
            "tentativas": t["tentativas"],
            "resultado": t["resultado"][:1200],
            "criado_em": t["criado_em"],
            "concluido_em": t["concluido_em"],
            "nao_antes_de": t["nao_antes_de"],
        }

    # ------------------------------------------------------------------ partida e desligamento
    def _preparar(self) -> None:
        self.registro.sistema(
            "Agente ligado",
            f"modelo local: {self.cfg.modelo} ({self.cfg.provedor} em {self.cfg.url_llm})\n"
            f"dados: {self.cfg.dir_dados}\npasta de trabalho: {self.cfg.dir_trabalho}",
        )
        retomadas = self.banco.retomar_interrompidas()
        if retomadas:
            self.registro.sistema(f"{retomadas} tarefa(s) interrompida(s) voltaram para a fila")
        try:
            self.amb.supervisor.restaurar()
        except Exception as erro:
            self.registro.erro("Falha ao religar serviços", str(erro))
        try:
            self.amb.extensoes.carregar_todas()
        except Exception as erro:
            self.registro.erro("Falha ao carregar extensões", str(erro))

    def _encerrar(self) -> None:
        self.atividade.definir("desligado")
        for acao in (
            lambda: self.amb.navegador.fechar(),
            lambda: self.amb.extensoes.encerrar_todas(),
            lambda: self.amb.supervisor.encerrar_todos(),
        ):
            try:
                acao()
            except Exception:
                pass
        self.registro.sistema("Agente desligado")

    def _dormir(self, segundos: float) -> None:
        """Espera interrompível: acorda se o dono agir no painel ou se o agente for desligado."""
        self._acordar.wait(timeout=max(0.1, segundos))
        self._acordar.clear()

    # ------------------------------------------------------------------ modelo local
    def _verificar_llm(self) -> bool:
        """Confere se o servidor do modelo responde e se o modelo está instalado."""
        try:
            if not hasattr(self.llm, "modelo_disponivel"):
                self._llm_ok, self._llm_erro = True, ""
                return True
            if not self.llm.modelo_disponivel():
                if self.cfg.provedor == "ollama":
                    self.atividade.definir("baixando_modelo", f"Baixando o modelo {self.cfg.modelo}")
                    self.registro.sistema(f"Baixando o modelo {self.cfg.modelo} (pode demorar bastante)")
                    self.llm.baixar_modelo()
                    self.registro.sistema(f"Modelo {self.cfg.modelo} instalado")
                else:
                    raise ErroLLM(f"O modelo '{self.cfg.modelo}' não está disponível no servidor local.")
            if self._llm_ok is not True:
                self.registro.sistema("Modelo local disponível", f"{self.cfg.modelo} em {self.cfg.url_llm}")
            self._llm_ok, self._llm_erro = True, ""
            return True
        except ErroLLM as erro:
            if self._llm_ok is not False or str(erro) != self._llm_erro:
                self.registro.evento("sistema", "Modelo local indisponível", str(erro), nivel="erro")
            self._llm_ok, self._llm_erro = False, str(erro)
            return False

    def _aguardar_llm(self) -> None:
        espera = 15.0
        while not self._parar.is_set():
            self.atividade.definir("aguardando_llm", self._llm_erro)
            self._dormir(espera)
            if self._parar.is_set() or self._verificar_llm():
                return
            espera = min(300.0, espera * 1.6)

    # ------------------------------------------------------------------ manutenção
    def _manutencao(self) -> None:
        agora = time.time()
        if agora - self._ultima_vigia >= 30:
            self._ultima_vigia = agora
            try:
                self.amb.supervisor.vigiar()
            except Exception as erro:
                self.registro.erro("Falha ao vigiar serviços", str(erro))
        self._disparar_automacoes()
        if agora - self._ultima_poda >= 86400:
            self._ultima_poda = agora
            self.banco.podar_eventos(90)

    def _disparar_automacoes(self) -> None:
        for automacao in self.banco.automacoes_vencidas():
            self.banco.marcar_automacao_executada(automacao["id"], automacao["intervalo_min"])
            if self.banco.existe_tarefa_aberta(automacao["titulo"]):
                continue  # a execução anterior ainda está na fila
            novo_id = self.banco.criar_tarefa(
                automacao["titulo"],
                automacao["descricao"],
                automacao["area"],
                prioridade=2,
                origem=f"automacao:{automacao['id']}",
            )
            self.registro.evento("automacao", f"Rotina disparada: {automacao['titulo']} (tarefa #{novo_id})")

    def _atualizar_resumo(self, forcar: bool = False) -> None:
        """Mantém a narrativa da semana em dia e fecha a semana anterior quando ela vira."""
        _, _, chave_atual = modulo_resumo.limites_semana()
        ultima_chave = self.banco.obter("resumo_semana", "")
        ultima_vez = float(self.banco.obter("resumo_atualizado_em", 0) or 0)
        try:
            if ultima_chave and ultima_chave != chave_atual:
                modulo_resumo.gerar_narrativa(self.llm, self.banco, ultima_chave)  # fechamento da semana que passou
                self.registro.evento("resumo", f"Resumo final da semana de {ultima_chave} gerado")
                forcar = True
            if forcar or time.time() - ultima_vez >= self.cfg.intervalo_resumo_horas * 3600:
                self.atividade.definir("resumindo", "Escrevendo o resumo da semana")
                modulo_resumo.gerar_narrativa(self.llm, self.banco)
                self.banco.definir("resumo_semana", chave_atual)
                self.banco.definir("resumo_atualizado_em", time.time())
                self.registro.evento("resumo", "Resumo da semana atualizado")
        except LLMIndisponivel:
            raise
        except Exception as erro:
            self.banco.definir("resumo_atualizado_em", time.time())
            self.registro.erro("Falha ao gerar o resumo semanal", str(erro))

    # ------------------------------------------------------------------ escolha e execução de tarefas
    def _escolher_tarefa(self) -> dict | None:
        proxima = self.banco.proxima_tarefa()
        concluidas = int(self.banco.obter("concluidas_desde_planejamento", 0) or 0)
        precisa_planejar = proxima is None or concluidas >= self.cfg.tarefas_por_planejamento
        if proxima is not None and proxima["tipo"] == "planejamento":
            return proxima
        if precisa_planejar and time.time() >= self._proximo_planejamento:
            pendente = self.banco.planejamento_pendente()
            if pendente:
                return pendente  # um ciclo interrompido anteriormente: retoma em vez de criar outro
            novo_id = self.banco.criar_tarefa(
                TITULO_PLANEJAMENTO,
                "Revisar a situação da empresa e definir os próximos passos.",
                area="produto",
                prioridade=1,
                tipo="planejamento",
                origem="sistema",
            )
            return self.banco.tarefa(novo_id)
        return proxima

    def _executar_tarefa(self, tarefa: dict) -> None:
        planejamento = tarefa["tipo"] == "planejamento"
        tarefa["tentativas"] += 1
        self.banco.atualizar_tarefa(tarefa["id"], status="em_andamento", iniciado_em=time.time(), tentativas=tarefa["tentativas"])
        self.atividade.definir("planejando" if planejamento else "trabalhando", tarefa["titulo"], tarefa)
        self.registro.evento(
            "tarefa",
            "Planejando os próximos passos" if planejamento else f"Iniciando tarefa #{tarefa['id']}: {tarefa['titulo']}",
            tarefa["descricao"],
            tarefa_id=tarefa["id"],
        )
        abertas_antes = self.banco.contar_tarefas_abertas("trabalho")
        try:
            resultado = self.executor.executar(tarefa)
        except (Interrompido, LLMIndisponivel):
            # Não foi culpa da tarefa: ela volta para a fila sem gastar a tentativa.
            self.banco.atualizar_tarefa(tarefa["id"], status="pendente", tentativas=tarefa["tentativas"] - 1)
            raise
        except ErroLLM as erro:
            # O servidor respondeu, mas recusou o pedido. A tentativa conta (uma tarefa específica pode ser a
            # causa) e há uma pausa, para um erro de configuração não queimar a fila inteira em segundos.
            self.registro.erro(f"O modelo recusou o pedido na tarefa #{tarefa['id']}", str(erro), tarefa["id"])
            resultado = {"situacao": "incompleta", "resultado": "", "notas": tarefa.get("notas", "")}
            self._dormir(30)
        except Exception as erro:
            self.registro.erro(f"Erro inesperado na tarefa #{tarefa['id']}", traceback.format_exc(), tarefa["id"])
            resultado = {"situacao": "incompleta", "resultado": "", "notas": f"Erro inesperado: {erro}"}

        agora = time.time()
        if planejamento:
            self.banco.atualizar_tarefa(tarefa["id"], status="concluida", concluido_em=agora, resultado=resultado["resultado"])
            self.banco.definir("concluidas_desde_planejamento", 0)
            criadas = self.banco.contar_tarefas_abertas("trabalho") - abertas_antes
            if criadas <= 0:
                # Planejamento sem tarefas novas: espera cada vez mais antes de tentar de novo.
                self._planejamentos_vazios += 1
                espera = min(3600, 300 * self._planejamentos_vazios)
                self._proximo_planejamento = agora + espera
                self.registro.evento(
                    "plano", f"Planejamento sem novas tarefas; nova tentativa em {espera // 60} min", resultado["resultado"]
                )
            else:
                self._planejamentos_vazios = 0
                self.registro.evento("plano", f"Planejamento concluído: {criadas} tarefa(s) nova(s)", resultado["resultado"])
            return

        if resultado["situacao"] == "incompleta" and tarefa["tentativas"] < self.cfg.max_tentativas_tarefa:
            self.banco.atualizar_tarefa(tarefa["id"], status="pendente", notas=resultado["notas"])
            self.registro.evento(
                "tarefa",
                f"Tarefa #{tarefa['id']} não terminou nesta sessão e voltou para a fila",
                resultado["notas"],
                nivel="aviso",
                tarefa_id=tarefa["id"],
            )
            return

        sucesso = resultado["situacao"] == "concluida"
        texto = resultado["resultado"] or (
            "Não foi concluída após várias tentativas. Últimas anotações:\n" + resultado.get("notas", "")
        )
        self.banco.atualizar_tarefa(
            tarefa["id"], status="concluida" if sucesso else "falhou", concluido_em=agora, resultado=texto
        )
        self.banco.definir(
            "concluidas_desde_planejamento", int(self.banco.obter("concluidas_desde_planejamento", 0) or 0) + 1
        )
        # O resultado vira memória pesquisável, mesmo que o modelo tenha esquecido de salvar.
        self.banco.salvar_memoria(
            f"{'Resultado' if sucesso else 'Falha'} da tarefa: {tarefa['titulo']}", texto[:3000], "aprendizado"
        )
        self.registro.evento(
            "tarefa",
            f"Tarefa #{tarefa['id']} {'concluída' if sucesso else 'falhou'}: {tarefa['titulo']}",
            texto,
            nivel="info" if sucesso else "erro",
            tarefa_id=tarefa["id"],
        )

    # ------------------------------------------------------------------ laço principal
    def _ciclo(self) -> None:
        if not self.empresa_iniciada():
            self.atividade.definir("aguardando_inicio", "Aguardando o dono iniciar a empresa pelo painel")
            self._dormir(2)
            return
        if self.pausado():
            self.atividade.definir("pausado", "Pausado pelo dono")
            self._dormir(2)
            return
        self._manutencao()
        tarefa = self._escolher_tarefa()
        if tarefa is None:
            self._atualizar_resumo()
            agora = time.time()
            candidatos = [agora + float(self.cfg.intervalo_ocioso_seg)]
            despertar = self.banco.proximo_despertar()
            if despertar and despertar > agora:
                candidatos.append(despertar)  # próxima tarefa adiada
            if self._proximo_planejamento > agora:
                candidatos.append(self._proximo_planejamento)
            espera = max(1.0, min(candidatos) - agora)
            self.atividade.definir("ocioso", "Sem tarefas disponíveis no momento")
            self._dormir(espera)
            return
        self._executar_tarefa(tarefa)
        self._atualizar_resumo()

    def rodar(self) -> None:
        """Laço eterno do agente. Só retorna quando ``parar()`` é chamado."""
        self._preparar()
        if not self._verificar_llm():
            self._aguardar_llm()
        while not self._parar.is_set():
            try:
                self._ciclo()
            except Interrompido:
                break
            except LLMIndisponivel as erro:
                self._llm_ok, self._llm_erro = False, str(erro)
                self.registro.evento("sistema", "Modelo local indisponível; aguardando para retomar", str(erro), nivel="erro")
                self._aguardar_llm()
            except Exception:
                self.registro.erro("Erro inesperado no laço do agente", traceback.format_exc())
                self._dormir(15)
        self._encerrar()

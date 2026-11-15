"""Serviços em segundo plano e automações recorrentes.

Serviços são processos de longa duração criados pelo agente (um backend, um
robô de atendimento, um túnel). O supervisor os religa quando caem e quando a
máquina reinicia. Automações são tarefas que voltam para a fila em intervalos
fixos (verificar e-mail, publicar conteúdo, medir indicadores).
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path

import psutil

from .base import Ambiente, Catalogo, P
from .gestao import AREAS
from .sistema import EH_WINDOWS, ambiente_de_processo, comando_proibido, encerrar_arvore, linha_de_comando, resolver_caminho

MAX_REINICIOS_POR_HORA = 5


class Supervisor:
    def __init__(self, amb: Ambiente):
        self.amb = amb
        self._processos: dict[str, subprocess.Popen] = {}
        self._reinicios: dict[str, list[float]] = {}
        self._trava = threading.RLock()

    def _arquivo_log(self, nome: str) -> Path:
        return self.amb.cfg.dir_logs / f"servico_{nome}.log"

    @staticmethod
    def _vivo(pid: int | None, criado: float | None) -> bool:
        """Confere se o PID ainda é o mesmo processo que iniciamos (PIDs são reutilizados)."""
        if not pid:
            return False
        try:
            processo = psutil.Process(pid)
            if processo.status() == psutil.STATUS_ZOMBIE:
                return False
            return criado is None or abs(processo.create_time() - criado) < 2
        except psutil.Error:
            return False

    def _lancar(self, nome: str, comando: str, diretorio: str) -> subprocess.Popen:
        pasta = resolver_caminho(self.amb.cfg.dir_trabalho, diretorio)
        pasta.mkdir(parents=True, exist_ok=True)
        opcoes: dict = {}
        if EH_WINDOWS:
            opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            opcoes["start_new_session"] = True
        saida = open(self._arquivo_log(nome), "ab")
        saida.write(f"\n===== iniciado em {time.strftime('%d/%m/%Y %H:%M:%S')} =====\n".encode("utf-8"))
        saida.flush()
        processo = subprocess.Popen(
            linha_de_comando(comando),
            cwd=str(pasta),
            stdin=subprocess.DEVNULL,
            stdout=saida,
            stderr=subprocess.STDOUT,
            env=ambiente_de_processo(),
            **opcoes,
        )
        saida.close()
        try:
            criado = psutil.Process(processo.pid).create_time()
        except psutil.Error:
            criado = time.time()
        self._processos[nome] = processo
        self.amb.banco.atualizar_servico(nome, pid=processo.pid, pid_criado=criado)
        return processo

    def _parar_processo(self, nome: str) -> None:
        processo = self._processos.pop(nome, None)
        if processo is not None and processo.poll() is None:
            encerrar_arvore(processo.pid)
            return
        registro = self.amb.banco.servico(nome)
        if registro and self._vivo(registro.get("pid"), registro.get("pid_criado")):
            encerrar_arvore(registro["pid"])  # sobra de uma execução anterior do agente

    # ------------------------------------------------------------------ operações
    def iniciar(self, nome: str, comando: str, diretorio: str = "") -> str:
        nome = re.sub(r"[^a-z0-9_-]", "-", nome.strip().lower()).strip("-")
        if not nome:
            return "ERRO: informe um nome para o serviço."
        if comando_proibido(comando):
            return "ERRO: comando recusado por colocar a máquina do agente em risco."
        with self._trava:
            self._parar_processo(nome)
            self.amb.banco.salvar_servico(nome, comando, diretorio)
            processo = self._lancar(nome, comando, diretorio)
        time.sleep(2.5)
        if processo.poll() is not None:
            self.amb.banco.atualizar_servico(nome, ativo=0)
            return (
                f"ERRO: o serviço '{nome}' encerrou logo ao iniciar (código {processo.returncode}). "
                f"Últimas linhas do log:\n{self.logs(nome, 25)}"
            )
        self.amb.registro.evento("servico", f"Serviço iniciado: {nome}", comando)
        return f"Serviço '{nome}' em execução (PID {processo.pid}). Ele será religado automaticamente se cair."

    def parar(self, nome: str) -> str:
        nome = nome.strip().lower()
        with self._trava:
            if not self.amb.banco.servico(nome):
                return f"ERRO: não existe serviço chamado '{nome}'."
            self._parar_processo(nome)
            self.amb.banco.atualizar_servico(nome, ativo=0, pid=None, pid_criado=None)
        self.amb.registro.evento("servico", f"Serviço parado: {nome}")
        return f"Serviço '{nome}' parado."

    def estado(self) -> list[dict]:
        with self._trava:
            itens = []
            for registro in self.amb.banco.servicos():
                processo = self._processos.get(registro["nome"])
                rodando = (processo is not None and processo.poll() is None) or (
                    processo is None and self._vivo(registro.get("pid"), registro.get("pid_criado"))
                )
                itens.append(
                    {
                        "nome": registro["nome"],
                        "comando": registro["comando"],
                        "diretorio": registro["diretorio"],
                        "ativo": bool(registro["ativo"]),
                        "rodando": bool(rodando),
                        "pid": registro.get("pid") if rodando else None,
                    }
                )
            return itens

    def logs(self, nome: str, linhas: int = 40) -> str:
        arquivo = self._arquivo_log(nome.strip().lower())
        if not arquivo.exists():
            return "(sem registros)"
        with open(arquivo, "rb") as f:
            f.seek(0, 2)
            tamanho = f.tell()
            f.seek(max(0, tamanho - 20000))
            texto = f.read().decode("utf-8", errors="replace")
        return "\n".join(texto.splitlines()[-max(1, min(200, linhas)) :]) or "(sem registros)"

    # ------------------------------------------------------------------ supervisão
    def restaurar(self) -> None:
        """Na partida do agente, religa os serviços que deveriam estar no ar."""
        with self._trava:
            for registro in self.amb.banco.servicos(apenas_ativos=True):
                nome = registro["nome"]
                try:
                    self._parar_processo(nome)
                    self._lancar(nome, registro["comando"], registro["diretorio"])
                    self.amb.registro.evento("servico", f"Serviço religado na partida: {nome}")
                except Exception as erro:
                    self.amb.registro.erro(f"Falha ao religar o serviço {nome}", str(erro))

    def vigiar(self) -> None:
        """Religa serviços ativos que caíram, com limite para não entrar em ciclo."""
        with self._trava:
            for registro in self.amb.banco.servicos(apenas_ativos=True):
                nome = registro["nome"]
                processo = self._processos.get(nome)
                if processo is not None and processo.poll() is None:
                    continue
                if processo is None and self._vivo(registro.get("pid"), registro.get("pid_criado")):
                    continue
                agora = time.time()
                historico = [t for t in self._reinicios.get(nome, []) if agora - t < 3600]
                if len(historico) >= MAX_REINICIOS_POR_HORA:
                    self.amb.banco.atualizar_servico(nome, ativo=0)
                    self.amb.registro.erro(
                        f"Serviço {nome} desativado: caiu vezes demais em uma hora",
                        self.logs(nome, 20),
                    )
                    continue
                historico.append(agora)
                self._reinicios[nome] = historico
                try:
                    self._processos.pop(nome, None)
                    self._lancar(nome, registro["comando"], registro["diretorio"])
                    self.amb.registro.evento("servico", f"Serviço caiu e foi religado: {nome}", nivel="aviso")
                except Exception as erro:
                    self.amb.registro.erro(f"Falha ao religar o serviço {nome}", str(erro))

    def encerrar_todos(self) -> None:
        """No desligamento do agente, para os processos sem desativá-los (voltam na próxima partida)."""
        with self._trava:
            for nome in list(self._processos):
                try:
                    self._parar_processo(nome)
                except Exception:
                    pass


def descrever_intervalo(minutos: int) -> str:
    if minutos % 1440 == 0:
        dias = minutos // 1440
        return "todo dia" if dias == 1 else f"a cada {dias} dias"
    if minutos % 60 == 0:
        horas = minutos // 60
        return "a cada hora" if horas == 1 else f"a cada {horas} horas"
    return f"a cada {minutos} minutos"


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    supervisor = Supervisor(amb)
    amb.supervisor = supervisor
    banco = amb.banco

    @cat.ferramenta(
        "servico_iniciar",
        "Sobe um processo de longa duração (servidor web, API, robô, túnel) que continua rodando depois da tarefa "
        "e é religado automaticamente se cair ou se a máquina reiniciar.",
        _grupo="operacao",
        nome=P("string", "Nome curto do serviço (letras minúsculas, números e hífen)."),
        comando=P("string", "Comando que inicia o processo e o mantém em primeiro plano."),
        diretorio=P("string", "Subpasta da pasta de trabalho onde rodar.", obrigatorio=False),
    )
    def servico_iniciar(nome: str, comando: str, diretorio: str = "") -> str:
        return supervisor.iniciar(nome, comando, diretorio)

    @cat.ferramenta(
        "servico_parar",
        "Para um serviço e impede que ele seja religado.",
        _grupo="operacao",
        nome=P("string", "Nome do serviço."),
    )
    def servico_parar(nome: str) -> str:
        return supervisor.parar(nome)

    @cat.ferramenta("servico_listar", "Lista os serviços da empresa e se estão rodando.", _grupo="operacao")
    def servico_listar() -> str:
        itens = supervisor.estado()
        if not itens:
            return "Nenhum serviço cadastrado."
        return "\n".join(
            f"- {s['nome']}: {'rodando' if s['rodando'] else 'parado'}"
            f"{'' if s['ativo'] else ' (desativado)'} | comando: {s['comando']}"
            for s in itens
        )

    @cat.ferramenta(
        "servico_logs",
        "Mostra as últimas linhas de saída de um serviço (para diagnosticar erros).",
        _grupo="operacao",
        nome=P("string", "Nome do serviço."),
        linhas=P("integer", "Quantidade de linhas (padrão 40).", obrigatorio=False),
    )
    def servico_logs(nome: str, linhas: int = 40) -> str:
        return supervisor.logs(nome, linhas)

    @cat.ferramenta(
        "automacao_criar",
        "Cria uma rotina recorrente: a cada intervalo, uma tarefa com esta descrição entra na fila. Use para "
        "atendimento (ler e-mails), monitoramento, publicação de conteúdo e coleta de indicadores.",
        _grupo="operacao",
        titulo=P("string", "Título da rotina, começando com um verbo."),
        descricao=P("string", "Instruções completas do que fazer em cada execução."),
        intervalo_minutos=P("integer", "Intervalo entre execuções em minutos (mínimo 15; 1440 = diário)."),
        area=P("string", "Área responsável.", obrigatorio=False, enum=AREAS),
    )
    def automacao_criar(titulo: str, descricao: str, intervalo_minutos: int, area: str = "operacoes") -> str:
        if any(a["titulo"].lower() == titulo.strip().lower() for a in banco.automacoes()):
            return "Já existe uma automação ativa com esse título."
        if len(banco.automacoes()) >= 20:
            return "NEGADO: há automações demais. Remova alguma antes de criar outra."
        novo_id = banco.criar_automacao(titulo, descricao, intervalo_minutos, area if area in AREAS else "operacoes")
        intervalo = max(15, int(intervalo_minutos))
        amb.registro.evento("automacao", f"Automação criada: {titulo} ({descrever_intervalo(intervalo)})", descricao)
        return f"Automação #{novo_id} criada: {descrever_intervalo(intervalo)}."

    @cat.ferramenta("automacao_listar", "Lista as rotinas recorrentes ativas.", _grupo="operacao")
    def automacao_listar() -> str:
        itens = banco.automacoes()
        if not itens:
            return "Nenhuma automação ativa."
        return "\n".join(f"#{a['id']} {a['titulo']} ({descrever_intervalo(a['intervalo_min'])})" for a in itens)

    @cat.ferramenta(
        "automacao_remover",
        "Desativa uma rotina recorrente.",
        _grupo="operacao",
        id=P("integer", "Número da automação."),
    )
    def automacao_remover(id: int) -> str:
        if not banco.remover_automacao(id):
            return "ERRO: automação não encontrada."
        amb.registro.evento("automacao", f"Automação #{id} removida")
        return f"Automação #{id} removida."

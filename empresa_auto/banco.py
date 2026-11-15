"""Persistência em SQLite.

Todo o estado da empresa fica neste banco: se a máquina reiniciar, o agente
retoma exatamente de onde parou. Cada thread usa a sua própria conexão.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

ESQUEMA = """
CREATE TABLE IF NOT EXISTS empresa (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    tipo TEXT NOT NULL,
    nivel TEXT NOT NULL DEFAULT 'info',
    titulo TEXT NOT NULL,
    detalhe TEXT NOT NULL DEFAULT '',
    tarefa_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos (ts);

CREATE TABLE IF NOT EXISTS tarefas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    area TEXT NOT NULL DEFAULT 'operacoes',
    tipo TEXT NOT NULL DEFAULT 'trabalho',
    prioridade INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'pendente',
    origem TEXT NOT NULL DEFAULT 'agente',
    criado_em REAL NOT NULL,
    iniciado_em REAL,
    concluido_em REAL,
    nao_antes_de REAL NOT NULL DEFAULT 0,
    tentativas INTEGER NOT NULL DEFAULT 0,
    resultado TEXT NOT NULL DEFAULT '',
    notas TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tarefas_status ON tarefas (status);

CREATE TABLE IF NOT EXISTS memorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    categoria TEXT NOT NULL DEFAULT 'geral',
    titulo TEXT NOT NULL,
    conteudo TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    titulo TEXT NOT NULL,
    justificativa TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS metricas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    nome TEXT NOT NULL,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bloqueios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    titulo TEXT NOT NULL,
    detalhe TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'aberto'
);

CREATE TABLE IF NOT EXISTS automacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    area TEXT NOT NULL DEFAULT 'operacoes',
    intervalo_min INTEGER NOT NULL,
    proxima REAL NOT NULL,
    ultima REAL,
    ativa INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS servicos (
    nome TEXT PRIMARY KEY,
    comando TEXT NOT NULL,
    diretorio TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    pid INTEGER,
    pid_criado REAL,
    criado_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS gastos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    valor REAL NOT NULL,
    motivo TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS envios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    canal TEXT NOT NULL,
    destino TEXT NOT NULL,
    assunto TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS resumos (
    semana TEXT PRIMARY KEY,
    texto TEXT NOT NULL,
    atualizado_em REAL NOT NULL
);
"""

STATUS_ABERTOS = ("pendente", "em_andamento")


class Banco:
    def __init__(self, caminho: Path | str):
        self.caminho = str(caminho)
        self._local = threading.local()
        self._escrita = threading.Lock()
        self._fts = True
        with self._escrita:
            con = self._con()
            con.executescript(ESQUEMA)
            try:
                con.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memorias_fts "
                    "USING fts5(titulo, conteudo, categoria, content='memorias', content_rowid='id')"
                )
            except sqlite3.OperationalError:
                self._fts = False  # SQLite compilado sem FTS5: a busca cai para LIKE
            con.commit()

    # ------------------------------------------------------------------
    def _con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.caminho, timeout=30, check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            self._local.con = con
        return con

    def _executar(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._escrita:
            con = self._con()
            cur = con.execute(sql, tuple(params))
            con.commit()
            return cur.lastrowid or 0

    def _consultar(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        cur = self._con().execute(sql, tuple(params))
        return [dict(linha) for linha in cur.fetchall()]

    def _um(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        linhas = self._consultar(sql, params)
        return linhas[0] if linhas else None

    # ------------------------------------------------------------------ empresa
    def definir(self, chave: str, valor: Any) -> None:
        self._executar(
            "INSERT INTO empresa (chave, valor) VALUES (?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (chave, json.dumps(valor, ensure_ascii=False)),
        )

    def obter(self, chave: str, padrao: Any = None) -> Any:
        linha = self._um("SELECT valor FROM empresa WHERE chave = ?", (chave,))
        if not linha:
            return padrao
        try:
            return json.loads(linha["valor"])
        except json.JSONDecodeError:
            return padrao

    def empresa(self) -> dict:
        dados = {}
        for linha in self._consultar("SELECT chave, valor FROM empresa"):
            try:
                dados[linha["chave"]] = json.loads(linha["valor"])
            except json.JSONDecodeError:
                continue
        return dados

    # ------------------------------------------------------------------ eventos
    def adicionar_evento(
        self, tipo: str, titulo: str, detalhe: str = "", nivel: str = "info", tarefa_id: int | None = None
    ) -> int:
        return self._executar(
            "INSERT INTO eventos (ts, tipo, nivel, titulo, detalhe, tarefa_id) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), tipo, nivel, titulo, detalhe, tarefa_id),
        )

    def eventos_depois(self, depois_id: int = 0, limite: int = 200) -> list[dict]:
        return self._consultar(
            "SELECT * FROM eventos WHERE id > ? ORDER BY id ASC LIMIT ?", (depois_id, limite)
        )

    def eventos_recentes(self, limite: int = 200) -> list[dict]:
        linhas = self._consultar("SELECT * FROM eventos ORDER BY id DESC LIMIT ?", (limite,))
        return list(reversed(linhas))

    def eventos_periodo(self, inicio: float, fim: float, tipos: tuple[str, ...] = ()) -> list[dict]:
        sql = "SELECT * FROM eventos WHERE ts >= ? AND ts < ?"
        params: list[Any] = [inicio, fim]
        if tipos:
            sql += f" AND tipo IN ({','.join('?' * len(tipos))})"
            params.extend(tipos)
        return self._consultar(sql + " ORDER BY id ASC", params)

    def podar_eventos(self, manter_dias: int = 60) -> None:
        self._executar("DELETE FROM eventos WHERE ts < ?", (time.time() - manter_dias * 86400,))

    # ------------------------------------------------------------------ tarefas
    def criar_tarefa(
        self,
        titulo: str,
        descricao: str = "",
        area: str = "operacoes",
        prioridade: int = 3,
        tipo: str = "trabalho",
        origem: str = "agente",
        adiar_minutos: float = 0,
    ) -> int:
        agora = time.time()
        return self._executar(
            "INSERT INTO tarefas (titulo, descricao, area, tipo, prioridade, origem, criado_em, nao_antes_de) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                titulo.strip(),
                descricao.strip(),
                area,
                tipo,
                max(1, min(5, int(prioridade))),
                origem,
                agora,
                agora + max(0.0, float(adiar_minutos)) * 60,
            ),
        )

    def tarefa(self, tarefa_id: int) -> dict | None:
        return self._um("SELECT * FROM tarefas WHERE id = ?", (tarefa_id,))

    def proxima_tarefa(self) -> dict | None:
        return self._um(
            "SELECT * FROM tarefas WHERE status = 'pendente' AND nao_antes_de <= ? "
            "ORDER BY prioridade ASC, id ASC LIMIT 1",
            (time.time(),),
        )

    def planejamento_pendente(self) -> dict | None:
        return self._um("SELECT * FROM tarefas WHERE tipo = 'planejamento' AND status = 'pendente' ORDER BY id LIMIT 1")

    def proximo_despertar(self) -> float | None:
        """Instante em que a próxima tarefa adiada fica disponível."""
        linha = self._um(
            "SELECT MIN(nao_antes_de) AS t FROM tarefas WHERE status = 'pendente' AND nao_antes_de > ?",
            (time.time(),),
        )
        return linha["t"] if linha and linha["t"] else None

    def tarefas(self, status: str | None = None, limite: int = 50) -> list[dict]:
        if status:
            return self._consultar(
                "SELECT * FROM tarefas WHERE status = ? ORDER BY prioridade ASC, id ASC LIMIT ?",
                (status, limite),
            )
        return self._consultar("SELECT * FROM tarefas ORDER BY id DESC LIMIT ?", (limite,))

    def tarefas_abertas(self) -> list[dict]:
        return self._consultar(
            "SELECT * FROM tarefas WHERE status IN ('pendente', 'em_andamento') "
            "ORDER BY CASE status WHEN 'em_andamento' THEN 0 ELSE 1 END, prioridade ASC, id ASC"
        )

    def tarefas_finalizadas(self, limite: int = 15, tipo: str | None = "trabalho") -> list[dict]:
        sql = "SELECT * FROM tarefas WHERE status IN ('concluida', 'falhou', 'cancelada')"
        params: list[Any] = []
        if tipo:
            sql += " AND tipo = ?"
            params.append(tipo)
        return self._consultar(sql + " ORDER BY concluido_em DESC LIMIT ?", params + [limite])

    def tarefas_periodo(self, inicio: float, fim: float) -> list[dict]:
        return self._consultar(
            "SELECT * FROM tarefas WHERE concluido_em >= ? AND concluido_em < ? ORDER BY concluido_em ASC",
            (inicio, fim),
        )

    def existe_tarefa_aberta(self, titulo: str) -> bool:
        linha = self._um(
            "SELECT id FROM tarefas WHERE status IN ('pendente', 'em_andamento') "
            "AND lower(titulo) = lower(?) LIMIT 1",
            (titulo.strip(),),
        )
        return linha is not None

    def contar_tarefas_abertas(self, tipo: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM tarefas WHERE status IN ('pendente', 'em_andamento')"
        params: list[Any] = []
        if tipo:
            sql += " AND tipo = ?"
            params.append(tipo)
        return int(self._um(sql, params)["n"])

    def atualizar_tarefa(self, tarefa_id: int, **campos: Any) -> None:
        if not campos:
            return
        colunas = ", ".join(f"{nome} = ?" for nome in campos)
        self._executar(f"UPDATE tarefas SET {colunas} WHERE id = ?", list(campos.values()) + [tarefa_id])

    def retomar_interrompidas(self) -> int:
        """Tarefas que estavam em execução quando o processo caiu voltam para a fila."""
        linhas = self._consultar("SELECT id FROM tarefas WHERE status = 'em_andamento'")
        if linhas:
            self._executar("UPDATE tarefas SET status = 'pendente' WHERE status = 'em_andamento'")
        return len(linhas)

    def contagem_tarefas(self) -> dict:
        contagem = {"pendente": 0, "em_andamento": 0, "concluida": 0, "falhou": 0, "cancelada": 0}
        for linha in self._consultar(
            "SELECT status, COUNT(*) AS n FROM tarefas WHERE tipo = 'trabalho' GROUP BY status"
        ):
            contagem[linha["status"]] = linha["n"]
        return contagem

    # ------------------------------------------------------------------ memória
    def salvar_memoria(self, titulo: str, conteudo: str, categoria: str = "geral") -> int:
        with self._escrita:
            con = self._con()
            cur = con.execute(
                "INSERT INTO memorias (ts, categoria, titulo, conteudo) VALUES (?, ?, ?, ?)",
                (time.time(), categoria, titulo.strip(), conteudo.strip()),
            )
            if self._fts:
                con.execute(
                    "INSERT INTO memorias_fts (rowid, titulo, conteudo, categoria) VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, titulo, conteudo, categoria),
                )
            con.commit()
            return cur.lastrowid or 0

    def buscar_memorias(self, consulta: str, limite: int = 6) -> list[dict]:
        termos = [t for t in "".join(c if c.isalnum() else " " for c in consulta).split() if len(t) > 2]
        if not termos:
            return self.memorias_recentes(limite)
        if self._fts:
            expressao = " OR ".join(f'"{t}"' for t in termos[:12])
            try:
                return self._consultar(
                    "SELECT m.* FROM memorias_fts f JOIN memorias m ON m.id = f.rowid "
                    "WHERE memorias_fts MATCH ? ORDER BY bm25(memorias_fts) LIMIT ?",
                    (expressao, limite),
                )
            except sqlite3.OperationalError:
                pass
        condicoes = " OR ".join("titulo LIKE ? OR conteudo LIKE ?" for _ in termos[:6])
        params: list[Any] = []
        for termo in termos[:6]:
            params += [f"%{termo}%", f"%{termo}%"]
        return self._consultar(
            f"SELECT * FROM memorias WHERE {condicoes} ORDER BY id DESC LIMIT ?", params + [limite]
        )

    def memorias_recentes(self, limite: int = 6) -> list[dict]:
        return self._consultar("SELECT * FROM memorias ORDER BY id DESC LIMIT ?", (limite,))

    def contar_memorias(self) -> int:
        return int(self._um("SELECT COUNT(*) AS n FROM memorias")["n"])

    # ------------------------------------------------------------------ decisões e métricas
    def registrar_decisao(self, titulo: str, justificativa: str = "") -> int:
        return self._executar(
            "INSERT INTO decisoes (ts, titulo, justificativa) VALUES (?, ?, ?)",
            (time.time(), titulo.strip(), justificativa.strip()),
        )

    def decisoes(self, limite: int = 10, inicio: float = 0, fim: float | None = None) -> list[dict]:
        return self._consultar(
            "SELECT * FROM decisoes WHERE ts >= ? AND ts < ? ORDER BY id DESC LIMIT ?",
            (inicio, fim or time.time() + 1, limite),
        )

    def registrar_metrica(self, nome: str, valor: Any) -> int:
        return self._executar(
            "INSERT INTO metricas (ts, nome, valor) VALUES (?, ?, ?)", (time.time(), nome.strip(), str(valor))
        )

    def metricas_atuais(self) -> list[dict]:
        return self._consultar(
            "SELECT m.* FROM metricas m JOIN (SELECT nome, MAX(id) AS id FROM metricas GROUP BY nome) u "
            "ON u.id = m.id ORDER BY m.nome"
        )

    # ------------------------------------------------------------------ bloqueios
    def registrar_bloqueio(self, titulo: str, detalhe: str = "") -> int:
        existente = self._um(
            "SELECT id FROM bloqueios WHERE status = 'aberto' AND lower(titulo) = lower(?)", (titulo.strip(),)
        )
        if existente:
            return existente["id"]
        return self._executar(
            "INSERT INTO bloqueios (ts, titulo, detalhe) VALUES (?, ?, ?)",
            (time.time(), titulo.strip(), detalhe.strip()),
        )

    def bloqueios(self, status: str | None = "aberto", limite: int = 30) -> list[dict]:
        if status:
            return self._consultar(
                "SELECT * FROM bloqueios WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limite)
            )
        return self._consultar("SELECT * FROM bloqueios ORDER BY id DESC LIMIT ?", (limite,))

    def resolver_bloqueio(self, bloqueio_id: int) -> None:
        self._executar("UPDATE bloqueios SET status = 'resolvido' WHERE id = ?", (bloqueio_id,))

    # ------------------------------------------------------------------ automações
    def criar_automacao(self, titulo: str, descricao: str, intervalo_min: int, area: str = "operacoes") -> int:
        intervalo = max(15, int(intervalo_min))
        return self._executar(
            "INSERT INTO automacoes (titulo, descricao, area, intervalo_min, proxima) VALUES (?, ?, ?, ?, ?)",
            (titulo.strip(), descricao.strip(), area, intervalo, time.time() + intervalo * 60),
        )

    def automacoes(self, apenas_ativas: bool = True) -> list[dict]:
        sql = "SELECT * FROM automacoes"
        if apenas_ativas:
            sql += " WHERE ativa = 1"
        return self._consultar(sql + " ORDER BY id ASC")

    def automacoes_vencidas(self) -> list[dict]:
        return self._consultar("SELECT * FROM automacoes WHERE ativa = 1 AND proxima <= ?", (time.time(),))

    def marcar_automacao_executada(self, automacao_id: int, intervalo_min: int) -> None:
        agora = time.time()
        self._executar(
            "UPDATE automacoes SET ultima = ?, proxima = ? WHERE id = ?",
            (agora, agora + intervalo_min * 60, automacao_id),
        )

    def remover_automacao(self, automacao_id: int) -> bool:
        existe = self._um("SELECT id FROM automacoes WHERE id = ? AND ativa = 1", (automacao_id,))
        if existe:
            self._executar("UPDATE automacoes SET ativa = 0 WHERE id = ?", (automacao_id,))
        return existe is not None

    # ------------------------------------------------------------------ serviços
    def salvar_servico(self, nome: str, comando: str, diretorio: str) -> None:
        self._executar(
            "INSERT INTO servicos (nome, comando, diretorio, ativo, criado_em) VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(nome) DO UPDATE SET comando = excluded.comando, diretorio = excluded.diretorio, ativo = 1",
            (nome, comando, diretorio, time.time()),
        )

    def atualizar_servico(self, nome: str, **campos: Any) -> None:
        if not campos:
            return
        colunas = ", ".join(f"{c} = ?" for c in campos)
        self._executar(f"UPDATE servicos SET {colunas} WHERE nome = ?", list(campos.values()) + [nome])

    def servicos(self, apenas_ativos: bool = False) -> list[dict]:
        sql = "SELECT * FROM servicos"
        if apenas_ativos:
            sql += " WHERE ativo = 1"
        return self._consultar(sql + " ORDER BY nome")

    def servico(self, nome: str) -> dict | None:
        return self._um("SELECT * FROM servicos WHERE nome = ?", (nome,))

    # ------------------------------------------------------------------ gastos e envios
    def registrar_gasto(self, valor: float, motivo: str) -> int:
        return self._executar(
            "INSERT INTO gastos (ts, valor, motivo) VALUES (?, ?, ?)", (time.time(), float(valor), motivo.strip())
        )

    def gasto_desde(self, inicio: float) -> float:
        linha = self._um("SELECT COALESCE(SUM(valor), 0) AS total FROM gastos WHERE ts >= ?", (inicio,))
        return float(linha["total"])

    def gastos(self, limite: int = 20, inicio: float = 0, fim: float | None = None) -> list[dict]:
        return self._consultar(
            "SELECT * FROM gastos WHERE ts >= ? AND ts < ? ORDER BY id DESC LIMIT ?",
            (inicio, fim or time.time() + 1, limite),
        )

    def registrar_envio(self, canal: str, destino: str, assunto: str = "") -> int:
        return self._executar(
            "INSERT INTO envios (ts, canal, destino, assunto) VALUES (?, ?, ?, ?)",
            (time.time(), canal, destino, assunto),
        )

    def contar_envios(self, canal: str, desde: float, ate: float | None = None) -> int:
        linha = self._um(
            "SELECT COUNT(*) AS n FROM envios WHERE canal = ? AND ts >= ? AND ts < ?",
            (canal, desde, ate or time.time() + 1),
        )
        return int(linha["n"])

    # ------------------------------------------------------------------ resumos
    def salvar_resumo(self, semana: str, texto: str) -> None:
        self._executar(
            "INSERT INTO resumos (semana, texto, atualizado_em) VALUES (?, ?, ?) "
            "ON CONFLICT(semana) DO UPDATE SET texto = excluded.texto, atualizado_em = excluded.atualizado_em",
            (semana, texto, time.time()),
        )

    def resumo(self, semana: str) -> dict | None:
        return self._um("SELECT * FROM resumos WHERE semana = ?", (semana,))

    def semanas_com_resumo(self) -> list[str]:
        return [linha["semana"] for linha in self._consultar("SELECT semana FROM resumos ORDER BY semana DESC")]

    # ------------------------------------------------------------------ manutenção
    def zerar(self) -> None:
        """Apaga toda a empresa atual (usado apenas pelo comando ``zerar``)."""
        with self._escrita:
            con = self._con()
            for tabela in (
                "empresa",
                "eventos",
                "tarefas",
                "memorias",
                "decisoes",
                "metricas",
                "bloqueios",
                "automacoes",
                "servicos",
                "gastos",
                "envios",
                "resumos",
            ):
                con.execute(f"DELETE FROM {tabela}")
            if self._fts:
                con.execute("INSERT INTO memorias_fts (memorias_fts) VALUES ('delete-all')")
            con.commit()

"""Extensões: servidores MCP (Model Context Protocol) instalados pelo agente.

O MCP é o padrão aberto que a comunidade usa para publicar ferramentas para
agentes (bancos de dados, APIs, automação de aplicativos e muito mais). Aqui há
um cliente mínimo do transporte stdio: o agente registra o comando de um
servidor, e as ferramentas dele passam a existir como um grupo próprio.

A configuração (incluindo chaves de API passadas por variável de ambiente)
fica cifrada no cofre.
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
from pathlib import Path

import httpx

from .base import Ambiente, Catalogo, Ferramenta, P
from .sistema import ambiente_de_processo, encerrar_arvore

VERSAO_PROTOCOLO = "2025-06-18"
URL_REGISTRO = "https://registry.modelcontextprotocol.io/v0/servers"


class ErroMCP(Exception):
    pass


class ClienteMCP:
    """Cliente JSON-RPC sobre stdio para um servidor MCP."""

    def __init__(self, nome: str, comando: str, args: list[str], env: dict[str, str], arquivo_log: Path):
        self.nome = nome
        self.comando = comando
        self.args = args
        self.env = env
        self.arquivo_log = arquivo_log
        self._processo: subprocess.Popen | None = None
        self._respostas: dict[int, queue.Queue] = {}
        self._proximo_id = 0
        self._trava = threading.Lock()

    # ------------------------------------------------------------------ transporte
    def iniciar(self, tempo: float = 120) -> None:
        executavel = shutil.which(self.comando) or self.comando
        ambiente = ambiente_de_processo()
        ambiente.update({k: str(v) for k, v in self.env.items()})
        log = open(self.arquivo_log, "ab")
        try:
            self._processo = subprocess.Popen(
                [executavel, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                env=ambiente,
            )
        except OSError as erro:
            raise ErroMCP(f"não foi possível executar '{self.comando}': {erro}") from erro
        finally:
            log.close()
        threading.Thread(target=self._ler_saida, name=f"mcp-{self.nome}", daemon=True).start()
        resposta = self._requisitar(
            "initialize",
            {
                "protocolVersion": VERSAO_PROTOCOLO,
                "capabilities": {},
                "clientInfo": {"name": "empresa-auto", "version": "0.1.0"},
            },
            tempo,
        )
        if "protocolVersion" not in resposta:
            raise ErroMCP("o servidor não completou a inicialização MCP")
        self._enviar({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _enviar(self, mensagem: dict) -> None:
        if self._processo is None or self._processo.poll() is not None or self._processo.stdin is None:
            raise ErroMCP("o servidor da extensão não está em execução")
        dados = (json.dumps(mensagem, ensure_ascii=False) + "\n").encode("utf-8")
        with self._trava:
            try:
                self._processo.stdin.write(dados)
                self._processo.stdin.flush()
            except OSError as erro:
                raise ErroMCP(f"falha ao falar com o servidor da extensão: {erro}") from erro

    def _ler_saida(self) -> None:
        processo = self._processo
        if processo is None or processo.stdout is None:
            return
        for bruto in processo.stdout:
            linha = bruto.decode("utf-8", errors="replace").strip()
            if not linha.startswith("{"):
                continue
            try:
                mensagem = json.loads(linha)
            except json.JSONDecodeError:
                continue
            identificador = mensagem.get("id")
            if "method" in mensagem and identificador is not None:
                # Pedido do servidor para o cliente: só respondemos ao ping.
                try:
                    if mensagem["method"] == "ping":
                        self._enviar({"jsonrpc": "2.0", "id": identificador, "result": {}})
                    else:
                        self._enviar(
                            {
                                "jsonrpc": "2.0",
                                "id": identificador,
                                "error": {"code": -32601, "message": "método não suportado pelo cliente"},
                            }
                        )
                except ErroMCP:
                    pass
            elif identificador is not None and ("result" in mensagem or "error" in mensagem):
                fila = self._respostas.get(identificador)
                if fila is not None:
                    fila.put(mensagem)
        # Fim da saída: o servidor encerrou. Libera quem estiver esperando resposta.
        for fila in list(self._respostas.values()):
            fila.put({"error": {"message": "o servidor da extensão encerrou"}})

    def _requisitar(self, metodo: str, params: dict | None, tempo: float) -> dict:
        with self._trava:
            self._proximo_id += 1
            identificador = self._proximo_id
        fila: queue.Queue = queue.Queue()
        self._respostas[identificador] = fila
        try:
            mensagem: dict = {"jsonrpc": "2.0", "id": identificador, "method": metodo}
            if params is not None:
                mensagem["params"] = params
            self._enviar(mensagem)
            try:
                resposta = fila.get(timeout=tempo)
            except queue.Empty:
                raise ErroMCP(f"o servidor não respondeu a '{metodo}' em {int(tempo)}s") from None
        finally:
            self._respostas.pop(identificador, None)
        if "error" in resposta:
            raise ErroMCP(str(resposta["error"].get("message", resposta["error"])))
        return resposta.get("result") or {}

    # ------------------------------------------------------------------ operações
    def ferramentas(self) -> list[dict]:
        todas: list[dict] = []
        cursor = None
        for _ in range(20):
            resultado = self._requisitar("tools/list", {"cursor": cursor} if cursor else {}, 60)
            todas.extend(resultado.get("tools") or [])
            cursor = resultado.get("nextCursor")
            if not cursor:
                break
        return todas

    def chamar(self, nome: str, argumentos: dict, tempo: float = 300) -> str:
        resultado = self._requisitar("tools/call", {"name": nome, "arguments": argumentos}, tempo)
        partes = []
        for item in resultado.get("content") or []:
            if item.get("type") == "text":
                partes.append(item.get("text", ""))
            elif item.get("type") == "resource" and isinstance(item.get("resource"), dict):
                partes.append(item["resource"].get("text") or f"(recurso {item['resource'].get('uri', '')})")
            else:
                partes.append(f"(conteúdo do tipo {item.get('type')} omitido)")
        if not partes and resultado.get("structuredContent") is not None:
            partes.append(json.dumps(resultado["structuredContent"], ensure_ascii=False))
        texto = "\n".join(partes).strip() or "(sem conteúdo)"
        return f"ERRO da extensão: {texto}" if resultado.get("isError") else texto

    def vivo(self) -> bool:
        return self._processo is not None and self._processo.poll() is None

    def encerrar(self) -> None:
        if self._processo is not None and self._processo.poll() is None:
            encerrar_arvore(self._processo.pid)
        self._processo = None


def _nome_seguro(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", nome.strip().lower()).strip("_")[:24]


class GerenciadorExtensoes:
    CHAVE_COFRE = "extensoes"

    def __init__(self, amb: Ambiente, cat: Catalogo):
        self.amb = amb
        self.cat = cat
        self._clientes: dict[str, ClienteMCP] = {}
        amb.registro.adicionar_fonte_de_segredos(self._segredos)

    def _config(self) -> dict:
        return dict(self.amb.cofre.ler(self.CHAVE_COFRE, {}) or {})

    def _segredos(self) -> set[str]:
        valores = set()
        for item in self._config().values():
            for valor in (item.get("env") or {}).values():
                if len(str(valor)) >= 8:
                    valores.add(str(valor))
        return valores

    def _grupo(self, nome: str) -> str:
        return f"ext_{nome}"

    def _conectar(self, nome: str, comando: str, args: list[str], env: dict[str, str]) -> int:
        self._desconectar(nome)
        cliente = ClienteMCP(nome, comando, args, env, self.amb.cfg.dir_logs / f"extensao_{nome}.log")
        try:
            cliente.iniciar()
            ferramentas = cliente.ferramentas()
        except Exception:
            cliente.encerrar()
            raise
        self._clientes[nome] = cliente
        grupo = self._grupo(nome)
        for item in ferramentas:
            original = item.get("name", "")
            esquema = item.get("inputSchema") or {}
            if esquema.get("type") != "object":
                esquema = {"type": "object", "properties": {}}
            esquema.setdefault("properties", {})
            esquema.setdefault("required", [])
            self.cat.adicionar(
                Ferramenta(
                    nome=f"{grupo}_{re.sub(r'[^a-zA-Z0-9_]', '_', original)}"[:64],
                    descricao=(item.get("description") or original)[:400],
                    parametros=esquema,
                    funcao=self._chamador(nome, original),
                    grupo=grupo,
                )
            )
        self.cat.grupos_extras[grupo] = f"extensão {nome} ({len(ferramentas)} ferramentas)"
        return len(ferramentas)

    def _chamador(self, extensao: str, ferramenta: str):
        def chamar(**argumentos) -> str:
            cliente = self._clientes.get(extensao)
            if cliente is None or not cliente.vivo():
                config = self._config().get(extensao)
                if not config:
                    return "ERRO: esta extensão foi removida."
                self._conectar(extensao, config["comando"], config.get("args", []), config.get("env", {}))
                cliente = self._clientes[extensao]
            return cliente.chamar(ferramenta, argumentos)

        return chamar

    def _desconectar(self, nome: str) -> None:
        cliente = self._clientes.pop(nome, None)
        if cliente is not None:
            cliente.encerrar()
        self.cat.remover_grupo(self._grupo(nome))

    # ------------------------------------------------------------------ operações
    def instalar(self, nome: str, comando: str, args: list[str], env: dict[str, str]) -> str:
        nome = _nome_seguro(nome)
        if not nome:
            return "ERRO: informe um nome para a extensão."
        try:
            quantidade = self._conectar(nome, comando, args, env)
        except Exception as erro:
            return (
                f"ERRO ao iniciar a extensão: {erro}. Confira o comando e os argumentos "
                f"(log em {self.amb.cfg.dir_logs / f'extensao_{nome}.log'})."
            )
        config = self._config()
        config[nome] = {"comando": comando, "args": args, "env": env}
        self.amb.cofre.guardar(self.CHAVE_COFRE, config)
        self.amb.registro.evento("extensao", f"Extensão instalada: {nome} ({quantidade} ferramentas)", f"{comando} {' '.join(args)}")
        return (
            f"Extensão '{nome}' instalada com {quantidade} ferramentas. Para usá-las em uma tarefa, chame "
            f"ativar_ferramentas com o grupo '{self._grupo(nome)}'."
        )

    def remover(self, nome: str) -> str:
        nome = _nome_seguro(nome)
        config = self._config()
        if nome not in config:
            return "ERRO: extensão não encontrada."
        self._desconectar(nome)
        del config[nome]
        self.amb.cofre.guardar(self.CHAVE_COFRE, config)
        self.amb.registro.evento("extensao", f"Extensão removida: {nome}")
        return f"Extensão '{nome}' removida."

    def listar(self) -> list[dict]:
        itens = []
        for nome, config in sorted(self._config().items()):
            cliente = self._clientes.get(nome)
            itens.append(
                {
                    "nome": nome,
                    "comando": f"{config['comando']} {' '.join(config.get('args', []))}".strip(),
                    "ativa": bool(cliente and cliente.vivo()),
                    "ferramentas": len(self.cat.nomes({self._grupo(nome)})),
                }
            )
        return itens

    def carregar_todas(self) -> None:
        """Na partida do agente, religa as extensões já instaladas."""
        for nome, config in self._config().items():
            try:
                self._conectar(nome, config["comando"], config.get("args", []), config.get("env", {}))
            except Exception as erro:
                self.amb.registro.erro(f"Extensão {nome} não iniciou", str(erro))

    def encerrar_todas(self) -> None:
        for nome in list(self._clientes):
            cliente = self._clientes.pop(nome)
            cliente.encerrar()


def buscar_no_registro(consulta: str, limite: int = 8) -> str:
    """Consulta o registro público de servidores MCP."""
    resposta = httpx.get(URL_REGISTRO, params={"search": consulta, "limit": limite}, timeout=30)
    resposta.raise_for_status()
    linhas = []
    vistos = set()
    for item in resposta.json().get("servers", []):
        servidor = item.get("server") or item
        nome = servidor.get("name", "")
        if nome in vistos:
            continue
        vistos.add(nome)
        instalacao = []
        for pacote in servidor.get("packages") or []:
            if (pacote.get("transport") or {}).get("type") not in (None, "stdio"):
                continue
            tipo = pacote.get("registryType")
            identificador = pacote.get("identifier", "")
            if tipo == "npm":
                instalacao.append(f'comando "npx", argumentos ["-y", "{identificador}"]')
            elif tipo == "pypi":
                instalacao.append(f'comando "uvx", argumentos ["{identificador}"]')
            variaveis = [v.get("name") for v in pacote.get("environmentVariables") or [] if v.get("isRequired")]
            if variaveis:
                instalacao.append(f"variáveis obrigatórias: {', '.join(variaveis)}")
        repositorio = (servidor.get("repository") or {}).get("url", "")
        linhas.append(
            f"- {nome}: {servidor.get('description', '')[:200]}\n"
            f"  instalação: {'; '.join(instalacao) or 'ver repositório'}\n"
            f"  repositório: {repositorio}"
        )
    return "\n".join(linhas) or "Nenhuma extensão encontrada no registro para essa consulta."


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    gerenciador = GerenciadorExtensoes(amb, cat)
    amb.extensoes = gerenciador

    @cat.ferramenta(
        "extensao_buscar",
        "Procura extensões (servidores MCP) no registro público da comunidade. Devolve nome, descrição e como instalar.",
        _grupo="expansao",
        consulta=P("string", "O que a extensão deve fazer, em poucas palavras em inglês (ex.: github, postgres, slack)."),
    )
    def extensao_buscar(consulta: str) -> str:
        try:
            return buscar_no_registro(consulta)
        except Exception as erro:
            return f"ERRO ao consultar o registro: {erro}. Use pesquisar_web com 'MCP server {consulta}'."

    @cat.ferramenta(
        "extensao_instalar",
        "Instala uma extensão (servidor MCP por stdio) e disponibiliza as ferramentas dela em um grupo novo. "
        "Exemplo: comando 'npx' com argumentos '[\"-y\", \"@modelcontextprotocol/server-memory\"]'.",
        _grupo="expansao",
        nome=P("string", "Nome curto para a extensão."),
        comando=P("string", "Executável que inicia o servidor (npx, uvx, python, node...)."),
        argumentos=P("string", "Lista JSON com os argumentos do comando, por exemplo [\"-y\", \"pacote\"].", obrigatorio=False),
        ambiente=P("string", "Objeto JSON com variáveis de ambiente (chaves de API), por exemplo {\"TOKEN\": \"abc\"}.", obrigatorio=False),
    )
    def extensao_instalar(nome: str, comando: str, argumentos: str = "[]", ambiente: str = "{}") -> str:
        try:
            args = json.loads(argumentos) if argumentos.strip() else []
            env = json.loads(ambiente) if ambiente.strip() else {}
        except json.JSONDecodeError:
            return "ERRO: 'argumentos' deve ser uma lista JSON e 'ambiente' um objeto JSON."
        if not isinstance(args, list) or not isinstance(env, dict):
            return "ERRO: 'argumentos' deve ser uma lista JSON e 'ambiente' um objeto JSON."
        return gerenciador.instalar(nome, comando, [str(a) for a in args], {str(k): str(v) for k, v in env.items()})

    @cat.ferramenta("extensao_listar", "Lista as extensões instaladas.", _grupo="expansao")
    def extensao_listar() -> str:
        itens = gerenciador.listar()
        if not itens:
            return "Nenhuma extensão instalada."
        return "\n".join(
            f"- {e['nome']} (grupo ext_{e['nome']}, {e['ferramentas']} ferramentas, "
            f"{'ativa' if e['ativa'] else 'parada'}): {e['comando']}"
            for e in itens
        )

    @cat.ferramenta(
        "extensao_remover",
        "Remove uma extensão instalada.",
        _grupo="expansao",
        nome=P("string", "Nome da extensão."),
    )
    def extensao_remover(nome: str) -> str:
        return gerenciador.remover(nome)

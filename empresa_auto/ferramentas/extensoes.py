"""Extensões: servidores MCP (Model Context Protocol) instalados pelo agente.

O MCP é o padrão aberto que a comunidade usa para publicar ferramentas para
agentes (APIs de serviços, bancos de dados, documentação, depuração). Este
módulo traz um cliente mínimo para os dois transportes do protocolo:

* ``stdio``: o servidor é um processo local (npx, uvx, docker, binário);
* ``http``: o servidor é remoto (streamable HTTP) e autentica por cabeçalho fixo.

Fluxos OAuth interativos não são suportados: o agente roda sem humano.

Para poupar memória e contexto do modelo local, as extensões são preguiçosas:
ficam apenas registradas (nome e descrição) e o processo ou a conexão só
começa quando o modelo ativa o grupo delas em uma tarefa.

A configuração (incluindo chaves de API) fica cifrada no cofre.
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
ARQUIVO_CATALOGO = Path(__file__).resolve().parent.parent / "catalogo" / "extensoes.json"
INFO_CLIENTE = {"name": "empresa-auto", "version": "0.2.0"}


class ErroMCP(Exception):
    pass


class _ClienteBase:
    """Operações comuns aos dois transportes."""

    nome = ""

    def _requisitar(self, metodo: str, params: dict | None, tempo: float) -> dict:  # pragma: no cover
        raise NotImplementedError

    def ferramentas(self) -> list[dict]:
        todas: list[dict] = []
        cursor = None
        for _ in range(20):
            resultado = self._requisitar("tools/list", {"cursor": cursor} if cursor else {}, 90)
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


class ClienteMCP(_ClienteBase):
    """Cliente JSON-RPC sobre stdio para um servidor MCP local."""

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
    def iniciar(self, tempo: float = 180) -> None:
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
            {"protocolVersion": VERSAO_PROTOCOLO, "capabilities": {}, "clientInfo": INFO_CLIENTE},
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

    def vivo(self) -> bool:
        return self._processo is not None and self._processo.poll() is None

    def encerrar(self) -> None:
        if self._processo is not None and self._processo.poll() is None:
            encerrar_arvore(self._processo.pid)
        self._processo = None


class ClienteMCPHttp(_ClienteBase):
    """Cliente do transporte streamable HTTP, com autenticação por cabeçalho fixo."""

    def __init__(self, nome: str, url: str, cabecalhos: dict[str, str], transporte: httpx.BaseTransport | None = None):
        self.nome = nome
        self.url = url
        self.cabecalhos = {str(k): str(v) for k, v in cabecalhos.items()}
        self._http = httpx.Client(timeout=httpx.Timeout(120, connect=20), transport=transporte, follow_redirects=True)
        self._sessao: str | None = None
        self._versao: str | None = None
        self._proximo_id = 0
        self._iniciado = False

    def iniciar(self, tempo: float = 60) -> None:
        resposta = self._requisitar(
            "initialize",
            {"protocolVersion": VERSAO_PROTOCOLO, "capabilities": {}, "clientInfo": INFO_CLIENTE},
            tempo,
        )
        if "protocolVersion" not in resposta:
            raise ErroMCP("o servidor não completou a inicialização MCP")
        self._versao = str(resposta["protocolVersion"])
        self._postar({"jsonrpc": "2.0", "method": "notifications/initialized"}, tempo)
        self._iniciado = True

    def _postar(self, mensagem: dict, tempo: float) -> dict | None:
        cabecalhos = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.cabecalhos,
        }
        if self._sessao:
            cabecalhos["Mcp-Session-Id"] = self._sessao
        if self._versao:
            cabecalhos["MCP-Protocol-Version"] = self._versao
        try:
            with self._http.stream("POST", self.url, json=mensagem, headers=cabecalhos, timeout=tempo) as resposta:
                if resposta.status_code in (401, 403):
                    raise ErroMCP("o servidor recusou a credencial (HTTP %d)" % resposta.status_code)
                if resposta.status_code == 404 and self._sessao:
                    self._sessao, self._iniciado = None, False
                    raise ErroMCP("a sessão com o servidor expirou")
                if resposta.status_code >= 400:
                    resposta.read()
                    raise ErroMCP(f"o servidor respondeu HTTP {resposta.status_code}: {resposta.text[:200]}")
                self._sessao = resposta.headers.get("mcp-session-id") or self._sessao
                if "id" not in mensagem:
                    return None  # notificação: o servidor só confirma o recebimento
                if "text/event-stream" in resposta.headers.get("content-type", ""):
                    dados: list[str] = []
                    for linha in resposta.iter_lines():
                        if linha.startswith("data:"):
                            dados.append(linha[5:].lstrip())
                        elif not linha.strip() and dados:
                            try:
                                evento = json.loads("\n".join(dados))
                            except json.JSONDecodeError:
                                evento = None
                            dados = []
                            if isinstance(evento, dict) and evento.get("id") == mensagem["id"] and (
                                "result" in evento or "error" in evento
                            ):
                                return evento
                    raise ErroMCP("o servidor encerrou a resposta sem concluir")
                resposta.read()
                return resposta.json()
        except httpx.HTTPError as erro:
            raise ErroMCP(f"falha de rede ao falar com {self.url}: {erro}") from erro
        except json.JSONDecodeError as erro:
            raise ErroMCP("resposta inválida do servidor") from erro

    def _requisitar(self, metodo: str, params: dict | None, tempo: float) -> dict:
        self._proximo_id += 1
        mensagem: dict = {"jsonrpc": "2.0", "id": self._proximo_id, "method": metodo}
        if params is not None:
            mensagem["params"] = params
        resposta = self._postar(mensagem, tempo) or {}
        if "error" in resposta:
            erro = resposta["error"]
            raise ErroMCP(str(erro.get("message", erro) if isinstance(erro, dict) else erro))
        return resposta.get("result") or {}

    def vivo(self) -> bool:
        return self._iniciado

    def encerrar(self) -> None:
        self._iniciado = False
        try:
            if self._sessao:
                self._http.delete(self.url, headers={**self.cabecalhos, "Mcp-Session-Id": self._sessao}, timeout=10)
        except httpx.HTTPError:
            pass
        self._http.close()


def _nome_seguro(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", nome.strip().lower()).strip("_")[:24]


def carregar_catalogo() -> list[dict]:
    """Lê o catálogo curado de extensões que acompanha o agente."""
    try:
        return list(json.loads(ARQUIVO_CATALOGO.read_text(encoding="utf-8"))["extensoes"])
    except (OSError, ValueError, KeyError):
        return []


def caminho_do_chromium(configurado: str = "") -> str:
    """Localiza um navegador Chromium ou Chrome nesta máquina (o do Playwright tem preferência)."""
    import glob
    import os

    if configurado and Path(configurado).exists():
        return configurado
    bases = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")]
    bases += [str(Path.home() / ".cache" / "ms-playwright"), str(Path.home() / "AppData" / "Local" / "ms-playwright")]
    bases += [str(Path.home() / "Library" / "Caches" / "ms-playwright")]
    for base in [b for b in bases if b]:
        achados = []
        for padrao in ("chromium-*/chrome-*/chrome", "chromium-*/chrome-*/chrome.exe", "chromium-*/chrome-*/Chromium.app/Contents/MacOS/Chromium"):
            achados += glob.glob(str(Path(base) / padrao))
        if achados:
            return sorted(achados)[-1]
    for nome in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        achado = shutil.which(nome)
        if achado:
            return achado
    return ""


def _substituir(valor: object, trocas: dict[str, str]) -> object:
    """Troca marcadores como ``{segredo}`` em textos, listas e dicionários."""
    if isinstance(valor, str):
        for chave, novo in trocas.items():
            valor = valor.replace("{" + chave + "}", novo)
        return valor
    if isinstance(valor, list):
        return [_substituir(v, trocas) for v in valor]
    if isinstance(valor, dict):
        return {k: _substituir(v, trocas) for k, v in valor.items()}
    return valor


class GerenciadorExtensoes:
    CHAVE_COFRE = "extensoes"

    def __init__(self, amb: Ambiente, cat: Catalogo, transporte_http: httpx.BaseTransport | None = None):
        self.amb = amb
        self.cat = cat
        self._clientes: dict[str, _ClienteBase] = {}
        self._transporte_http = transporte_http
        amb.registro.adicionar_fonte_de_segredos(self._segredos)

    # ------------------------------------------------------------------ configuração
    def _config(self) -> dict:
        return dict(self.amb.cofre.ler(self.CHAVE_COFRE, {}) or {})

    def _segredos(self) -> set[str]:
        valores = set()
        for item in self._config().values():
            for origem in (item.get("env") or {}, item.get("cabecalhos") or {}):
                for valor in origem.values():
                    texto = str(valor)
                    if len(texto) >= 8:
                        valores.add(texto)
                        if texto.lower().startswith("bearer "):
                            valores.add(texto[7:])
        return valores

    @staticmethod
    def _grupo(nome: str) -> str:
        return f"ext_{nome}"

    def _anunciar(self, nome: str, item: dict) -> None:
        """Torna a extensão visível como grupo, mesmo antes de ser iniciada."""
        descricao = (item.get("descricao") or "").strip()
        quantidade = len(item.get("ferramentas") or [])
        sufixo = f" ({quantidade} ferramentas)" if quantidade else " (inicia ao ser ativada)"
        rotulo = f"extensão {nome}: {descricao[:110]}" if descricao else f"extensão {nome}"
        self.cat.grupos_extras[self._grupo(nome)] = rotulo + sufixo

    def _criar_cliente(self, nome: str, item: dict) -> _ClienteBase:
        if item.get("tipo") == "http":
            return ClienteMCPHttp(nome, item["url"], item.get("cabecalhos") or {}, self._transporte_http)
        return ClienteMCP(
            nome, item["comando"], item.get("args") or [], item.get("env") or {},
            self.amb.cfg.dir_logs / f"extensao_{nome}.log",
        )

    def _registrar_ferramentas(self, nome: str, ferramentas: list[dict]) -> int:
        grupo = self._grupo(nome)
        for existente in self.cat.nomes({grupo}):
            self.cat.remover(existente)
        for item in ferramentas:
            original = item.get("name", "")
            esquema = dict(item.get("inputSchema") or {})
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
        return len(ferramentas)

    # ------------------------------------------------------------------ conexão
    def _conectar(self, nome: str) -> int:
        """Inicia o servidor (ou a conexão), lista as ferramentas e guarda a lista em cache."""
        config = self._config()
        item = config.get(nome)
        if not item:
            raise ErroMCP("extensão não instalada")
        anterior = self._clientes.pop(nome, None)
        if anterior is not None:
            anterior.encerrar()
        cliente = self._criar_cliente(nome, item)
        try:
            cliente.iniciar()
            ferramentas = cliente.ferramentas()
        except Exception:
            cliente.encerrar()
            raise
        self._clientes[nome] = cliente
        enxutas = [
            {"name": f.get("name", ""), "description": (f.get("description") or "")[:400], "inputSchema": f.get("inputSchema") or {}}
            for f in ferramentas
        ]
        if item.get("ferramentas") != enxutas:
            item["ferramentas"] = enxutas
            config[nome] = item
            self.amb.cofre.guardar(self.CHAVE_COFRE, config)
        self._registrar_ferramentas(nome, enxutas)
        self._anunciar(nome, item)
        return len(enxutas)

    def garantir(self, nome: str) -> int:
        """Garante que as ferramentas da extensão estejam registradas; devolve quantas são."""
        registradas = len(self.cat.nomes({self._grupo(nome)}))
        return registradas if registradas else self._conectar(nome)

    def _chamador(self, extensao: str, ferramenta: str):
        def chamar(**argumentos) -> str:
            cliente = self._clientes.get(extensao)
            if cliente is None or not cliente.vivo():
                if extensao not in self._config():
                    return "ERRO: esta extensão foi removida."
                self._conectar(extensao)
                cliente = self._clientes[extensao]
            return cliente.chamar(ferramenta, argumentos)

        return chamar

    # ------------------------------------------------------------------ operações
    def registrar(self, nome: str, item: dict, conectar: bool = True) -> str:
        """Instala uma extensão. Com ``conectar=False`` ela fica só registrada e inicia quando for ativada."""
        nome = _nome_seguro(nome)
        if not nome:
            return "ERRO: informe um nome para a extensão."
        if item.get("tipo") == "http":
            if not str(item.get("url", "")).startswith(("http://", "https://")):
                return "ERRO: informe a URL do servidor (http ou https)."
        elif not item.get("comando"):
            return "ERRO: informe o comando que inicia o servidor, ou a URL de um servidor remoto."
        config = self._config()
        anterior = config.get(nome)
        config[nome] = {k: v for k, v in item.items() if k != "ferramentas"}
        em_uso = self._clientes.pop(nome, None)
        if em_uso is not None:
            em_uso.encerrar()  # a configuração mudou: a próxima chamada religa com os dados novos
        if not conectar:
            if anterior and anterior.get("ferramentas"):
                config[nome]["ferramentas"] = anterior["ferramentas"]  # mantém a lista conhecida de ferramentas
            self.amb.cofre.guardar(self.CHAVE_COFRE, config)
            self._anunciar(nome, config[nome])
            return f"Extensão '{nome}' registrada. Ela inicia quando o grupo '{self._grupo(nome)}' for ativado."
        self.amb.cofre.guardar(self.CHAVE_COFRE, config)
        try:
            quantidade = self._conectar(nome)
        except Exception as erro:
            if anterior is None:
                config.pop(nome, None)
            else:
                config[nome] = anterior
            self.amb.cofre.guardar(self.CHAVE_COFRE, config)
            self.cat.remover_grupo(self._grupo(nome))
            if anterior is not None:
                self._anunciar(nome, anterior)
            return (
                f"ERRO ao iniciar a extensão: {erro}. Confira comando, argumentos, URL e credenciais "
                f"(log em {self.amb.cfg.dir_logs / f'extensao_{nome}.log'})."
            )
        origem = item.get("url") or f"{item.get('comando')} {' '.join(item.get('args') or [])}"
        self.amb.registro.evento("extensao", f"Extensão instalada: {nome} ({quantidade} ferramentas)", origem)
        return (
            f"Extensão '{nome}' instalada com {quantidade} ferramentas. Para usá-las em uma tarefa, chame "
            f"ativar_ferramentas com o grupo '{self._grupo(nome)}'."
        )

    def instalar(self, nome: str, comando: str, args: list[str], env: dict[str, str]) -> str:
        return self.registrar(nome, {"tipo": "stdio", "comando": comando, "args": args, "env": env})

    def instalar_do_catalogo(self, nome: str, parametros: dict | None = None, conectar: bool = True) -> str:
        """Instala uma extensão do catálogo curado, buscando no cofre a credencial que ela exigir."""
        alvo = _nome_seguro(nome)
        entrada = next((e for e in carregar_catalogo() if _nome_seguro(e["nome"]) == alvo), None)
        if entrada is None:
            return f"ERRO: '{nome}' não está no catálogo. Use extensao_catalogo para ver as opções."
        trocas: dict[str, str] = {}
        credencial = entrada.get("credencial")
        sem_segredo = False
        if credencial:
            guardada = self.amb.cofre.obter_credencial(credencial["servico"])
            if guardada and guardada.get("senha"):
                trocas["segredo"] = str(guardada["senha"])
            elif credencial.get("opcional"):
                sem_segredo = True  # funciona sem a chave, com limites menores
            else:
                return (
                    f"FALTA CREDENCIAL: esta extensão precisa de '{credencial['servico']}' no cofre. "
                    f"{credencial.get('como_obter', '')} Depois guarde com credencial_salvar "
                    f"(servico='{credencial['servico']}', senha=o token) e instale de novo."
                ).strip()
        for chave, explicacao in (entrada.get("parametros") or {}).items():
            valor = (parametros or {}).get(chave)
            if not valor:
                return f"FALTA PARÂMETRO '{chave}': {explicacao} Informe em parametros, por exemplo {{\"{chave}\": \"valor\"}}."
            trocas[chave] = str(valor)
        if entrada.get("tipo", "stdio") == "stdio" and not shutil.which(entrada["comando"]):
            dica = {"npx": "instale o Node.js", "uvx": "instale o uv (pip install uv)", "docker": "instale o Docker"}.get(
                entrada["comando"], "instale esse programa"
            )
            return f"ERRO: o programa '{entrada['comando']}' não está instalado nesta máquina ({dica})."
        argumentos = list(entrada.get("args") or [])
        if "{chromium}" in argumentos:
            navegador = caminho_do_chromium(self.amb.cfg.navegador_executavel)
            if navegador:
                trocas["chromium"] = navegador
            else:  # sem navegador localizado: deixa o servidor procurar o Chrome do sistema
                posicao = argumentos.index("{chromium}")
                del argumentos[posicao - 1 : posicao + 1]
        def sem_marcador(origem: dict) -> dict:
            """Sem a credencial opcional, as variáveis e cabeçalhos que dependeriam dela são omitidos."""
            return {k: v for k, v in origem.items() if not (sem_segredo and "{segredo}" in str(v))}

        item = {
            "tipo": entrada.get("tipo", "stdio"),
            "descricao": entrada.get("descricao", ""),
            "comando": entrada.get("comando", ""),
            "args": _substituir(argumentos, trocas),
            "env": _substituir(sem_marcador(entrada.get("env") or {}), trocas),
            "url": _substituir(entrada.get("url", ""), trocas),
            "cabecalhos": _substituir(sem_marcador(entrada.get("cabecalhos") or {}), trocas),
        }
        return self.registrar(entrada["nome"], item, conectar=conectar)

    def registrar_por_credencial(self, servico: str) -> list[str]:
        """Quando uma credencial entra no cofre, deixa prontas as extensões do catálogo que dependem dela."""
        servico = servico.strip().lower()
        prontas = []
        for entrada in carregar_catalogo():
            credencial = entrada.get("credencial") or {}
            if credencial.get("servico") != servico or entrada.get("parametros"):
                continue
            resposta = self.instalar_do_catalogo(entrada["nome"], conectar=False)
            if not resposta.startswith(("ERRO", "FALTA")):
                prontas.append(self._grupo(_nome_seguro(entrada["nome"])))
        if prontas:
            self.amb.registro.evento(
                "extensao", f"Extensões liberadas pela credencial {servico}: {', '.join(prontas)}"
            )
        return prontas

    def remover(self, nome: str) -> str:
        nome = _nome_seguro(nome)
        config = self._config()
        if nome not in config:
            return "ERRO: extensão não encontrada."
        cliente = self._clientes.pop(nome, None)
        if cliente is not None:
            cliente.encerrar()
        self.cat.remover_grupo(self._grupo(nome))
        del config[nome]
        self.amb.cofre.guardar(self.CHAVE_COFRE, config)
        self.amb.registro.evento("extensao", f"Extensão removida: {nome}")
        return f"Extensão '{nome}' removida."

    def instalada(self, nome: str) -> bool:
        return _nome_seguro(nome) in self._config()

    def listar(self) -> list[dict]:
        itens = []
        for nome, item in sorted(self._config().items()):
            cliente = self._clientes.get(nome)
            origem = item.get("url") or f"{item.get('comando', '')} {' '.join(item.get('args') or [])}".strip()
            itens.append(
                {
                    "nome": nome,
                    "tipo": item.get("tipo", "stdio"),
                    "descricao": item.get("descricao", ""),
                    "comando": self.amb.registro.mascarar(origem),
                    "ativa": bool(cliente and cliente.vivo()),
                    "ferramentas": len(item.get("ferramentas") or []),
                }
            )
        return itens

    def carregar_todas(self) -> None:
        """Na partida, registra as extensões sem iniciar nenhuma: cada uma liga no primeiro uso."""
        for nome, item in self._config().items():
            try:
                if item.get("ferramentas"):
                    self._registrar_ferramentas(nome, item["ferramentas"])
                self._anunciar(nome, item)
            except Exception as erro:
                self.amb.registro.erro(f"Extensão {nome} não pôde ser registrada", str(erro))

    def encerrar_todas(self) -> None:
        for nome in list(self._clientes):
            cliente = self._clientes.pop(nome)
            try:
                cliente.encerrar()
            except Exception:
                pass


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
        "extensao_catalogo",
        "Mostra as extensões recomendadas e já conferidas para este agente (GitHub, Cloudflare, Notion, bancos de "
        "dados, documentação de bibliotecas, depuração de sites, redes sociais e outras), com o que cada uma exige.",
        _grupo="expansao",
        area=P("string", "Filtra por área: programacao, gestao, infraestrutura, web, seguranca, midia, social, dados.", obrigatorio=False),
    )
    def extensao_catalogo(area: str = "") -> str:
        linhas = []
        for e in carregar_catalogo():
            if area and area.strip().lower() not in e.get("area", ""):
                continue
            exigencias = []
            if e.get("credencial"):
                tem = bool(amb.cofre.obter_credencial(e["credencial"]["servico"]))
                tipo = "credencial opcional" if e["credencial"].get("opcional") else "credencial"
                exigencias.append(f"{tipo} '{e['credencial']['servico']}' no cofre ({'já existe' if tem else 'falta'})")
            if e.get("parametros"):
                exigencias.append("parâmetros: " + ", ".join(e["parametros"]))
            if e.get("tipo", "stdio") == "stdio":
                exigencias.append(f"programa {e['comando']}" + ("" if shutil.which(e["comando"]) else " (não instalado)"))
            situacao = "INSTALADA" if gerenciador.instalada(e["nome"]) else "disponível"
            linhas.append(f"- {e['nome']} [{e.get('area', '')}] {situacao}: {e.get('descricao', '')} Exige: {'; '.join(exigencias) or 'nada'}.")
        if not linhas:
            return "Nenhuma extensão do catálogo nessa área. Use extensao_buscar para procurar no registro público."
        return "\n".join(linhas) + "\nPara instalar: extensao_instalar com o nome. Fora do catálogo: extensao_buscar."

    @cat.ferramenta(
        "extensao_buscar",
        "Procura extensões (servidores MCP) no registro público da comunidade. O registro não filtra qualidade: "
        "prefira o catálogo (extensao_catalogo) e, fora dele, servidores oficiais do próprio fornecedor.",
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
        "Instala uma extensão. Do catálogo: informe só o nome (e parametros, se o catálogo pedir). Fora do catálogo: "
        "informe comando e argumentos de um servidor local (stdio), ou url e cabecalhos de um servidor remoto (HTTP).",
        _grupo="expansao",
        nome=P("string", "Nome da extensão (do catálogo, ou um nome curto novo)."),
        comando=P("string", "Servidor local: executável que o inicia (npx, uvx, python, node, docker).", obrigatorio=False),
        argumentos=P("string", "Servidor local: lista JSON de argumentos, por exemplo [\"-y\", \"pacote\"].", obrigatorio=False),
        ambiente=P("string", "Servidor local: objeto JSON de variáveis de ambiente (chaves de API).", obrigatorio=False),
        url=P("string", "Servidor remoto: endereço do endpoint MCP.", obrigatorio=False),
        cabecalhos=P("string", "Servidor remoto: objeto JSON de cabeçalhos, por exemplo {\"Authorization\": \"Bearer TOKEN\"}.", obrigatorio=False),
        parametros=P("string", "Catálogo: objeto JSON com os parâmetros pedidos pela extensão.", obrigatorio=False),
    )
    def extensao_instalar(
        nome: str, comando: str = "", argumentos: str = "", ambiente: str = "", url: str = "", cabecalhos: str = "", parametros: str = ""
    ) -> str:
        def ler_json(texto: str, tipo: type, padrao: object) -> object:
            if not texto.strip():
                return padrao
            valor = json.loads(texto)
            if not isinstance(valor, tipo):
                raise ValueError
            return valor

        try:
            args = ler_json(argumentos, list, [])
            env = ler_json(ambiente, dict, {})
            cab = ler_json(cabecalhos, dict, {})
            par = ler_json(parametros, dict, {})
        except ValueError:
            return "ERRO: 'argumentos' deve ser uma lista JSON; 'ambiente', 'cabecalhos' e 'parametros' devem ser objetos JSON."
        if url.strip():
            return gerenciador.registrar(nome, {"tipo": "http", "url": url.strip(), "cabecalhos": {str(k): str(v) for k, v in cab.items()}})
        if comando.strip():
            return gerenciador.instalar(nome, comando.strip(), [str(a) for a in args], {str(k): str(v) for k, v in env.items()})
        return gerenciador.instalar_do_catalogo(nome, par)

    @cat.ferramenta("extensao_listar", "Lista as extensões instaladas.", _grupo="expansao")
    def extensao_listar() -> str:
        itens = gerenciador.listar()
        if not itens:
            return "Nenhuma extensão instalada. Veja as recomendadas com extensao_catalogo."
        return "\n".join(
            f"- {e['nome']} (grupo ext_{e['nome']}, {e['tipo']}, "
            f"{str(e['ferramentas']) + ' ferramentas' if e['ferramentas'] else 'ainda não iniciada'}): {e['descricao'] or e['comando']}"
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

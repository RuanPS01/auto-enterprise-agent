"""Cliente do modelo de linguagem local.

Fala com o Ollama pela API nativa (padrão) ou com qualquer servidor local que
exponha a API compatível com OpenAI (llama.cpp, LM Studio, vLLM, LocalAI).

As mensagens circulam pelo agente em um formato neutro:

* ``{"role": "system" | "user", "content": str}``
* ``{"role": "assistant", "content": str, "chamadas": [{"id", "nome", "argumentos"}]}``
* ``{"role": "tool", "id": str, "nome": str, "content": str}``

Nem todo modelo local sabe chamar ferramentas de forma nativa. Por isso existem
dois modos: ``nativo`` (o servidor recebe a lista de ferramentas) e ``json`` (as
ferramentas são descritas no prompt e o modelo responde com um objeto JSON). No
modo ``auto`` o cliente começa pelo nativo e troca sozinho se o modelo não der
suporte.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

import httpx

from .config import Config, url_e_local


class ErroLLM(Exception):
    """Erro ao conversar com o modelo."""


class LLMIndisponivel(ErroLLM):
    """O servidor do modelo não respondeu (desligado, carregando ou travado)."""


class _SemSuporteFerramentas(Exception):
    pass


@dataclass
class Chamada:
    id: str
    nome: str
    argumentos: dict


@dataclass
class Resposta:
    texto: str = ""
    chamadas: list[Chamada] = field(default_factory=list)
    pensamento: str = ""


_RE_PENSAMENTO = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
_RE_BLOCO_CHAMADA = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL | re.IGNORECASE)
_RE_CERCA = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def separar_pensamento(texto: str) -> tuple[str, str]:
    """Remove blocos ``<think>`` do texto e os devolve em separado."""
    if not texto:
        return "", ""
    pensamentos = [p.strip() for p in _RE_PENSAMENTO.findall(texto)]
    limpo = _RE_PENSAMENTO.sub("", texto)
    if "<think>" in limpo.lower():  # bloco aberto e nunca fechado
        inicio = limpo.lower().index("<think>")
        pensamentos.append(limpo[inicio + 7 :].strip())
        limpo = limpo[:inicio]
    return limpo.strip(), "\n".join(p for p in pensamentos if p)


def _objetos_json(texto: str) -> list[object]:
    """Encontra objetos JSON balanceados dentro de um texto livre."""
    achados: list[object] = []
    decodificador = json.JSONDecoder()
    posicao = 0
    while True:
        inicio = texto.find("{", posicao)
        if inicio < 0:
            break
        try:
            objeto, fim = decodificador.raw_decode(texto[inicio:])
        except json.JSONDecodeError:
            posicao = inicio + 1
            continue
        achados.append(objeto)
        posicao = inicio + fim
    return achados


def _interpretar_chamada(objeto: object, nomes_validos: set[str]) -> Chamada | None:
    if not isinstance(objeto, dict):
        return None
    if isinstance(objeto.get("function"), dict):
        objeto = objeto["function"]
    nome = objeto.get("ferramenta") or objeto.get("name") or objeto.get("tool") or objeto.get("nome")
    if not isinstance(nome, str) or nome not in nomes_validos:
        return None
    argumentos = None
    for chave in ("argumentos", "arguments", "args", "parameters", "parametros"):
        if chave in objeto:
            argumentos = objeto[chave]
            break
    if isinstance(argumentos, str):
        try:
            argumentos = json.loads(argumentos)
        except json.JSONDecodeError:
            argumentos = {}
    if not isinstance(argumentos, dict):
        argumentos = {}
    return Chamada(id=f"c_{uuid.uuid4().hex[:8]}", nome=nome, argumentos=argumentos)


def extrair_chamadas_do_texto(texto: str, nomes_validos: set[str]) -> list[Chamada]:
    """Recupera chamadas de ferramenta escritas pelo modelo como texto.

    Modelos pequenos frequentemente devolvem a chamada no corpo da resposta, em
    vez de usar o campo próprio. Aqui aceitamos os formatos mais comuns.
    """
    if not texto or not nomes_validos:
        return []
    candidatos: list[str] = _RE_BLOCO_CHAMADA.findall(texto) + _RE_CERCA.findall(texto) + [texto]
    for trecho in candidatos:
        chamadas = []
        for objeto in _objetos_json(trecho):
            itens = objeto.get("chamadas") if isinstance(objeto, dict) and "chamadas" in objeto else [objeto]
            for item in itens if isinstance(itens, list) else [itens]:
                chamada = _interpretar_chamada(item, nomes_validos)
                if chamada:
                    chamadas.append(chamada)
        if chamadas:
            return chamadas
    return []


def estimar_tokens(mensagens: list[dict]) -> int:
    """Estimativa conservadora (texto em português rende cerca de 3 caracteres por token)."""
    total = 0
    for mensagem in mensagens:
        total += len(mensagem.get("content") or "") + 12
        for chamada in mensagem.get("chamadas") or []:
            total += len(json.dumps(chamada.get("argumentos", {}), ensure_ascii=False)) + len(chamada["nome"]) + 12
    return int(total / 3)


def _assinatura(ferramenta: dict) -> str:
    propriedades = ferramenta["parametros"].get("properties", {})
    obrigatorios = set(ferramenta["parametros"].get("required", []))
    partes = []
    for nome, esquema in propriedades.items():
        marca = "" if nome in obrigatorios else "?"
        partes.append(f"{nome}{marca}: {esquema.get('type', 'string')}")
    return f"- {ferramenta['nome']}({', '.join(partes)}): {ferramenta['descricao']}"


def instrucoes_modo_json(ferramentas: list[dict]) -> str:
    linhas = "\n".join(_assinatura(f) for f in ferramentas)
    return (
        "FERRAMENTAS DISPONÍVEIS (parâmetros com ? são opcionais):\n"
        f"{linhas}\n\n"
        "Para agir, responda SOMENTE com um objeto JSON, sem nenhum texto fora dele, neste formato:\n"
        '{"pensamento": "raciocínio curto", "ferramenta": "nome_da_ferramenta", "argumentos": {"parametro": "valor"}}\n'
        "Use uma ferramenta por resposta."
    )


class ClienteLLM:
    def __init__(self, cfg: Config, transporte: httpx.BaseTransport | None = None):
        self.cfg = cfg
        if not cfg.permitir_llm_remoto and not url_e_local(cfg.url_llm):
            raise ErroLLM(
                f"O endereço do modelo ({cfg.url_llm}) não é local. Este agente usa somente modelos que rodam "
                "na sua máquina ou na sua rede privada. Se isso for intencional, defina permitir_llm_remoto = true."
            )
        if not cfg.permitir_llm_remoto and "cloud" in cfg.modelo.lower().split(":")[-1]:
            raise ErroLLM(
                f"O modelo '{cfg.modelo}' é uma variante de nuvem: o processamento aconteceria fora da sua máquina. "
                "Escolha um modelo que rode localmente (por exemplo qwen3:8b)."
            )
        self._usar_json = cfg.modo_ferramentas == "json"
        self._http = httpx.Client(timeout=httpx.Timeout(cfg.tempo_limite_llm, connect=10.0), transport=transporte)

    # ------------------------------------------------------------------ infraestrutura
    @property
    def modo_atual(self) -> str:
        return "json" if self._usar_json else "nativo"

    def _base_openai(self) -> str:
        base = self.cfg.url_llm
        return base if base.endswith("/v1") else base + "/v1"

    def _postar(self, url: str, corpo: dict, tempo: float | None = None) -> dict:
        try:
            resposta = self._http.post(url, json=corpo, timeout=tempo) if tempo else self._http.post(url, json=corpo)
        except (httpx.ConnectError, httpx.ConnectTimeout) as erro:
            raise LLMIndisponivel(f"Sem conexão com o servidor do modelo em {self.cfg.url_llm}: {erro}") from erro
        except httpx.TimeoutException as erro:
            raise LLMIndisponivel(f"O modelo demorou mais que {self.cfg.tempo_limite_llm}s para responder.") from erro
        except httpx.HTTPError as erro:
            raise LLMIndisponivel(f"Falha de comunicação com o modelo: {erro}") from erro
        if resposta.status_code >= 400:
            texto = resposta.text[:500]
            minusculo = texto.lower()
            if "does not support tools" in minusculo or "tool use is not supported" in minusculo:
                raise _SemSuporteFerramentas(texto)
            if resposta.status_code == 404 and "model" in minusculo:
                raise ErroLLM(
                    f"O modelo '{self.cfg.modelo}' não está instalado no servidor local. "
                    f"Instale com: ollama pull {self.cfg.modelo}"
                )
            if resposta.status_code >= 500:
                raise LLMIndisponivel(f"O servidor do modelo respondeu HTTP {resposta.status_code}: {texto}")
            raise ErroLLM(f"O servidor do modelo respondeu HTTP {resposta.status_code}: {texto}")
        try:
            return resposta.json()
        except json.JSONDecodeError as erro:
            raise ErroLLM(f"Resposta inválida do servidor do modelo: {resposta.text[:200]}") from erro

    # ------------------------------------------------------------------ diagnóstico
    def modelos_instalados(self) -> list[str]:
        try:
            if self.cfg.provedor == "ollama":
                dados = self._http.get(f"{self.cfg.url_llm}/api/tags", timeout=10).json()
                return [m.get("name", "") for m in dados.get("models", [])]
            dados = self._http.get(f"{self._base_openai()}/models", timeout=10).json()
            return [m.get("id", "") for m in dados.get("data", [])]
        except (httpx.HTTPError, json.JSONDecodeError) as erro:
            raise LLMIndisponivel(f"Sem conexão com o servidor do modelo em {self.cfg.url_llm}: {erro}") from erro

    def modelo_disponivel(self) -> bool:
        instalados = self.modelos_instalados()
        alvo = self.cfg.modelo
        return any(nome == alvo or nome == f"{alvo}:latest" or nome.split(":")[0] == alvo for nome in instalados)

    def baixar_modelo(self) -> None:
        """Pede ao Ollama que baixe o modelo configurado (pode levar bastante tempo)."""
        if self.cfg.provedor != "ollama":
            raise ErroLLM("O download automático de modelos só existe para o provedor ollama.")
        self._postar(f"{self.cfg.url_llm}/api/pull", {"model": self.cfg.modelo, "stream": False}, tempo=6 * 3600)

    # ------------------------------------------------------------------ conversa
    def conversar(
        self,
        mensagens: list[dict],
        ferramentas: list[dict] | None = None,
        temperatura: float | None = None,
    ) -> Resposta:
        ferramentas = ferramentas or []
        nomes = {f["nome"] for f in ferramentas}
        if ferramentas and self._usar_json:
            return self._conversar_json(mensagens, ferramentas, temperatura)
        try:
            resposta = self._conversar_nativo(mensagens, ferramentas, temperatura)
        except _SemSuporteFerramentas as erro:
            if self.cfg.modo_ferramentas == "nativo":
                raise ErroLLM(
                    f"O modelo '{self.cfg.modelo}' não aceita ferramentas nativas. "
                    'Use modo_ferramentas = "auto" ou "json".'
                ) from erro
            self._usar_json = True
            return self._conversar_json(mensagens, ferramentas, temperatura)
        if ferramentas and not resposta.chamadas and resposta.texto:
            resgatadas = extrair_chamadas_do_texto(resposta.texto, nomes)
            if resgatadas:
                resposta.chamadas = resgatadas
                resposta.texto = ""
        return resposta

    def texto_simples(self, sistema: str, pedido: str, temperatura: float | None = None) -> str:
        """Atalho para uma pergunta sem ferramentas."""
        resposta = self.conversar(
            [{"role": "system", "content": sistema}, {"role": "user", "content": pedido}],
            temperatura=temperatura,
        )
        return resposta.texto.strip()

    # ------------------------------------------------------------------ modo nativo
    def _conversar_nativo(self, mensagens: list[dict], ferramentas: list[dict], temperatura: float | None) -> Resposta:
        if self.cfg.provedor == "ollama":
            return self._ollama(self._para_ollama(mensagens), ferramentas, temperatura, formato_json=False)
        return self._openai(self._para_openai(mensagens), ferramentas, temperatura)

    def _opcoes_ollama(self, temperatura: float | None) -> dict:
        return {
            "num_ctx": self.cfg.contexto_tokens,
            "temperature": self.cfg.temperatura if temperatura is None else temperatura,
            "num_predict": min(8192, max(1024, self.cfg.contexto_tokens // 2)),
        }

    def _ollama(
        self, mensagens: list[dict], ferramentas: list[dict], temperatura: float | None, formato_json: bool
    ) -> Resposta:
        corpo: dict = {
            "model": self.cfg.modelo,
            "messages": mensagens,
            "stream": False,
            "keep_alive": "30m",
            "options": self._opcoes_ollama(temperatura),
        }
        if ferramentas:
            corpo["tools"] = [
                {
                    "type": "function",
                    "function": {"name": f["nome"], "description": f["descricao"], "parameters": f["parametros"]},
                }
                for f in ferramentas
            ]
        if formato_json:
            corpo["format"] = "json"
        dados = self._postar(f"{self.cfg.url_llm}/api/chat", corpo)
        mensagem = dados.get("message") or {}
        texto, pensamento = separar_pensamento(mensagem.get("content") or "")
        pensamento = (mensagem.get("thinking") or "").strip() or pensamento
        chamadas = []
        for item in mensagem.get("tool_calls") or []:
            funcao = item.get("function") or {}
            argumentos = funcao.get("arguments")
            if isinstance(argumentos, str):
                try:
                    argumentos = json.loads(argumentos)
                except json.JSONDecodeError:
                    argumentos = {}
            chamadas.append(
                Chamada(
                    id=str(item.get("id") or f"c_{uuid.uuid4().hex[:8]}"),
                    nome=str(funcao.get("name") or ""),
                    argumentos=argumentos if isinstance(argumentos, dict) else {},
                )
            )
        return Resposta(texto=texto, chamadas=chamadas, pensamento=pensamento)

    def _openai(self, mensagens: list[dict], ferramentas: list[dict], temperatura: float | None) -> Resposta:
        corpo: dict = {
            "model": self.cfg.modelo,
            "messages": mensagens,
            "stream": False,
            "temperature": self.cfg.temperatura if temperatura is None else temperatura,
            "max_tokens": min(8192, max(1024, self.cfg.contexto_tokens // 2)),
        }
        if ferramentas:
            corpo["tools"] = [
                {
                    "type": "function",
                    "function": {"name": f["nome"], "description": f["descricao"], "parameters": f["parametros"]},
                }
                for f in ferramentas
            ]
        dados = self._postar(f"{self._base_openai()}/chat/completions", corpo)
        escolhas = dados.get("choices") or [{}]
        mensagem = escolhas[0].get("message") or {}
        texto, pensamento = separar_pensamento(mensagem.get("content") or "")
        pensamento = (mensagem.get("reasoning_content") or mensagem.get("reasoning") or "").strip() or pensamento
        chamadas = []
        for item in mensagem.get("tool_calls") or []:
            funcao = item.get("function") or {}
            argumentos = funcao.get("arguments")
            if isinstance(argumentos, str):
                try:
                    argumentos = json.loads(argumentos or "{}")
                except json.JSONDecodeError:
                    argumentos = {}
            chamadas.append(
                Chamada(
                    id=str(item.get("id") or f"c_{uuid.uuid4().hex[:8]}"),
                    nome=str(funcao.get("name") or ""),
                    argumentos=argumentos if isinstance(argumentos, dict) else {},
                )
            )
        return Resposta(texto=texto, chamadas=chamadas, pensamento=pensamento)

    @staticmethod
    def _para_ollama(mensagens: list[dict]) -> list[dict]:
        saida = []
        for m in mensagens:
            if m["role"] == "assistant" and m.get("chamadas"):
                saida.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or "",
                        "tool_calls": [
                            {"function": {"name": c["nome"], "arguments": c["argumentos"]}} for c in m["chamadas"]
                        ],
                    }
                )
            elif m["role"] == "tool":
                saida.append({"role": "tool", "content": m.get("content") or "", "tool_name": m.get("nome", "")})
            else:
                saida.append({"role": m["role"], "content": m.get("content") or ""})
        return saida

    @staticmethod
    def _para_openai(mensagens: list[dict]) -> list[dict]:
        saida = []
        for m in mensagens:
            if m["role"] == "assistant" and m.get("chamadas"):
                saida.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {
                                    "name": c["nome"],
                                    "arguments": json.dumps(c["argumentos"], ensure_ascii=False),
                                },
                            }
                            for c in m["chamadas"]
                        ],
                    }
                )
            elif m["role"] == "tool":
                saida.append({"role": "tool", "tool_call_id": m.get("id", ""), "content": m.get("content") or ""})
            else:
                saida.append({"role": m["role"], "content": m.get("content") or ""})
        return saida

    # ------------------------------------------------------------------ modo json
    @staticmethod
    def _para_modo_json(mensagens: list[dict], ferramentas: list[dict]) -> list[dict]:
        saida: list[dict] = []
        instrucoes = instrucoes_modo_json(ferramentas)
        for m in mensagens:
            if m["role"] == "system":
                saida.append({"role": "system", "content": f"{m.get('content') or ''}\n\n{instrucoes}"})
                instrucoes = ""
            elif m["role"] == "assistant" and m.get("chamadas"):
                for c in m["chamadas"]:
                    objeto = {"pensamento": m.get("content") or "", "ferramenta": c["nome"], "argumentos": c["argumentos"]}
                    saida.append({"role": "assistant", "content": json.dumps(objeto, ensure_ascii=False)})
            elif m["role"] == "tool":
                saida.append(
                    {"role": "user", "content": f"Resultado da ferramenta {m.get('nome', '')}:\n{m.get('content') or ''}"}
                )
            else:
                saida.append({"role": m["role"], "content": m.get("content") or ""})
        if instrucoes:
            saida.insert(0, {"role": "system", "content": instrucoes})
        # Alguns servidores recusam duas mensagens seguidas do mesmo papel.
        unidas: list[dict] = []
        for m in saida:
            if unidas and unidas[-1]["role"] == m["role"] and m["role"] in ("user", "assistant"):
                unidas[-1] = {"role": m["role"], "content": unidas[-1]["content"] + "\n\n" + m["content"]}
            else:
                unidas.append(m)
        return unidas

    def _conversar_json(self, mensagens: list[dict], ferramentas: list[dict], temperatura: float | None) -> Resposta:
        convertidas = self._para_modo_json(mensagens, ferramentas)
        if self.cfg.provedor == "ollama":
            bruta = self._ollama(convertidas, [], temperatura, formato_json=True)
        else:
            bruta = self._openai(convertidas, [], temperatura)
        nomes = {f["nome"] for f in ferramentas}
        chamadas = extrair_chamadas_do_texto(bruta.texto, nomes)
        if chamadas:
            pensamento = bruta.pensamento
            for objeto in _objetos_json(bruta.texto):
                if isinstance(objeto, dict) and isinstance(objeto.get("pensamento"), str):
                    pensamento = objeto["pensamento"] or pensamento
                    break
            return Resposta(texto="", chamadas=chamadas[:1], pensamento=pensamento)
        return Resposta(texto=bruta.texto, chamadas=[], pensamento=bruta.pensamento)

import json

import httpx
import pytest

from empresa_auto.config import carregar_config, url_e_local
from empresa_auto.llm import (
    ClienteLLM,
    ErroLLM,
    LLMIndisponivel,
    estimar_tokens,
    extrair_chamadas_do_texto,
    separar_pensamento,
)

FERRAMENTAS = [
    {
        "nome": "pesquisar_web",
        "descricao": "Pesquisa na internet.",
        "parametros": {"type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"]},
    }
]
MENSAGENS = [{"role": "system", "content": "regras"}, {"role": "user", "content": "pesquise algo"}]


def cliente(tmp_path, manipulador, **opcoes) -> ClienteLLM:
    cfg = carregar_config(tmp_path, **opcoes)
    return ClienteLLM(cfg, transporte=httpx.MockTransport(manipulador))


def test_separa_pensamento_do_texto():
    assert separar_pensamento("<think>vou pesquisar</think>Resposta final") == ("Resposta final", "vou pesquisar")
    assert separar_pensamento("texto <think>nunca fechou") == ("texto", "nunca fechou")
    assert separar_pensamento("") == ("", "")


@pytest.mark.parametrize(
    "texto",
    [
        '{"name": "pesquisar_web", "arguments": {"consulta": "cafeterias"}}',
        '<tool_call>{"name": "pesquisar_web", "arguments": {"consulta": "cafeterias"}}</tool_call>',
        'Vou pesquisar.\n```json\n{"ferramenta": "pesquisar_web", "argumentos": {"consulta": "cafeterias"}}\n```',
        '{"function": {"name": "pesquisar_web", "arguments": "{\\"consulta\\": \\"cafeterias\\"}"}}',
        '{"pensamento": "ok", "tool": "pesquisar_web", "args": {"consulta": "cafeterias"}}',
    ],
)
def test_resgata_chamadas_escritas_como_texto(texto):
    chamadas = extrair_chamadas_do_texto(texto, {"pesquisar_web"})
    assert len(chamadas) == 1
    assert chamadas[0].nome == "pesquisar_web" and chamadas[0].argumentos == {"consulta": "cafeterias"}


def test_nao_resgata_ferramenta_desconhecida_nem_json_comum():
    assert extrair_chamadas_do_texto('{"name": "apagar_tudo", "arguments": {}}', {"pesquisar_web"}) == []
    assert extrair_chamadas_do_texto('O resultado foi {"total": 3}.', {"pesquisar_web"}) == []


def test_ollama_nativo_envia_ferramentas_e_le_chamadas(tmp_path):
    recebido = {}

    def manipulador(pedido: httpx.Request) -> httpx.Response:
        recebido["url"] = str(pedido.url)
        recebido["corpo"] = json.loads(pedido.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "thinking": "preciso pesquisar",
                    "tool_calls": [{"function": {"name": "pesquisar_web", "arguments": {"consulta": "mercado pet"}}}],
                }
            },
        )

    llm = cliente(tmp_path, manipulador, modelo="qwen3:8b", contexto_tokens=8192)
    historico = MENSAGENS + [
        {"role": "assistant", "content": "", "chamadas": [{"id": "c1", "nome": "pesquisar_web", "argumentos": {"consulta": "a"}}]},
        {"role": "tool", "id": "c1", "nome": "pesquisar_web", "content": "resultado"},
    ]
    resposta = llm.conversar(historico, FERRAMENTAS)
    assert recebido["url"] == "http://127.0.0.1:11434/api/chat"
    corpo = recebido["corpo"]
    assert corpo["model"] == "qwen3:8b" and corpo["stream"] is False and corpo["options"]["num_ctx"] == 8192
    assert corpo["tools"][0]["function"]["name"] == "pesquisar_web"
    assert corpo["messages"][2]["tool_calls"][0]["function"]["arguments"] == {"consulta": "a"}
    assert corpo["messages"][3] == {"role": "tool", "content": "resultado", "tool_name": "pesquisar_web"}
    assert resposta.chamadas[0].nome == "pesquisar_web" and resposta.chamadas[0].argumentos == {"consulta": "mercado pet"}
    assert resposta.pensamento == "preciso pesquisar"


def test_modelo_sem_ferramentas_nativas_cai_para_modo_json(tmp_path):
    corpos = []

    def manipulador(pedido: httpx.Request) -> httpx.Response:
        corpo = json.loads(pedido.content)
        corpos.append(corpo)
        if "tools" in corpo:
            return httpx.Response(400, json={"error": "registry.ollama.ai/library/modelo does not support tools"})
        conteudo = json.dumps({"pensamento": "vou pesquisar", "ferramenta": "pesquisar_web", "argumentos": {"consulta": "x"}})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": conteudo}})

    llm = cliente(tmp_path, manipulador)
    resposta = llm.conversar(MENSAGENS, FERRAMENTAS)
    assert llm.modo_atual == "json"
    assert resposta.chamadas[0].argumentos == {"consulta": "x"} and resposta.pensamento == "vou pesquisar"
    assert corpos[1]["format"] == "json" and "tools" not in corpos[1]
    assert "pesquisar_web(consulta: string)" in corpos[1]["messages"][0]["content"]
    llm.conversar(MENSAGENS, FERRAMENTAS)
    assert "tools" not in corpos[2]  # não tenta o modo nativo de novo


def test_provedor_compativel_com_openai(tmp_path):
    recebido = {}

    def manipulador(pedido: httpx.Request) -> httpx.Response:
        recebido["url"] = str(pedido.url)
        recebido["corpo"] = json.loads(pedido.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {"id": "call_9", "type": "function", "function": {"name": "pesquisar_web", "arguments": '{"consulta": "y"}'}}
                            ],
                        }
                    }
                ]
            },
        )

    llm = cliente(tmp_path, manipulador, provedor="openai", url_llm="http://localhost:8080")
    resposta = llm.conversar(MENSAGENS, FERRAMENTAS)
    assert recebido["url"] == "http://localhost:8080/v1/chat/completions"
    assert recebido["corpo"]["tools"][0]["function"]["parameters"]["required"] == ["consulta"]
    assert (resposta.chamadas[0].id, resposta.chamadas[0].argumentos) == ("call_9", {"consulta": "y"})


def test_erros_de_conexao_e_de_modelo(tmp_path):
    def sem_conexao(pedido: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusado")

    with pytest.raises(LLMIndisponivel):
        cliente(tmp_path, sem_conexao).conversar(MENSAGENS)

    def sem_modelo(pedido: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'qwen3:8b' not found"})

    with pytest.raises(ErroLLM, match="ollama pull"):
        cliente(tmp_path, sem_modelo).conversar(MENSAGENS)


def test_recusa_llm_fora_da_rede_local(tmp_path):
    assert url_e_local("http://127.0.0.1:11434") and url_e_local("http://192.168.1.20:11434") and url_e_local("http://localhost:1234")
    assert not url_e_local("https://8.8.8.8/v1")
    with pytest.raises(ErroLLM, match="não é local"):
        ClienteLLM(carregar_config(tmp_path, url_llm="https://8.8.8.8"))
    ClienteLLM(carregar_config(tmp_path, url_llm="https://8.8.8.8", permitir_llm_remoto=True))


def test_estimativa_de_tokens_cresce_com_o_conteudo():
    assert estimar_tokens(MENSAGENS) < estimar_tokens(MENSAGENS + [{"role": "user", "content": "x" * 3000}])

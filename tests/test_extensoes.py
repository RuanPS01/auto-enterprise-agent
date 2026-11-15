import json
import sys
from pathlib import Path

import httpx
import pytest

from conftest import LLMRoteirizado, chamar
from empresa_auto.agente import Agente
from empresa_auto.ferramentas import extensoes as modulo
from empresa_auto.ferramentas.extensoes import ClienteMCPHttp, ErroMCP

SERVIDOR = str(Path(__file__).parent / "apoio" / "servidor_mcp_falso.py")


def instalar(agente, nome="Calculadora", ambiente="{}"):
    return agente.catalogo.executar(
        "extensao_instalar",
        {"nome": nome, "comando": sys.executable, "argumentos": json.dumps([SERVIDOR]), "ambiente": ambiente},
    )


# ---------------------------------------------------------------------- servidor local (stdio)
def test_instala_servidor_mcp_e_usa_as_ferramentas(agente):
    saida = instalar(agente, ambiente='{"CHAVE_API": "chave-secreta-xyz-123"}')
    assert "instalada com 3 ferramentas" in saida and "ext_calculadora" in saida
    cat = agente.catalogo
    assert cat.grupos()["ext_calculadora"] == "extensão calculadora (3 ferramentas)"
    assert cat.executar("ext_calculadora_somar", {"a": "2", "b": 3.5}) == "5.5"  # tipos consertados pelo esquema
    assert cat.executar("ext_calculadora_ler_segredo", {}) == "chave-secreta-xyz-123"
    assert cat.executar("ext_calculadora_falhar", {}) == "ERRO da extensão: deu errado"
    assert "calculadora (grupo ext_calculadora, stdio, 3 ferramentas)" in cat.executar("extensao_listar", {})

    # a chave de API fica cifrada no cofre e é mascarada nos registros
    assert b"chave-secreta-xyz-123" not in (agente.cfg.dir_dados / "cofre.bin").read_bytes()
    agente.registro.evento("resultado", "saída com chave-secreta-xyz-123")
    assert "chave-secreta-xyz-123" not in agente.banco.eventos_recentes(1)[0]["titulo"]


def test_extensao_religa_sozinha_e_pode_ser_removida(agente):
    instalar(agente)
    agente.amb.extensoes._clientes["calculadora"].encerrar()  # simula a queda do servidor
    assert agente.catalogo.executar("ext_calculadora_somar", {"a": 1, "b": 1}) == "2.0"
    assert "removida" in agente.catalogo.executar("extensao_remover", {"nome": "calculadora"})
    assert "ext_calculadora" not in agente.catalogo.grupos()
    assert "não existe" in agente.catalogo.executar("ext_calculadora_somar", {"a": 1, "b": 1})


def test_apos_reiniciar_a_extensao_fica_registrada_sem_processo_e_liga_no_primeiro_uso(agente, cfg):
    instalar(agente)
    agente.amb.extensoes.encerrar_todas()
    outro = Agente(cfg, llm=LLMRoteirizado(), imprimir=False)
    try:
        outro.amb.extensoes.carregar_todas()
        assert outro.amb.extensoes._clientes == {}  # nenhum processo iniciado na partida
        assert outro.catalogo.grupos()["ext_calculadora"] == "extensão calculadora (3 ferramentas)"
        assert len(outro.catalogo.nomes({"ext_calculadora"})) == 3  # ferramentas vieram do cache
        assert outro.catalogo.executar("ext_calculadora_somar", {"a": 4, "b": 4}) == "8.0"
        assert outro.amb.extensoes._clientes["calculadora"].vivo()
    finally:
        outro.amb.extensoes.encerrar_todas()


def test_comando_invalido_devolve_erro_claro(agente):
    saida = agente.catalogo.executar("extensao_instalar", {"nome": "x", "comando": "comando-que-nao-existe-123"})
    assert saida.startswith("ERRO ao iniciar a extensão")
    assert agente.amb.extensoes.listar() == [] and "ext_x" not in agente.catalogo.grupos()
    assert "lista JSON" in agente.catalogo.executar("extensao_instalar", {"nome": "x", "comando": "y", "argumentos": "não é json"})


def test_registro_preguicoso_so_inicia_quando_o_grupo_e_ativado(agente):
    ext = agente.amb.extensoes
    resposta = ext.registrar("docs", {"tipo": "stdio", "comando": sys.executable, "args": [SERVIDOR], "descricao": "documentação de bibliotecas"}, conectar=False)
    assert "inicia quando o grupo 'ext_docs' for ativado" in resposta
    assert ext._clientes == {} and agente.catalogo.nomes({"ext_docs"}) == []
    assert agente.catalogo.grupos()["ext_docs"] == "extensão docs: documentação de bibliotecas (inicia ao ser ativada)"

    saida = agente.catalogo.executar("ativar_ferramentas", {"grupo": "ext_docs"})
    assert saida.startswith("Ativadas 3 ferramentas da extensão") and ext._clientes["docs"].vivo()
    assert agente.amb.ferramentas_avulsas == {"ext_docs_somar", "ext_docs_ler_segredo", "ext_docs_falhar"}
    ext.registrar("quebrada", {"tipo": "stdio", "comando": "comando-inexistente-xyz"}, conectar=False)
    assert agente.catalogo.executar("ativar_ferramentas", {"grupo": "ext_quebrada"}).startswith("ERRO ao iniciar a extensão")


def test_extensao_grande_exige_filtro_e_respeita_o_limite_de_contexto(agente):
    instalar(agente, nome="grande", ambiente='{"FERRAMENTAS_EXTRAS": "30"}')
    cat = agente.catalogo
    sem_filtro = cat.executar("ativar_ferramentas", {"grupo": "ext_grande"})
    assert "tem 33 ferramentas" in sem_filtro and "filtro" in sem_filtro and "ext_grande_issue_acao_0" in sem_filtro
    assert agente.amb.ferramentas_avulsas == set()

    assert "Nenhuma ferramenta combina" in cat.executar("ativar_ferramentas", {"grupo": "ext_grande", "filtro": "inexistente"})
    filtrado = cat.executar("ativar_ferramentas", {"grupo": "ext_grande", "filtro": "issue_acao_0, somar"})
    assert filtrado.startswith("Ativadas 2 ferramentas")
    assert agente.amb.ferramentas_avulsas == {"ext_grande_issue_acao_0", "ext_grande_somar"}
    nomes = {e["nome"] for e in cat.esquemas({"base"}, agente.amb.ferramentas_avulsas)}
    assert "ext_grande_somar" in nomes and "ext_grande_repo_acao_1" not in nomes

    agente.cfg.contexto_tokens = 6000  # modelo com janela pequena: as descrições não podem dominar o contexto
    assert cat.executar("ativar_ferramentas", {"grupo": "ext_grande", "filtro": "acao"}).startswith("NEGADO")
    assert cat.executar("ativar_ferramentas", {"grupo": "navegador"}).startswith("NEGADO")


def test_modelo_ativa_o_grupo_da_extensao_durante_a_tarefa(agente):
    instalar(agente)
    agente.llm.roteiro = [
        chamar("ext_calculadora_somar", a=1, b=1),  # ainda não ativada
        chamar("ativar_ferramentas", grupo="ext_calculadora"),
        chamar("ext_calculadora_somar", a=20, b=22),
        chamar("concluir_tarefa", resultado="A soma é 42."),
    ]
    tid = agente.banco.criar_tarefa("Somar valores", "use a extensão", "financeiro")
    tarefa = agente.banco.tarefa(tid)
    tarefa["tentativas"] = 1
    assert agente.executor.executar(tarefa)["resultado"] == "A soma é 42."
    resultados = [m["content"] for m in agente.llm.historico[-1][0] if m["role"] == "tool"]
    assert "grupo='ext_calculadora' e um filtro" in resultados[0]
    assert resultados[2] == "42.0"
    assert "ext_calculadora_somar" in {f["nome"] for f in agente.llm.historico[-1][1]}
    # o conjunto de ferramentas ligadas é reiniciado a cada tarefa
    tarefa2 = agente.banco.tarefa(agente.banco.criar_tarefa("Outra", "d", "financeiro"))
    tarefa2["tentativas"] = 1
    agente.llm.roteiro = [chamar("concluir_tarefa", resultado="ok")]
    agente.executor.executar(tarefa2)
    assert "ext_calculadora_somar" not in {f["nome"] for f in agente.llm.historico[-1][1]}


# ---------------------------------------------------------------------- servidor remoto (HTTP)
def servidor_http(modo="json", token="tok-secreto-123"):
    """Imita um servidor MCP remoto: responde em JSON ou em fluxo de eventos e exige o token."""
    estado = {"pedidos": []}

    def manipulador(pedido: httpx.Request) -> httpx.Response:
        if pedido.method == "DELETE":
            return httpx.Response(200)
        estado["pedidos"].append(pedido)
        if pedido.headers.get("authorization") != f"Bearer {token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        corpo = json.loads(pedido.content)
        if "id" not in corpo:
            return httpx.Response(202)
        metodo = corpo["method"]
        if metodo == "initialize":
            resultado = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "remoto", "version": "1"}}
        elif metodo == "tools/list":
            resultado = {"tools": [{"name": "buscar_issue", "description": "Busca issues.", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}]}
        else:
            resultado = {"content": [{"type": "text", "text": f"achado: {corpo['params']['arguments']['q']}"}]}
        resposta = {"jsonrpc": "2.0", "id": corpo["id"], "result": resultado}
        cabecalhos = {"Mcp-Session-Id": "sessao-1"}
        if modo == "sse":
            texto = "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}) + "\n\n"
            texto += "event: message\ndata: " + json.dumps(resposta) + "\n\n"
            return httpx.Response(200, content=texto.encode(), headers={**cabecalhos, "Content-Type": "text/event-stream"})
        return httpx.Response(200, json=resposta, headers=cabecalhos)

    return httpx.MockTransport(manipulador), estado


@pytest.mark.parametrize("modo", ["json", "sse"])
def test_cliente_http_fala_o_protocolo_nos_dois_formatos_de_resposta(modo):
    transporte, estado = servidor_http(modo)
    cliente = ClienteMCPHttp("remoto", "https://mcp.exemplo.test/mcp", {"Authorization": "Bearer tok-secreto-123"}, transporte)
    cliente.iniciar()
    assert [f["name"] for f in cliente.ferramentas()] == ["buscar_issue"]
    assert cliente.chamar("buscar_issue", {"q": "erro no login"}) == "achado: erro no login"
    ultimo = estado["pedidos"][-1]
    assert ultimo.headers["mcp-session-id"] == "sessao-1" and ultimo.headers["mcp-protocol-version"] == "2025-06-18"
    assert "text/event-stream" in ultimo.headers["accept"]
    cliente.encerrar()
    assert not cliente.vivo()


def test_cliente_http_recusa_credencial_invalida():
    transporte, _ = servidor_http()
    cliente = ClienteMCPHttp("remoto", "https://mcp.exemplo.test/mcp", {"Authorization": "Bearer errado"}, transporte)
    with pytest.raises(ErroMCP, match="recusou a credencial"):
        cliente.iniciar()


def test_extensao_remota_instalada_pela_ferramenta(agente):
    transporte, _ = servidor_http()
    agente.amb.extensoes._transporte_http = transporte
    saida = agente.catalogo.executar(
        "extensao_instalar",
        {"nome": "remota", "url": "https://mcp.exemplo.test/mcp", "cabecalhos": '{"Authorization": "Bearer tok-secreto-123"}'},
    )
    assert "instalada com 1 ferramentas" in saida
    assert agente.catalogo.executar("ext_remota_buscar_issue", {"q": "x"}) == "achado: x"
    listagem = agente.catalogo.executar("extensao_listar", {})
    assert "remota (grupo ext_remota, http, 1 ferramentas)" in listagem and "tok-secreto-123" not in listagem
    agente.registro.evento("resultado", "cabeçalho Bearer tok-secreto-123 usado")
    assert "tok-secreto-123" not in agente.banco.eventos_recentes(1)[0]["titulo"]
    assert "ERRO: informe a URL" in agente.amb.extensoes.registrar("ruim", {"tipo": "http", "url": "ftp://x"})


# ---------------------------------------------------------------------- catálogo curado
CATALOGO_DE_TESTE = [
    {"nome": "docs", "area": "programacao", "tipo": "stdio", "comando": sys.executable, "args": [SERVIDOR], "padrao": True,
     "descricao": "Documentação de bibliotecas."},
    {"nome": "hospedagem", "area": "infraestrutura", "tipo": "http", "url": "https://mcp.exemplo.test/mcp",
     "cabecalhos": {"Authorization": "Bearer {segredo}"}, "descricao": "Publicar sites.",
     "credencial": {"servico": "hospedagem-token", "como_obter": "Crie o token no painel do serviço."}},
    {"nome": "banco", "area": "dados", "tipo": "stdio", "comando": sys.executable, "args": [SERVIDOR, "--dsn", "{dsn}"],
     "descricao": "Consultar bancos.", "parametros": {"dsn": "Endereço do banco."}},
    {"nome": "docs-com-chave", "area": "programacao", "tipo": "stdio", "comando": sys.executable, "args": [SERVIDOR],
     "env": {"CHAVE_API": "{segredo}"}, "padrao": True, "descricao": "Funciona sem chave, melhor com ela.",
     "credencial": {"servico": "docs-token", "opcional": True, "como_obter": "Chave gratuita no painel."}},
    {"nome": "sem-programa", "area": "web", "tipo": "stdio", "comando": "programa-que-nao-existe-xyz", "args": [], "descricao": "Exige programa ausente."},
]


@pytest.fixture
def catalogo(monkeypatch):
    monkeypatch.setattr(modulo, "carregar_catalogo", lambda: CATALOGO_DE_TESTE)


def test_catalogo_lista_exigencias_e_instala_pelo_nome(agente, catalogo):
    cat = agente.catalogo
    lista = cat.executar("extensao_catalogo", {})
    assert "- docs [programacao] disponível: Documentação de bibliotecas." in lista
    assert "credencial 'hospedagem-token' no cofre (falta)" in lista and "parâmetros: dsn" in lista
    assert "programa programa-que-nao-existe-xyz (não instalado)" in lista
    assert cat.executar("extensao_catalogo", {"area": "dados"}).count("\n- ") == 0 and "- banco" in cat.executar("extensao_catalogo", {"area": "dados"})

    assert "instalada com 3 ferramentas" in cat.executar("extensao_instalar", {"nome": "docs"})
    assert "- docs [programacao] INSTALADA" in cat.executar("extensao_catalogo", {})
    assert "não está no catálogo" in cat.executar("extensao_instalar", {"nome": "inexistente"})
    assert "FALTA PARÂMETRO 'dsn'" in cat.executar("extensao_instalar", {"nome": "banco"})
    assert "instalada com 3 ferramentas" in cat.executar("extensao_instalar", {"nome": "banco", "parametros": '{"dsn": "sqlite:///x.db"}'})
    assert agente.amb.extensoes._config()["banco"]["args"][-1] == "sqlite:///x.db"
    assert "não está instalado nesta máquina" in cat.executar("extensao_instalar", {"nome": "sem-programa"})


def test_credencial_no_cofre_libera_a_extensao_do_catalogo(agente, catalogo):
    transporte, estado = servidor_http(token="token-da-hospedagem-9")
    agente.amb.extensoes._transporte_http = transporte
    cat = agente.catalogo
    falta = cat.executar("extensao_instalar", {"nome": "hospedagem"})
    assert falta.startswith("FALTA CREDENCIAL") and "hospedagem-token" in falta and "Crie o token no painel" in falta

    salva = cat.executar("credencial_salvar", {"servico": "hospedagem-token", "usuario": "empresa", "senha": "token-da-hospedagem-9"})
    assert "ficaram disponíveis os grupos de extensão: ext_hospedagem" in salva
    assert estado["pedidos"] == []  # só registrada: nenhuma conexão ainda
    assert "ext_hospedagem" in cat.grupos()

    assert cat.executar("ativar_ferramentas", {"grupo": "ext_hospedagem"}).startswith("Ativadas 1 ferramentas")
    assert estado["pedidos"][0].headers["authorization"] == "Bearer token-da-hospedagem-9"
    assert cat.executar("ext_hospedagem_buscar_issue", {"q": "site"}) == "achado: site"


def test_credencial_opcional_funciona_sem_a_chave_e_passa_a_usar_quando_ela_chega(agente, catalogo):
    cat = agente.catalogo
    assert "credencial opcional 'docs-token' no cofre (falta)" in cat.executar("extensao_catalogo", {})
    assert "instalada com 3 ferramentas" in cat.executar("extensao_instalar", {"nome": "docs-com-chave"})
    assert agente.amb.extensoes._config()["docs_com_chave"]["env"] == {}
    assert cat.executar("ext_docs_com_chave_ler_segredo", {}) == "(sem conteúdo)"

    cat.executar("credencial_salvar", {"servico": "docs-token", "usuario": "empresa", "senha": "chave-opcional-123"})
    assert agente.amb.extensoes._config()["docs_com_chave"]["env"] == {"CHAVE_API": "chave-opcional-123"}
    assert "docs_com_chave" not in agente.amb.extensoes._clientes  # o processo antigo foi encerrado; a próxima chamada religa com a chave
    assert len(agente.catalogo.nomes({"ext_docs_com_chave"})) == 3  # as ferramentas continuam registradas
    assert cat.executar("ext_docs_com_chave_ler_segredo", {}) == "chave-opcional-123"


def test_catalogo_real_e_valido():
    entradas = json.loads((Path(modulo.ARQUIVO_CATALOGO)).read_text(encoding="utf-8"))["extensoes"]
    nomes = [e["nome"] for e in entradas]
    assert len(nomes) == len(set(nomes)) and {"context7", "chrome-devtools", "github", "cloudflare", "banco-de-dados"} <= set(nomes)
    for e in entradas:
        assert e["descricao"] and e["area"] and e["fonte"].startswith("https://")
        if e["tipo"] == "http":
            assert e["url"].startswith("https://") and "{segredo}" in json.dumps(e["cabecalhos"]) and e["credencial"]["como_obter"]
        else:
            assert e["comando"] in ("npx", "uvx") and e["args"]
        if e.get("padrao"):  # o que vem ligado por padrão não pode exigir nada
            assert not e.get("parametros") and (not e.get("credencial") or e["credencial"].get("opcional"))

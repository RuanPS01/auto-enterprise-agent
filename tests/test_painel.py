import pytest
from fastapi.testclient import TestClient

from conftest import LLMRoteirizado
from empresa_auto.agente import Agente
from empresa_auto.painel import criar_app

CAB = {"X-Requested-With": "empresa-auto"}


@pytest.fixture
def cliente(agente):
    return TestClient(criar_app(agente), base_url="http://127.0.0.1:8787")


def test_pagina_e_arquivos_estaticos(cliente):
    pagina = cliente.get("/")
    assert pagina.status_code == 200 and "Como a empresa deve começar?" in pagina.text
    assert cliente.get("/estatico/app.js").status_code == 200
    assert cliente.get("/estatico/estilo.css").status_code == 200
    assert pagina.headers["x-frame-options"] == "DENY"


def test_partida_pela_ideia_e_estado(cliente, agente):
    estado = cliente.get("/api/estado").json()
    assert estado["iniciada"] is False and estado["llm"]["modelo"] == "qwen3:8b"

    curto = cliente.post("/api/iniciar", json={"modo": "ideia", "ideia": "app"}, headers=CAB)
    assert curto.status_code == 400 and "mais de detalhe" in curto.json()["detail"]

    ok = cliente.post(
        "/api/iniciar", json={"modo": "ideia", "ideia": "Agenda online para barbearias de bairro"}, headers=CAB
    )
    assert ok.status_code == 200
    estado = cliente.get("/api/estado").json()
    assert estado["iniciada"] and estado["empresa"]["ideia"] == "Agenda online para barbearias de bairro"
    assert [t["titulo"] for t in estado["tarefas_abertas"]][0] == "Pesquisar o mercado da ideia do dono"
    assert len(estado["habilidades"]) >= 10
    repetido = cliente.post("/api/iniciar", json={"modo": "auto"}, headers=CAB)
    assert repetido.status_code == 400 and "já foi iniciada" in repetido.json()["detail"]

    eventos = cliente.get("/api/eventos").json()["eventos"]
    assert eventos[-1]["titulo"] == "Empresa iniciada a partir da ideia do dono"
    assert cliente.get(f"/api/eventos?depois={eventos[-1]['id']}").json()["eventos"] == []


def test_alteracoes_exigem_cabecalho_proprio_e_host_local(cliente, agente):
    assert cliente.post("/api/iniciar", json={"modo": "auto"}).status_code == 403  # sem o cabeçalho: outro site não consegue agir
    assert not agente.empresa_iniciada()
    externo = cliente.get("/api/estado", headers={"Host": "site-malicioso.example"})
    assert externo.status_code == 403


def test_pausar_retomar_e_bloqueios(cliente, agente):
    cliente.post("/api/iniciar", json={"modo": "auto"}, headers=CAB)
    assert cliente.post("/api/pausar", headers=CAB).status_code == 200
    assert cliente.get("/api/estado").json()["pausado"] is True
    cliente.post("/api/retomar", headers=CAB)
    assert cliente.get("/api/estado").json()["pausado"] is False

    agente.catalogo.executar("bloqueio_relatar", {"titulo": "Cadastro exige CAPTCHA", "detalhe": "tentei o serviço X"})
    bloqueios = cliente.get("/api/estado").json()["bloqueios"]
    assert bloqueios[0]["titulo"] == "Cadastro exige CAPTCHA"
    cliente.post(f"/api/bloqueios/{bloqueios[0]['id']}/resolver", headers=CAB)
    assert cliente.get("/api/estado").json()["bloqueios"] == []


def test_cartao_e_conta_fornecidos_pelo_dono(cliente, agente):
    invalido = cliente.post(
        "/api/cartao", json={"numero": "12", "validade": "01/30", "cvv": "123", "limite_mensal": 50}, headers=CAB
    )
    assert invalido.status_code == 400
    ok = cliente.post(
        "/api/cartao",
        json={"numero": "4111 1111 1111 1111", "validade": "01/30", "cvv": "123", "titular": "Dona", "limite_mensal": 80},
        headers=CAB,
    )
    assert ok.status_code == 200
    estado = cliente.get("/api/estado").json()
    assert estado["cartao"] == {
        "configurado": True, "final": "1111", "titular": "Dona", "limite_mensal": 80.0, "gasto_mes": 0.0, "disponivel": 80.0,
    }
    assert "4111111111111111" not in cliente.get("/api/estado").text
    assert "4111" not in cliente.get("/api/eventos").text.replace("final 1111", "")
    cliente.delete("/api/cartao", headers=CAB)
    assert cliente.get("/api/estado").json()["cartao"] == {"configurado": False}

    cliente.post(
        "/api/contas", json={"servico": "GitHub", "usuario": "dona@exemplo.com", "senha": "senha-do-dono-123"}, headers=CAB
    )
    contas = cliente.get("/api/estado").json()["contas"]
    assert contas[0]["servico"] == "github" and contas[0]["origem"] == "dono"
    assert "senha-do-dono-123" not in cliente.get("/api/estado").text
    assert agente.cofre.obter_credencial("github")["senha"] == "senha-do-dono-123"


def test_resumo_semanal(cliente, agente):
    import time

    tid = agente.banco.criar_tarefa("Publicar o site", "d", "engenharia")
    agente.banco.atualizar_tarefa(tid, status="concluida", concluido_em=time.time(), resultado="Site no ar.")
    agente.banco.registrar_decisao("Focar em barbearias", "maior demanda")
    resumo = cliente.get("/api/resumo").json()
    assert resumo["semana_atual"] and resumo["numeros"]["tarefas_concluidas"] == 1
    assert resumo["numeros"]["por_area"] == {"engenharia": 1}
    assert resumo["numeros"]["decisoes"][0]["titulo"] == "Focar em barbearias"
    assert resumo["semana"] in resumo["semanas"]
    assert cliente.get("/api/resumo?semana=invalida").status_code == 400
    assert cliente.get("/api/captura").status_code == 404


def test_painel_exposto_na_rede_exige_token(cfg):
    cfg.host = "0.0.0.0"
    agente = Agente(cfg, llm=LLMRoteirizado(), imprimir=False)
    cliente = TestClient(criar_app(agente), base_url="http://192.168.0.50:8787", follow_redirects=False)
    token = (cfg.dir_dados / "token_painel.txt").read_text().strip()

    assert cliente.get("/api/estado").status_code == 401
    pagina = cliente.get("/")
    assert pagina.status_code == 401 and "Token de acesso" in pagina.text
    assert cliente.get("/?token=errado").status_code == 401

    entrada = cliente.get(f"/?token={token}")
    assert entrada.status_code == 303 and "ea_token" in entrada.headers["set-cookie"]
    cliente.cookies.set("ea_token", token)
    assert cliente.get("/api/estado").status_code == 200
    sem_cookie = TestClient(criar_app(agente), base_url="http://192.168.0.50:8787")
    assert sem_cookie.get("/api/estado", headers={"Authorization": f"Bearer {token}"}).status_code == 200

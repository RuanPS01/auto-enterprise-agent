"""Agente real (cliente HTTP do Ollama, laço e ferramentas) contra um servidor Ollama simulado."""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "apoio"))

import ollama_simulado  # noqa: E402

from empresa_auto.agente import Agente  # noqa: E402
from empresa_auto.config import carregar_config  # noqa: E402
from empresa_auto.llm import ClienteLLM, ErroLLM  # noqa: E402


@pytest.fixture
def ollama():
    servidor = ollama_simulado.criar_servidor()
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.shutdown()


def test_empresa_nasce_e_avanca_usando_a_api_do_ollama(tmp_path, ollama):
    cfg = carregar_config(tmp_path / "dados", url_llm=ollama)
    cfg.intervalo_ocioso_seg = 1
    cfg.pacote_padrao = False
    agente = Agente(cfg, imprimir=False)
    assert isinstance(agente.llm, ClienteLLM) and agente.llm.modelo_disponivel()
    agente.iniciar_empresa("ideia", "Agenda online simples e gratuita para barbearias de bairro")

    fio = threading.Thread(target=agente.rodar, daemon=True)
    fio.start()
    fim = time.time() + 90
    while time.time() < fim and agente.banco.contagem_tarefas()["concluida"] < 4:
        time.sleep(0.2)
    agente.parar()
    fio.join(timeout=30)
    assert not fio.is_alive()

    empresa = agente.banco.empresa()
    assert empresa["nome"] == "Agenda Navalha" and empresa["fase"] == "construcao"
    assert agente.banco.contagem_tarefas()["concluida"] >= 4 and agente.banco.contagem_tarefas()["falhou"] == 0
    assert agente.banco.decisoes(10) and agente.banco.contar_memorias() >= 4
    assert (cfg.dir_trabalho / "agenda" / "index.html").exists()  # o agente escreveu arquivos de verdade
    titulos = [e["titulo"] for e in agente.banco.eventos_recentes(600)]
    assert "Modelo local disponível" in titulos
    assert any(t.startswith("Planejamento concluído: 2 tarefa(s) nova(s)") for t in titulos)
    assert not any(e["nivel"] == "erro" for e in agente.banco.eventos_recentes(600)), "houve erro durante a execução"


def test_variante_de_nuvem_e_recusada(tmp_path):
    with pytest.raises(ErroLLM, match="variante de nuvem"):
        ClienteLLM(carregar_config(tmp_path, modelo="gpt-oss:20b-cloud"))

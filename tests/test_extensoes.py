import json
import sys
from pathlib import Path

from conftest import chamar

SERVIDOR = str(Path(__file__).parent / "apoio" / "servidor_mcp_falso.py")


def instalar(agente, nome="Calculadora", ambiente="{}"):
    return agente.catalogo.executar(
        "extensao_instalar",
        {"nome": nome, "comando": sys.executable, "argumentos": json.dumps([SERVIDOR]), "ambiente": ambiente},
    )


def test_instala_servidor_mcp_e_usa_as_ferramentas(agente):
    saida = instalar(agente, ambiente='{"CHAVE_API": "chave-secreta-xyz-123"}')
    assert "instalada com 3 ferramentas" in saida and "ext_calculadora" in saida
    cat = agente.catalogo
    assert cat.grupos()["ext_calculadora"] == "extensão calculadora (3 ferramentas)"
    assert cat.executar("ext_calculadora_somar", {"a": "2", "b": 3.5}) == "5.5"  # tipos consertados pelo esquema
    assert cat.executar("ext_calculadora_ler_segredo", {}) == "chave-secreta-xyz-123"
    assert cat.executar("ext_calculadora_falhar", {}) == "ERRO da extensão: deu errado"
    assert "calculadora (grupo ext_calculadora, 3 ferramentas, ativa)" in cat.executar("extensao_listar", {})

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


def test_extensao_volta_apos_reiniciar_o_agente(agente, cfg):
    from conftest import LLMRoteirizado
    from empresa_auto.agente import Agente

    instalar(agente)
    agente.amb.extensoes.encerrar_todas()
    outro = Agente(cfg, llm=LLMRoteirizado(), imprimir=False)
    try:
        outro.amb.extensoes.carregar_todas()
        assert outro.catalogo.executar("ext_calculadora_somar", {"a": 4, "b": 4}) == "8.0"
    finally:
        outro.amb.extensoes.encerrar_todas()


def test_comando_invalido_devolve_erro_claro(agente):
    saida = agente.catalogo.executar("extensao_instalar", {"nome": "x", "comando": "comando-que-nao-existe-123"})
    assert saida.startswith("ERRO ao iniciar a extensão")
    assert agente.amb.extensoes.listar() == []
    assert "lista JSON" in agente.catalogo.executar("extensao_instalar", {"nome": "x", "comando": "y", "argumentos": "não é json"})


def test_modelo_ativa_o_grupo_da_extensao_durante_a_tarefa(agente):
    instalar(agente)
    agente.llm.roteiro = [
        chamar("ativar_ferramentas", grupo="ext_calculadora"),
        chamar("ext_calculadora_somar", a=20, b=22),
        chamar("concluir_tarefa", resultado="A soma é 42."),
    ]
    tid = agente.banco.criar_tarefa("Somar valores", "use a extensão", "financeiro")
    tarefa = agente.banco.tarefa(tid)
    tarefa["tentativas"] = 1
    assert agente.executor.executar(tarefa)["resultado"] == "A soma é 42."
    resultados = [m["content"] for m in agente.llm.historico[-1][0] if m["role"] == "tool"]
    assert resultados[1] == "42.0"

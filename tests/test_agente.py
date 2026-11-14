import threading
import time

import pytest

from conftest import LLMRoteirizado, chamar, falar
from empresa_auto.agente import Agente
from empresa_auto.agente.resumo import dados_do_resumo
from empresa_auto.llm import LLMIndisponivel


def nova_tarefa(agente, titulo="Pesquisar concorrentes", area="pesquisa", tipo="trabalho"):
    tid = agente.banco.criar_tarefa(titulo, "descrição da tarefa", area, tipo=tipo)
    tarefa = agente.banco.tarefa(tid)
    tarefa["tentativas"] = 1
    return tarefa


def test_executor_usa_ferramentas_e_conclui(agente):
    agente.llm.roteiro = [
        chamar("memoria_salvar", titulo="Concorrente Beta", conteudo="cobra 20 reais", categoria="mercado"),
        chamar("concluir_tarefa", resultado="Encontrei um concorrente e salvei na memória.", sucesso=True),
    ]
    resultado = agente.executor.executar(nova_tarefa(agente))
    assert resultado == {"situacao": "concluida", "resultado": "Encontrei um concorrente e salvei na memória.", "notas": ""}
    assert agente.banco.buscar_memorias("Beta")[0]["conteudo"] == "cobra 20 reais"
    # o modelo recebeu as regras, a tarefa e o resultado da ferramenta
    mensagens, ferramentas = agente.llm.historico[1]
    assert "REGRAS INVIOLÁVEIS" in mensagens[0]["content"] and "pesquisa-de-mercado" in mensagens[0]["content"]
    assert "Pesquisar concorrentes" in mensagens[1]["content"]
    assert mensagens[-1]["role"] == "tool" and "salvo" in mensagens[-1]["content"]
    nomes = {f["nome"] for f in ferramentas}
    assert {"navegador_abrir", "pesquisar_web", "concluir_tarefa"} <= nomes  # área pesquisa liga o navegador
    assert "servico_iniciar" not in nomes and "cartao_autorizar" not in nomes


def test_executor_ativa_grupo_sob_demanda(agente):
    agente.llm.roteiro = [
        chamar("servico_listar"),  # grupo ainda desligado
        chamar("ativar_ferramentas", grupo="operacao"),
        chamar("servico_listar"),
        chamar("concluir_tarefa", resultado="ok"),
    ]
    agente.executor.executar(nova_tarefa(agente, area="produto"))
    resultados = [m["content"] for m in agente.llm.historico[-1][0] if m["role"] == "tool"]
    assert "não está ativo" in resultados[0] and "grupo='operacao'" in resultados[0]
    assert "ativado" in resultados[1]
    assert resultados[2] == "Nenhum serviço cadastrado."
    assert "servico_iniciar" in {f["nome"] for f in agente.llm.historico[-1][1]}


def test_executor_cobra_acao_e_aceita_relato_final(agente):
    relato = "Relatório completo da pesquisa. " * 12
    agente.llm.roteiro = [falar("Vou pensar."), falar("Ainda pensando."), falar(relato)]
    resultado = agente.executor.executar(nova_tarefa(agente))
    assert resultado["situacao"] == "concluida" and resultado["resultado"].startswith("Relatório completo")
    lembretes = [m for m in agente.llm.historico[-1][0] if m["role"] == "user" and "sem usar ferramentas" in m["content"]]
    assert len(lembretes) == 2


def test_executor_interrompe_repeticao_e_anota_progresso(agente):
    agente.llm.roteiro = lambda mensagens, ferramentas: chamar("memoria_buscar", consulta="nada")
    resultado = agente.executor.executar(nova_tarefa(agente))
    assert resultado["situacao"] == "incompleta" and resultado["notas"] == "Texto gerado pelo modelo de teste."
    assert len(agente.llm.historico) <= 8  # parou muito antes do limite de 40 passos
    assert any("repetiu a mesma ação" in m["content"] for m in agente.llm.historico[-1][0] if m["role"] == "user")


def test_executor_compacta_contexto_longo(agente):
    import json

    from empresa_auto.llm import estimar_tokens

    agente.cfg.contexto_tokens = 12000
    agente.cfg.max_passos_tarefa = 30
    contador = {"n": 0}

    def roteiro(mensagens, ferramentas):
        contador["n"] += 1
        if contador["n"] > 25:
            return chamar("concluir_tarefa", resultado="fim")
        return chamar("escrever_arquivo", caminho=f"notas/{contador['n']}.txt", conteudo="conteúdo longo " * 150)

    agente.llm.roteiro = roteiro
    resultado = agente.executor.executar(nova_tarefa(agente, area="engenharia"))
    assert resultado["situacao"] == "concluida" and contador["n"] == 26
    assert len(list((agente.cfg.dir_trabalho / "notas").iterdir())) == 25

    # o pedido enviado ao modelo (mensagens mais ferramentas) nunca passou da janela configurada
    maior = max(estimar_tokens(m) + len(json.dumps(f, ensure_ascii=False)) // 3 for m, f in agente.llm.historico)
    assert maior < 12000
    ultimas = agente.llm.historico[-1][0]
    assert len(ultimas) < 20  # 25 passos fariam mais de 50 mensagens sem compactação
    assert ultimas[0]["role"] == "system" and "TAREFA #" in ultimas[1]["content"]
    resumo = next(m for m in ultimas if m.get("resumo"))
    assert "escrever_arquivo(" in resumo["content"] and "resultou em: Arquivo gravado" in resumo["content"]
    for i, m in enumerate(ultimas):  # nenhum resultado de ferramenta ficou órfão
        if m["role"] == "tool":
            assert ultimas[i - 1]["role"] in ("assistant", "tool")


def test_planejamento_enxerga_apenas_gestao_e_cria_tarefas(agente):
    agente.iniciar_empresa("auto")
    agente.llm.roteiro = [
        chamar("empresa_atualizar", campo="nome", valor="Cardápio Fácil"),
        chamar("tarefa_criar", titulo="Criar o repositório do produto", descricao="git init", area="engenharia", prioridade=2),
        chamar("concluir_tarefa", resultado="Plano definido."),
    ]
    tarefa = nova_tarefa(agente, "Ciclo de planejamento", "produto", tipo="planejamento")
    agente.executor.executar(tarefa)
    mensagens, ferramentas = agente.llm.historico[0]
    nomes = {f["nome"] for f in ferramentas}
    assert nomes == {
        "concluir_tarefa", "tarefa_criar", "tarefa_listar", "tarefa_cancelar", "memoria_buscar", "memoria_salvar",
        "empresa_atualizar", "decisao_registrar", "metrica_registrar", "bloqueio_relatar",
    }
    assert "CICLO DE PLANEJAMENTO" in mensagens[1]["content"] and "ORIENTAÇÃO DA FASE ATUAL (descoberta)" in mensagens[1]["content"]
    assert "Mapear oportunidades" in mensagens[1]["content"]  # tarefas abertas aparecem na situação
    assert agente.banco.obter("nome") == "Cardápio Fácil"
    criada = next(t for t in agente.banco.tarefas_abertas() if t["titulo"].startswith("Criar o repositório"))
    assert criada["origem"] == "planejamento" and criada["prioridade"] == 2


def test_partida_exige_ideia_e_acontece_uma_vez(agente):
    with pytest.raises(ValueError):
        agente.iniciar_empresa("ideia", "curta")
    agente.iniciar_empresa("ideia", "Plataforma de cardápios digitais para pequenos restaurantes")
    assert agente.empresa_iniciada() and agente.banco.obter("fase") == "descoberta"
    abertas = agente.banco.tarefas_abertas()
    assert [t["area"] for t in abertas] == ["pesquisa", "produto"]
    assert "cardápios digitais" in abertas[0]["descricao"]
    with pytest.raises(ValueError):
        agente.iniciar_empresa("auto")


def rodar_ate(agente, condicao, limite=30):
    fio = threading.Thread(target=agente.rodar, daemon=True)
    fio.start()
    fim = time.time() + limite
    while time.time() < fim and not condicao():
        time.sleep(0.05)
    agente.parar()
    fio.join(timeout=15)
    assert not fio.is_alive(), "o laço do agente não encerrou"
    assert condicao(), "a condição esperada não foi atingida a tempo"


def test_laco_completo_executa_fila_planeja_e_resume(cfg):
    cfg.tarefas_por_planejamento = 2
    planejamentos = {"n": 0}

    def roteiro(mensagens, ferramentas):
        pedido = mensagens[1]["content"]
        ultimo = mensagens[-1]
        if "CICLO DE PLANEJAMENTO" in pedido:
            if ultimo["role"] == "user":
                planejamentos["n"] += 1
                return chamar(
                    "tarefa_criar",
                    titulo=f"Construir a etapa {planejamentos['n']} do produto",
                    descricao="implementar e testar",
                    area="engenharia",
                )
            return chamar("concluir_tarefa", resultado="Plano atualizado.")
        if ultimo["role"] == "user":
            return chamar("memoria_salvar", titulo="Aprendizado", conteudo="algo útil", categoria="aprendizado")
        return chamar("concluir_tarefa", resultado="Trabalho feito e verificado.", sucesso=True)

    agente = Agente(cfg, llm=LLMRoteirizado(roteiro), imprimir=False)
    agente.iniciar_empresa("auto")
    rodar_ate(agente, lambda: agente.banco.contagem_tarefas()["concluida"] >= 5)

    contagem = agente.banco.contagem_tarefas()
    assert contagem["falhou"] == 0 and contagem["concluida"] >= 5
    assert planejamentos["n"] >= 2  # planejou após as tarefas iniciais e de novo depois
    # o modelo de teste responde na hora, então o agente pode ter concluído dezenas de tarefas: olhe todas
    titulos = [t["titulo"] for t in agente.banco.tarefas(limite=1000) if t["status"] == "concluida"]
    assert "Mapear oportunidades de negócio no mercado atual" in titulos
    assert any(t.startswith("Construir a etapa") for t in titulos)
    # resultados viram memória pesquisável e o resumo da semana foi escrito
    assert agente.banco.buscar_memorias("Resultado da tarefa Mapear oportunidades")
    resumo = dados_do_resumo(agente.banco)
    assert resumo["numeros"]["tarefas_concluidas"] >= 5 and resumo["texto"] == "Texto gerado pelo modelo de teste."
    tipos = {e["tipo"] for e in agente.banco.eventos_recentes(500)}
    assert {"sistema", "tarefa", "ferramenta", "resultado", "plano", "memoria", "resumo"} <= tipos
    assert agente.atividade.como_dict()["estado"] == "desligado"


def test_tarefa_incompleta_volta_para_fila_e_depois_falha(cfg):
    cfg.max_passos_tarefa = 3
    cfg.max_tentativas_tarefa = 2
    contador = {"n": 0}

    def roteiro(mensagens, ferramentas):
        if "CICLO DE PLANEJAMENTO" in mensagens[1]["content"]:
            return chamar("concluir_tarefa", resultado="sem novidades")
        contador["n"] += 1
        return chamar("memoria_buscar", consulta=f"busca {contador['n']}")

    agente = Agente(cfg, llm=LLMRoteirizado(roteiro), imprimir=False)
    agente.banco.definir("iniciada", True)
    tid = agente.banco.criar_tarefa("Tarefa impossível", "nunca termina", "pesquisa")
    rodar_ate(agente, lambda: agente.banco.tarefa(tid)["status"] == "falhou")
    tarefa = agente.banco.tarefa(tid)
    assert tarefa["tentativas"] == 2 and "Não foi concluída" in tarefa["resultado"]
    assert tarefa["notas"] == "Texto gerado pelo modelo de teste."  # anotações passadas para a segunda tentativa
    segunda_tentativa = [m for m, _ in agente.llm.historico if "ANOTAÇÕES DA TENTATIVA ANTERIOR" in m[1]["content"]]
    assert segunda_tentativa


def test_queda_do_modelo_nao_gasta_tentativa_e_o_agente_se_recupera(cfg, monkeypatch):
    estado = {"falhas": 2}

    def roteiro(mensagens, ferramentas):
        if estado["falhas"] > 0:
            estado["falhas"] -= 1
            raise LLMIndisponivel("servidor do modelo fora do ar")
        return chamar("concluir_tarefa", resultado="feito depois da queda")

    agente = Agente(cfg, llm=LLMRoteirizado(roteiro), imprimir=False)
    monkeypatch.setattr(agente, "_dormir", lambda segundos: time.sleep(0.01))
    agente.banco.definir("iniciada", True)
    tid = agente.banco.criar_tarefa("Tarefa resistente", "d", "pesquisa")
    rodar_ate(agente, lambda: agente.banco.tarefa(tid)["status"] == "concluida")
    tarefa = agente.banco.tarefa(tid)
    assert tarefa["tentativas"] == 1 and tarefa["resultado"] == "feito depois da queda"
    assert any(e["titulo"].startswith("Modelo local indisponível") for e in agente.banco.eventos_recentes(100))


def test_pausa_segura_o_trabalho(cfg):
    agente = Agente(cfg, llm=LLMRoteirizado(), imprimir=False)
    agente.iniciar_empresa("auto")
    agente.pausar()
    fio = threading.Thread(target=agente.rodar, daemon=True)
    fio.start()
    time.sleep(1.0)
    assert agente.llm.historico == [] and agente.atividade.como_dict()["estado"] == "pausado"
    agente.retomar()
    fim = time.time() + 15
    while time.time() < fim and not agente.llm.historico:
        time.sleep(0.05)
    agente.parar()
    fio.join(timeout=15)
    assert agente.llm.historico, "o agente não retomou o trabalho"

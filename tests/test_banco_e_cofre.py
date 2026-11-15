import time

import pytest

from empresa_auto.banco import Banco
from empresa_auto.cofre import Cofre, ErroCofre, gerar_senha
from empresa_auto.registro import Registro


def test_fila_respeita_prioridade_e_adiamento(tmp_path):
    banco = Banco(tmp_path / "b.db")
    banco.criar_tarefa("baixa", prioridade=4)
    urgente = banco.criar_tarefa("urgente", prioridade=1)
    banco.criar_tarefa("adiada", prioridade=1, adiar_minutos=60)
    assert banco.proxima_tarefa()["id"] == urgente
    banco.atualizar_tarefa(urgente, status="concluida", concluido_em=time.time())
    assert banco.proxima_tarefa()["titulo"] == "baixa"
    assert banco.existe_tarefa_aberta("ADIADA")
    assert banco.proximo_despertar() > time.time()


def test_tarefas_interrompidas_voltam_para_a_fila(tmp_path):
    banco = Banco(tmp_path / "b.db")
    tid = banco.criar_tarefa("x")
    banco.atualizar_tarefa(tid, status="em_andamento")
    assert banco.proxima_tarefa() is None
    assert banco.retomar_interrompidas() == 1
    assert banco.proxima_tarefa()["id"] == tid


def test_memoria_encontra_por_palavra(tmp_path):
    banco = Banco(tmp_path / "b.db")
    banco.salvar_memoria("Concorrente Alfa", "cobra 30 reais por mês e tem reclamações de suporte", "mercado")
    banco.salvar_memoria("Hospedagem", "site publicado em páginas estáticas", "tecnico")
    achados = banco.buscar_memorias("reclamações do concorrente")
    assert achados and achados[0]["titulo"] == "Concorrente Alfa"
    assert banco.buscar_memorias("???")  # consulta sem termos devolve as mais recentes


def test_automacao_vence_e_reagenda(tmp_path):
    banco = Banco(tmp_path / "b.db")
    aid = banco.criar_automacao("Ler e-mails", "ler a caixa", 15)
    assert banco.automacoes_vencidas() == []
    banco._executar("UPDATE automacoes SET proxima = 0 WHERE id = ?", (aid,))
    assert [a["id"] for a in banco.automacoes_vencidas()] == [aid]
    banco.marcar_automacao_executada(aid, 15)
    assert banco.automacoes_vencidas() == []
    assert banco.remover_automacao(aid) and not banco.automacoes()


def test_empresa_guarda_valores_estruturados(tmp_path):
    banco = Banco(tmp_path / "b.db")
    banco.definir("nome", "Cardápio Fácil")
    banco.definir("iniciada", True)
    assert banco.empresa() == {"nome": "Cardápio Fácil", "iniciada": True}
    assert banco.obter("ausente", 7) == 7


def test_cofre_cifra_em_disco_e_recupera(tmp_path):
    cofre = Cofre(tmp_path)
    cofre.salvar_credencial("GitHub", "empresa@exemplo.com", "S3nh4-Muit0-Secreta!", notas="plano gratuito")
    bruto = (tmp_path / "cofre.bin").read_bytes()
    assert b"S3nh4-Muit0-Secreta!" not in bruto and b"empresa@exemplo.com" not in bruto
    reaberto = Cofre(tmp_path)
    assert reaberto.obter_credencial("github")["senha"] == "S3nh4-Muit0-Secreta!"
    assert reaberto.listar()[0] == {
        "servico": "github",
        "usuario": "empresa@exemplo.com",
        "url": "",
        "notas": "plano gratuito",
        "origem": "agente",
        "atualizado_em": reaberto.listar()[0]["atualizado_em"],
    }
    assert "senha" not in reaberto.listar()[0]


def test_cofre_recusa_chave_errada(tmp_path):
    Cofre(tmp_path, senha_mestra="correta").salvar_credencial("x", "u", "segredo-123")
    with pytest.raises(ErroCofre):
        Cofre(tmp_path, senha_mestra="errada")
    assert Cofre(tmp_path, senha_mestra="correta").obter_credencial("x")["senha"] == "segredo-123"


def test_cartao_valida_e_expoe_campos(tmp_path):
    cofre = Cofre(tmp_path)
    with pytest.raises(ErroCofre):
        cofre.definir_cartao("123", "12/30", "123", "Fulano", 100)
    with pytest.raises(ErroCofre):
        cofre.definir_cartao("4111 1111 1111 1111", "12/30", "123", "Fulano", 0)
    cofre.definir_cartao("4111 1111 1111 1111", "07/2031", "123", "Fulano de Tal", 150)
    assert cofre.resumo_cartao() == {"configurado": True, "final": "1111", "titular": "Fulano de Tal", "limite_mensal": 150.0}
    campos = cofre.campos_cartao()
    assert (campos["mes"], campos["ano"], campos["ano_curto"]) == ("07", "2031", "31")
    assert cofre.remover_cartao() and cofre.resumo_cartao() == {"configurado": False}


def test_registro_mascara_segredos(tmp_path):
    banco = Banco(tmp_path / "b.db")
    cofre = Cofre(tmp_path)
    registro = Registro(banco, imprimir=False)
    registro.adicionar_fonte_de_segredos(cofre.segredos)
    cofre.salvar_credencial("servico", "usuario", "Minha-Senha-Forte-9")
    cofre.definir_cartao("4111111111111111", "12/30", "123", "Fulano", 100)
    nova = gerar_senha()
    cofre.lembrar_segredo_temporario(nova)
    registro.evento("ferramenta", "digitando Minha-Senha-Forte-9", f"cartão 4111 1111 1111 1111 e 4111111111111111, senha nova {nova}")
    evento = banco.eventos_recentes(1)[0]
    assert "Minha-Senha-Forte-9" not in evento["titulo"]
    assert "4111" not in evento["detalhe"] and nova not in evento["detalhe"]


def test_senha_gerada_tem_todas_as_classes():
    senha = gerar_senha(24)
    assert len(senha) == 24
    assert any(c.islower() for c in senha) and any(c.isupper() for c in senha) and any(c.isdigit() for c in senha)

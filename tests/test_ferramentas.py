import subprocess
import sys
import time

import pytest

from empresa_auto.ferramentas.habilidades import ler_cabecalho
from empresa_auto.ferramentas.sistema import comando_proibido
from empresa_auto.ferramentas.web import html_para_texto


def test_catalogo_conserta_tipos_e_valida_obrigatorios(agente):
    cat = agente.catalogo
    assert "faltam os parâmetros obrigatórios: conteudo" in cat.executar("memoria_salvar", {"titulo": "x"})
    assert "não existe" in cat.executar("inexistente", {})
    # prioridade veio como texto e um parâmetro desconhecido foi enviado: ambos são tolerados
    saida = cat.executar(
        "tarefa_criar",
        {"titulo": "Testar coerção", "descricao": "d", "area": "engenharia", "prioridade": "2", "extra": 1},
    )
    assert "criada" in saida
    assert agente.banco.proxima_tarefa()["prioridade"] == 2


def test_arquivos_ficam_confinados_a_pasta_de_trabalho(agente):
    cat = agente.catalogo
    assert "gravado" in cat.executar("escrever_arquivo", {"caminho": "site/index.html", "conteudo": "<h1>Olá</h1>\nlinha 2"})
    assert (agente.cfg.dir_trabalho / "site" / "index.html").read_text(encoding="utf-8").startswith("<h1>Olá</h1>")
    assert "ERRO" in cat.executar("escrever_arquivo", {"caminho": "../fora.txt", "conteudo": "x"})
    assert "ERRO" in cat.executar("ler_arquivo", {"caminho": "/etc/passwd"})
    assert "    2  linha 2" in cat.executar("ler_arquivo", {"caminho": "site/index.html"})
    assert "editado" in cat.executar(
        "editar_arquivo", {"caminho": "site/index.html", "trecho_antigo": "Olá", "trecho_novo": "Bem-vindo"}
    )
    assert "não foi encontrado" in cat.executar(
        "editar_arquivo", {"caminho": "site/index.html", "trecho_antigo": "inexistente", "trecho_novo": "y"}
    )
    listagem = cat.executar("listar_arquivos", {})
    assert "site/" in listagem and "index.html" in listagem


def test_terminal_executa_e_respeita_tempo_limite(agente):
    cat = agente.catalogo
    saida = cat.executar("executar_comando", {"comando": f'"{sys.executable}" -c "print(6*7)"'})
    assert "código de saída: 0" in saida and "42" in saida
    inicio = time.time()
    saida = cat.executar(
        "executar_comando", {"comando": f'"{sys.executable}" -c "import time; time.sleep(60)"', "tempo_limite": 5}
    )
    assert "TEMPO ESGOTADO" in saida and time.time() - inicio < 30


@pytest.mark.parametrize(
    "comando,proibido",
    [
        ("rm -rf /", True),
        ("sudo rm -rf / --no-preserve-root", True),
        ("rm -rf ~", True),
        ("mkfs.ext4 /dev/sda1", True),
        ("dd if=/dev/zero of=/dev/sda bs=1M", True),
        ("shutdown -h now", True),
        ("rm -rf ./build", False),
        ("rm -rf node_modules && npm install", False),
        ("git status", False),
    ],
)
def test_barreira_de_comandos_destrutivos(comando, proibido):
    assert comando_proibido(comando) is proibido


def test_html_vira_texto_legivel():
    titulo, texto = html_para_texto(
        "<html><head><title>Loja</title><style>p{}</style></head><body><script>x()</script>"
        "<h1>Planos</h1><p>Grátis &amp; simples</p><a href='https://exemplo.com/a'>Saiba mais</a></body></html>"
    )
    assert titulo == "Loja"
    assert "# Planos" in texto and "Grátis & simples" in texto and "Saiba mais (https://exemplo.com/a)" in texto
    assert "x()" not in texto and "p{}" not in texto


def test_cabecalho_de_habilidade():
    campos, corpo = ler_cabecalho("---\nname: minha-skill\ndescription: >\n  Faz uma coisa\n  muito útil.\n---\n\n# Corpo\n")
    assert campos == {"name": "minha-skill", "description": "Faz uma coisa muito útil."}
    assert corpo.startswith("# Corpo")
    assert ler_cabecalho("sem cabeçalho") == ({}, "sem cabeçalho")


def test_habilidades_embutidas_criadas_e_instaladas(agente, tmp_path):
    hab = agente.amb.habilidades
    nomes = [h["nome"] for h in hab.listar()]
    assert {"pesquisa-de-mercado", "publicacao-gratuita", "contas-e-credenciais", "expandir-capacidades"} <= set(nomes)
    assert all(h["descricao"] for h in hab.listar())
    assert "Pesquisa de mercado" in hab.ler("pesquisa-de-mercado")
    assert "não encontrada" in hab.ler("nao-existe")
    assert "não encontrado" in hab.ler("pesquisa-de-mercado", "../../config.py")

    assert "criada" in hab.criar("Publicar no Pages", "Passo a passo de publicação.", "1. git push")
    assert "1. git push" in hab.ler("publicar-no-pages")

    # instalação a partir de um repositório git local
    repo = tmp_path / "repo"
    (repo / "skills" / "planilhas").mkdir(parents=True)
    (repo / "skills" / "planilhas" / "SKILL.md").write_text(
        "---\nname: planilhas\ndescription: Gera planilhas.\n---\nUse a biblioteca.\n", encoding="utf-8"
    )
    (repo / "skills" / "planilhas" / "exemplo.py").write_text("print('oi')\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], check=True
    )
    saida = agente.catalogo.executar("habilidade_instalar", {"origem": f"file://{repo}"})
    assert "planilhas" in saida
    lido = hab.ler("planilhas")
    assert "Use a biblioteca." in lido and "exemplo.py" in lido
    assert "print('oi')" in hab.ler("planilhas", "exemplo.py")
    assert "removida" in hab.remover("planilhas")
    assert "só é possível remover" in hab.remover("pesquisa-de-mercado")


def test_cartao_so_com_cadastro_e_dentro_do_limite(agente):
    cat, amb = agente.catalogo, agente.amb
    from empresa_auto.ferramentas.pagamento import resolver_marcadores

    assert "NEGADO" in cat.executar("cartao_autorizar", {"motivo": "domínio", "valor": 50})
    assert "não há ferramentas de pagamento" in cat.executar("ativar_ferramentas", {"grupo": "pagamento"})

    agente.cofre.definir_cartao("4111111111111111", "08/29", "321", "Dona da Empresa", 100)
    assert resolver_marcadores(amb, "{{cartao:numero}}") == "{{cartao:numero}}"  # sem autorização, nada é revelado
    assert "ultrapassa" in cat.executar("cartao_autorizar", {"motivo": "servidor", "valor": 150})
    saida = cat.executar("cartao_autorizar", {"motivo": "domínio da empresa", "valor": 60})
    assert "AUTORIZADO" in saida and "4111" not in saida and "321" not in saida
    assert resolver_marcadores(amb, "{{cartao:numero}} {{ cartao:cvv }} {{cartao:mes}}/{{cartao:ano_curto}}") == "4111111111111111 321 08/29"
    assert "ultrapassa" in cat.executar("cartao_autorizar", {"motivo": "outro", "valor": 60})  # 60 + 60 > 100
    assert agente.estado()["cartao"]["gasto_mes"] == 60
    eventos = [e for e in agente.banco.eventos_recentes(20) if e["tipo"] == "pagamento"]
    assert eventos and "R$ 60.00" in eventos[-1]["titulo"]


def test_credenciais_e_limite_de_emails(agente):
    cat = agente.catalogo
    senha = cat.executar("senha_gerar", {}).split(": ", 1)[1]
    assert "guardada" in cat.executar("credencial_salvar", {"servico": "GitHub", "usuario": "empresa", "senha": senha})
    assert senha in cat.executar("credencial_obter", {"servico": "github"})
    assert "github: empresa" in cat.executar("credencial_listar", {})
    assert senha not in cat.executar("credencial_listar", {})
    assert "nenhum e-mail configurado" in cat.executar("email_enviar", {"para": "a@b.c", "assunto": "s", "corpo": "c"})

    cat.executar(
        "email_configurar",
        {"endereco": "contato@empresa.test", "senha": "x-senha-de-app", "smtp_host": "127.0.0.1", "imap_host": "127.0.0.1"},
    )
    for _ in range(agente.cfg.limite_emails_hora):
        agente.banco.registrar_envio("email", "cliente@exemplo.com")
    assert "limite de e-mails por hora" in cat.executar("email_enviar", {"para": "a@b.c", "assunto": "s", "corpo": "c"})


def test_supervisor_sobe_religa_e_para_servico(agente):
    cat, sup = agente.catalogo, agente.amb.supervisor
    comando = f'"{sys.executable}" -c "import time; print(\'no ar\', flush=True); time.sleep(120)"'
    assert "em execução" in cat.executar("servico_iniciar", {"nome": "API Teste", "comando": comando})
    estado = sup.estado()
    assert estado[0]["nome"] == "api-teste" and estado[0]["rodando"]
    assert "no ar" in cat.executar("servico_logs", {"nome": "api-teste"})

    pid_antigo = estado[0]["pid"]
    sup._processos["api-teste"].kill()
    sup._processos["api-teste"].wait()
    assert not sup.estado()[0]["rodando"]
    sup.vigiar()
    novo = sup.estado()[0]
    assert novo["rodando"] and novo["pid"] != pid_antigo

    assert "parado" in cat.executar("servico_parar", {"nome": "api-teste"})
    assert not sup.estado()[0]["rodando"] and not sup.estado()[0]["ativo"]
    falha = cat.executar("servico_iniciar", {"nome": "quebrado", "comando": f'"{sys.executable}" -c "raise SystemExit(3)"'})
    assert "encerrou logo ao iniciar" in falha


def test_automacoes_pela_ferramenta(agente):
    cat = agente.catalogo
    assert "a cada 2 horas" in cat.executar(
        "automacao_criar", {"titulo": "Ler e-mails", "descricao": "ler e responder", "intervalo_minutos": 120}
    )
    assert "Já existe" in cat.executar(
        "automacao_criar", {"titulo": "ler e-mails", "descricao": "x", "intervalo_minutos": 60}
    )
    assert "Ler e-mails" in cat.executar("automacao_listar", {})
    automacao = agente.banco.automacoes()[0]
    agente.banco._executar("UPDATE automacoes SET proxima = 0 WHERE id = ?", (automacao["id"],))
    agente._disparar_automacoes()
    agente._disparar_automacoes()  # não duplica enquanto a tarefa anterior estiver aberta
    abertas = [t for t in agente.banco.tarefas_abertas() if t["titulo"] == "Ler e-mails"]
    assert len(abertas) == 1 and abertas[0]["origem"] == f"automacao:{automacao['id']}"

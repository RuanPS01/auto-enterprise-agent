"""Habilidades por relevância, catálogo curado e provisionamento do pacote padrão."""

import json
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest

from conftest import LLMRoteirizado, chamar
from empresa_auto import provisionamento
from empresa_auto.agente import Agente
from empresa_auto.ferramentas import extensoes as modulo_extensoes
from empresa_auto.ferramentas import habilidades as modulo_habilidades
from empresa_auto.ferramentas.habilidades import DIR_EMBUTIDAS, ler_cabecalho, radicais
from empresa_auto.ferramentas.sistema import inspecionar_ambiente

AREAS_VALIDAS = {
    "pesquisa", "gestao", "programacao", "infraestrutura", "operacao", "atendimento", "marketing", "social",
    "midia", "seguranca", "web", "dados", "privacidade",
}


# ---------------------------------------------------------------------- habilidades embutidas
def test_habilidades_embutidas_sao_validas_e_seguem_o_estilo_do_dono():
    pastas = sorted(p for p in DIR_EMBUTIDAS.iterdir() if p.is_dir())
    assert len(pastas) >= 21
    for pasta in pastas:
        texto = (pasta / "SKILL.md").read_text(encoding="utf-8")
        campos, corpo = ler_cabecalho(texto)
        assert campos.get("name") == pasta.name, pasta.name
        assert len(campos.get("description", "")) > 60, pasta.name
        assert campos.get("area") in AREAS_VALIDAS, pasta.name
        assert len(corpo) > 800, pasta.name
        assert not re.search("[—–→⇒➜]|[\U0001F300-\U0001FAFF]", texto), f"{pasta.name}: travessão, seta ou emoji"


@pytest.mark.parametrize(
    "consulta,esperada",
    [
        ("ffmpeg cortar e legendar vídeo vertical", "video-e-motion"),
        ("narração com voz sintética e transcrição whisper", "criacao-sonora"),
        ("baixar legendas com yt-dlp", "baixar-midia-com-yt-dlp"),
        ("política de privacidade lgpd", "privacidade-e-termos"),
        ("docker backup monitoramento servidor", "infraestrutura-e-servidores"),
        ("calendário editorial redes sociais influenciador", "influenciador-e-redes-sociais"),
        ("vulnerabilidades dependências segredos", "seguranca-defensiva"),
        ("capa miniatura imagem svg", "edicao-de-imagens"),
        ("priorização roteiro tarefas projeto", "gestao-de-projetos"),
        ("planilha csv gráfico relatório pdf", "documentos-e-dados"),
        ("raspagem sitemap rss api", "acesso-avancado-a-web"),
    ],
)
def test_busca_encontra_a_habilidade_certa(agente, consulta, esperada):
    primeira = agente.catalogo.executar("habilidade_buscar", {"consulta": consulta}).splitlines()[0]
    assert primeira.startswith(f"- {esperada} "), primeira


def test_contexto_mostra_so_as_habilidades_relevantes_para_a_tarefa(agente):
    hab = agente.amb.habilidades
    resumo = hab.catalogo_resumido("Produzir vídeo curto com legenda para divulgar o produto nas redes sociais", "marketing")
    linhas = resumo.splitlines()
    assert len(linhas) <= 11 and linhas[-1].startswith("(há mais ")  # lista curta, com aviso de que há mais
    nomes = [l.split(":")[0][2:] for l in linhas[:-1]]
    assert {"video-e-motion", "influenciador-e-redes-sociais"} <= set(nomes[:5])
    assert "seguranca-defensiva" not in nomes

    # tarefa sem palavras em comum: cai nas habilidades da área
    generico = hab.catalogo_resumido("xyz", "engenharia")
    assert "construcao-de-software" in generico and "(há mais " in generico
    assert agente.catalogo.executar("habilidade_buscar", {"consulta": "qwertyuiop"}).startswith("Nenhuma habilidade instalada combina")

    # a lista chega ao modelo dentro do prompt de sistema da tarefa
    agente.llm.roteiro = [chamar("concluir_tarefa", resultado="ok")]
    tid = agente.banco.criar_tarefa("Publicar o site com Docker e HTTPS", "subir o contêiner e o proxy", "engenharia")
    tarefa = agente.banco.tarefa(tid)
    tarefa["tentativas"] = 1
    agente.executor.executar(tarefa)
    sistema = agente.llm.historico[0][0][0]["content"]
    assert "HABILIDADES MAIS RELEVANTES PARA ESTA TAREFA" in sistema and "- infraestrutura-e-servidores:" in sistema
    assert "programas instalados:" in sistema and "python do agente" in sistema and "placa de vídeo:" in sistema
    assert sistema.count("\n- ") < 40  # o prompt não despeja todas as habilidades


def test_radicais_ignoram_acentos_e_palavras_vazias():
    assert radicais("Publicação de vídeos para as redes sociais") == {"publi", "video", "redes", "socia"}


def test_inspecao_do_ambiente():
    dados = inspecionar_ambiente(validade=0)
    assert "git" in dados["programas"] and isinstance(dados["pode_instalar_pacotes"], bool) and isinstance(dados["placa_de_video"], str)


# ---------------------------------------------------------------------- catálogo curado de habilidades
def test_catalogo_real_de_habilidades_e_valido():
    catalogo = json.loads(Path(modulo_habilidades.ARQUIVO_CATALOGO).read_text(encoding="utf-8"))
    assert catalogo["versao"] >= 1 and len(catalogo["fontes"]) >= 11
    nomes = []
    for fonte in catalogo["fontes"]:
        assert fonte["origem"].startswith("https://github.com/") and fonte["ramo"] and fonte["licenca"]
        for item in fonte["itens"]:
            assert item["area"] in AREAS_VALIDAS and len(item["descricao"]) > 25 and not item["pasta"].startswith("/")
            nomes.append(item["pasta"].rsplit("/", 1)[-1])
    assert len(nomes) == len(set(nomes)), "duas habilidades do catálogo teriam o mesmo nome"
    embutidas = {p.name for p in DIR_EMBUTIDAS.iterdir()}
    assert not embutidas & set(nomes), "habilidade da comunidade sobrescreveria uma embutida"
    assert {"hyperframes", "remotion-best-practices", "higgsfield-generate", "lgpd-audit", "systematic-debugging", "social"} <= set(nomes)


@pytest.fixture
def repositorio(tmp_path):
    """Repositório git local que imita uma coleção de habilidades da comunidade."""
    raiz = tmp_path / "colecao"
    for pasta, corpo in (
        ("skills/debugging", "---\nname: debugging\ndescription: Use when encountering any bug.\n---\n# Debugging\nUse the Bash tool and TodoWrite.\n"),
        ("skills/video-kit", "---\nname: video-kit\ndescription: |\n  Make videos from HTML.\n---\n# Video\nRun scripts/render.sh\n"),
        ("skills/nao-pedida", "---\nname: nao-pedida\ndescription: Extra.\n---\ncorpo\n"),
    ):
        (raiz / pasta).mkdir(parents=True)
        (raiz / pasta / "SKILL.md").write_text(corpo, encoding="utf-8")
    (raiz / "skills/video-kit/scripts").mkdir()
    (raiz / "skills/video-kit/scripts/render.sh").write_text("echo render\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(raiz)], check=True)
    subprocess.run(["git", "-C", str(raiz), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(raiz), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], check=True)
    return raiz


def catalogos_de_teste(monkeypatch, repositorio, pastas_extras=()):
    fonte = {
        "origem": f"file://{repositorio}", "ramo": "main", "licenca": "MIT",
        "itens": [
            {"pasta": "skills/debugging", "area": "programacao", "descricao": "Depuração sistemática: achar a causa raiz de um erro antes de corrigir."},
            {"pasta": "skills/video-kit", "area": "midia", "descricao": "Criar vídeos a partir de HTML."},
            *[{"pasta": p, "area": "midia", "descricao": "Pasta que não existe no repositório."} for p in pastas_extras],
        ],
    }
    extensoes = [
        {"nome": "docs", "area": "programacao", "tipo": "stdio", "comando": "python3", "args": ["-c", "pass"], "padrao": True, "descricao": "Documentação."},
        {"nome": "com-token", "area": "gestao", "tipo": "http", "url": "https://x.test/mcp", "cabecalhos": {"Authorization": "Bearer {segredo}"},
         "padrao": True, "credencial": {"servico": "x-token", "como_obter": "painel"}, "descricao": "Exige token."},
    ]
    monkeypatch.setattr(provisionamento, "catalogo_de_habilidades", lambda: {"versao": 7, "fontes": [fonte]})
    monkeypatch.setattr(provisionamento, "catalogo_de_extensoes", lambda: extensoes)
    monkeypatch.setattr(modulo_extensoes, "carregar_catalogo", lambda: extensoes)
    return fonte


def test_provisionamento_instala_o_pacote_uma_vez(agente, monkeypatch, repositorio):
    catalogos_de_teste(monkeypatch, repositorio)
    agente.cfg.pacote_padrao = True
    assert provisionamento.pendente(agente.amb)
    resultado = provisionamento.provisionar(agente.amb)
    assert resultado == {"novas": ["debugging", "video-kit"], "extensoes": ["docs"], "erros": [], "completo": True}

    hab = agente.amb.habilidades
    instalada = next(h for h in hab.listar() if h["nome"] == "debugging")
    assert instalada["descricao"].startswith("Depuração sistemática") and instalada["area"] == "programacao"  # descrição em português do catálogo
    assert instalada["licenca"] == "MIT" and instalada["origem"] == "instalada"
    assert not (agente.cfg.dir_habilidades / "nao-pedida").exists()  # só o que o catálogo lista
    lida = hab.ler("debugging")
    assert "NOTA: esta habilidade veio da comunidade" in lida and "Bash ou terminal = executar_comando" in lida and "# Debugging" in lida
    assert "echo render" in hab.ler("video-kit", "scripts/render.sh")
    assert "NOTA: esta habilidade veio da comunidade" not in hab.ler("pesquisa-de-mercado")  # embutidas não levam a nota
    assert agente.catalogo.executar("habilidade_buscar", {"consulta": "erro causa raiz depuração"}).startswith("- debugging ")

    # extensão sem credencial fica registrada sem iniciar; a que exige token espera o cofre
    assert agente.amb.extensoes._clientes == {} and "ext_docs" in agente.catalogo.grupos() and "ext_com_token" not in agente.catalogo.grupos()

    # segunda chamada não refaz nada
    assert not provisionamento.pendente(agente.amb)
    eventos = [e["titulo"] for e in agente.banco.eventos_recentes(50)]
    assert "Pacote padrão: 2 habilidades da comunidade instaladas" in eventos
    assert provisionamento.provisionar(agente.amb)["novas"] == []


def test_provisionamento_desligado_ou_sem_rede_nao_atrapalha(agente, monkeypatch, repositorio, tmp_path):
    catalogos_de_teste(monkeypatch, repositorio)
    assert not provisionamento.pendente(agente.amb)  # pacote_padrao = False no ambiente de teste

    agente.cfg.pacote_padrao = True
    fonte_ruim = {"origem": f"file://{tmp_path}/nao-existe", "ramo": "main", "licenca": "MIT", "itens": [{"pasta": "a", "area": "midia", "descricao": "x" * 30}]}
    monkeypatch.setattr(provisionamento, "catalogo_de_habilidades", lambda: {"versao": 7, "fontes": [fonte_ruim]})
    resultado = provisionamento.provisionar(agente.amb)
    assert resultado["novas"] == [] and not resultado["completo"] and "falha ao clonar" in resultado["erros"][0]
    assert not provisionamento.pendente(agente.amb)  # acabou de tentar: espera algumas horas
    estado = provisionamento.situacao(agente.amb)
    estado["ultima_tentativa"] = time.time() - provisionamento.INTERVALO_NOVA_TENTATIVA - 1
    agente.banco.definir(provisionamento.CHAVE_ESTADO, estado)
    assert provisionamento.pendente(agente.amb)  # e depois tenta de novo
    avisos = [e for e in agente.banco.eventos_recentes(20) if e["nivel"] == "aviso"]
    assert avisos and "nova tentativa" in avisos[-1]["titulo"]


def test_pasta_ausente_no_repositorio_e_relatada_sem_perder_as_demais(agente, monkeypatch, repositorio):
    catalogos_de_teste(monkeypatch, repositorio, pastas_extras=("skills/sumiu",))
    agente.cfg.pacote_padrao = True
    resultado = provisionamento.provisionar(agente.amb)
    assert resultado["novas"] == ["debugging", "video-kit"] and "skills/sumiu" in resultado["erros"][0]


def test_agente_provisiona_na_partida(cfg, monkeypatch, repositorio):
    catalogos_de_teste(monkeypatch, repositorio)
    cfg.pacote_padrao = True
    agente = Agente(cfg, llm=LLMRoteirizado(), imprimir=False)
    fio = threading.Thread(target=agente.rodar, daemon=True)
    fio.start()
    fim = time.time() + 20
    while time.time() < fim and not provisionamento.situacao(agente.amb).get("completo"):
        time.sleep(0.05)
    agente.parar()
    fio.join(timeout=15)
    assert provisionamento.situacao(agente.amb)["completo"]
    estado = agente.estado()
    assert {"debugging", "video-kit"} <= {h["nome"] for h in estado["habilidades"]}
    assert estado["extensoes"][0]["nome"] == "docs" and "programas" in estado["maquina"]

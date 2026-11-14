"""Testes do navegador real (Chromium) contra um site local."""

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

PAGINA = """<!doctype html><html><head><title>Cadastro de teste</title></head><body>
<h1>Crie sua conta</h1>
<a href="/sobre">Sobre a empresa</a>
<form action="/enviado" method="get">
  <label for="email">E-mail</label><input id="email" name="email" type="email">
  <input name="senha" type="password" placeholder="Senha">
  <input name="cardnumber" autocomplete="cc-number" placeholder="Número do cartão">
  <label>Plano <select name="plano"><option>Gratuito</option><option>Profissional</option></select></label>
  <label><input type="checkbox" name="termos"> Aceito os termos</label>
  <input type="hidden" name="oculto" value="1">
  <button type="submit">Criar conta</button>
</form>
<button style="display:none">Invisível</button>
</body></html>"""

CAPTCHA = """<!doctype html><html><head><title>Verificação</title></head><body>
<p>Confirme que você não é um robô</p><div class="g-recaptcha"></div><button>Continuar</button></body></html>"""


class Manipulador(BaseHTTPRequestHandler):
    def do_GET(self):
        rota = urlparse(self.path)
        if rota.path == "/enviado":
            dados = parse_qs(rota.query)
            corpo = "<html><head><title>Conta criada</title></head><body><h1>Bem-vindo</h1><pre>" + "\n".join(
                f"{chave}={valores[0]}" for chave, valores in sorted(dados.items())
            ) + "</pre></body></html>"
        elif rota.path == "/captcha":
            corpo = CAPTCHA
        elif rota.path == "/sobre":
            corpo = "<html><head><title>Sobre</title></head><body><p>Somos uma empresa de teste.</p></body></html>"
        else:
            corpo = PAGINA
        dados = corpo.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manipulador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.shutdown()


def indice(pagina: str, trecho: str) -> int:
    encontrado = re.search(r"\[(\d+)\] [^\n]*" + re.escape(trecho), pagina)
    assert encontrado, f"elemento com '{trecho}' não apareceu em:\n{pagina}"
    return int(encontrado.group(1))


def test_fluxo_de_cadastro_no_navegador(agente, site):
    cat = agente.catalogo
    pagina = cat.executar("navegador_abrir", {"url": site})
    if pagina.startswith("ERRO") and "Executable doesn't exist" in pagina:
        pytest.skip("Chromium do Playwright não está instalado neste ambiente")
    assert "Título: Cadastro de teste" in pagina and "Crie sua conta" in pagina
    assert 'link "Sobre a empresa"' in pagina and 'campo email "E-mail"' in pagina
    assert 'campo password "Senha"' in pagina and 'botão "Criar conta"' in pagina
    assert "seleção" in pagina and "Gratuito | Profissional" in pagina
    assert "Invisível" not in pagina and "oculto" not in pagina  # elementos escondidos não são listados
    assert (agente.cfg.dir_capturas / "atual.png").stat().st_size > 1000  # imagem para o painel

    assert "digitado" in cat.executar("navegador_digitar", {"indice": indice(pagina, '"E-mail"'), "texto": "contato@empresa.test"})
    cat.executar("navegador_digitar", {"indice": indice(pagina, '"Senha"'), "texto": "Senha-Forte-123"})
    assert "selecionada" in cat.executar("navegador_selecionar", {"indice": indice(pagina, "seleção"), "opcao": "Profissional"})
    cat.executar("navegador_clicar", {"indice": indice(pagina, "checkbox")})

    relida = cat.executar("navegador_ler", {})
    assert 'valor: "contato@empresa.test"' in relida
    assert "Senha-Forte-123" not in relida and 'valor: "(preenchido)"' in relida  # senha nunca é ecoada
    assert "atual: Profissional" in relida and "marcado" in relida

    resultado = cat.executar("navegador_clicar", {"indice": indice(relida, '"Criar conta"')})
    assert "Título: Conta criada" in resultado
    assert "email=contato@empresa.test" in resultado and "plano=Profissional" in resultado and "termos=on" in resultado

    voltou = cat.executar("navegador_voltar", {})
    assert "Título: Cadastro de teste" in voltou
    sobre = cat.executar("navegador_clicar", {"indice": indice(voltou, '"Sobre a empresa"')})
    assert "Somos uma empresa de teste." in sobre
    assert "não existe na página atual" in cat.executar("navegador_clicar", {"indice": 99})


def test_marcadores_de_cartao_so_valem_com_autorizacao(agente, site):
    cat = agente.catalogo
    pagina = cat.executar("navegador_abrir", {"url": site})
    if pagina.startswith("ERRO"):
        pytest.skip("navegador indisponível neste ambiente")
    campo = indice(pagina, '"Número do cartão"')
    agente.cofre.definir_cartao("4111111111111111", "09/30", "987", "Dona", 200)

    cat.executar("navegador_digitar", {"indice": campo, "texto": "{{cartao:numero}}"})
    valor = agente.amb.navegador._pagina.locator('[name="cardnumber"]').input_value()
    assert valor == "{{cartao:numero}}"  # sem autorização o marcador não é trocado

    assert "AUTORIZADO" in cat.executar("cartao_autorizar", {"motivo": "domínio", "valor": 40})
    cat.executar("navegador_digitar", {"indice": campo, "texto": "{{cartao:numero}}"})
    assert agente.amb.navegador._pagina.locator('[name="cardnumber"]').input_value() == "4111111111111111"
    relida = cat.executar("navegador_ler", {})
    assert "4111" not in relida  # o número não volta para o modelo nem para o registro


def test_pagina_com_captcha_gera_aviso(agente, site):
    pagina = agente.catalogo.executar("navegador_abrir", {"url": f"{site}/captcha"})
    if pagina.startswith("ERRO"):
        pytest.skip("navegador indisponível neste ambiente")
    assert "AVISO: esta página exige uma verificação humana" in pagina and "Não tente burlar" in pagina

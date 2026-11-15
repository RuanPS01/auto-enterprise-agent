"""Servidor que imita a API do Ollama com um "modelo" roteirizado.

Serve para testar o agente de ponta a ponta (linha de comando, laço, painel)
sem GPU e sem baixar um modelo de verdade:

    python tests/apoio/ollama_simulado.py 11500
    python -m empresa_auto --dados /tmp/demo --url-llm http://127.0.0.1:11500

O "modelo" não pensa: ele segue um roteiro fixo de chamadas de ferramenta.
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ATRASO = 0.6
PORTA = 11500
contador = {"planos": 0, "tarefas": 0}

PAGINA_MERCADO = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Fórum de donos de barbearia</title>
<style>body{font-family:system-ui;margin:40px;max-width:720px}h1{font-size:26px}.post{border:1px solid #ddd;border-radius:8px;padding:14px;margin:12px 0}</style>
</head><body><h1>Fórum de donos de barbearia</h1>
<div class="post"><b>Perco clientes por causa da agenda no papel</b><p>Alguém conhece um sistema de agendamento simples e gratuito? Os que testei são caros.</p></div>
<div class="post"><b>Clientes faltam e não avisam</b><p>Queria mandar lembrete automático um dia antes do horário.</p></div>
<a href="/mercado?pagina=2">Próxima página</a></body></html>"""


def chamada(nome: str, **argumentos) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": nome, "arguments": argumentos}}]}


def decidir(corpo: dict) -> dict:
    mensagens = corpo.get("messages", [])
    ferramentas = {f["function"]["name"] for f in corpo.get("tools", [])}
    if not ferramentas:
        return {
            "role": "assistant",
            "content": (
                "A semana foi dedicada a entender o mercado e a definir o negócio. O agente pesquisou concorrentes, "
                "registrou as evidências de demanda e escolheu o primeiro produto.\n\n"
                "Não houve impedimentos relevantes. Um cadastro exigiu verificação humana e foi contornado com um "
                "serviço equivalente.\n\n"
                "Os próximos passos são construir a primeira versão do produto e publicá-la em hospedagem gratuita."
            ),
        }
    pedido = mensagens[1]["content"] if len(mensagens) > 1 else ""
    passo = sum(1 for m in mensagens if m["role"] == "tool")
    base = f"http://127.0.0.1:{PORTA}"

    if "CICLO DE PLANEJAMENTO" in pedido:
        if passo == 0:
            contador["planos"] += 1
            return chamada(
                "decisao_registrar",
                titulo=f"Prioridade do ciclo {contador['planos']}: colocar a agenda online no ar",
                justificativa="A pesquisa mostrou demanda por agendamento simples e gratuito.",
            )
        if passo in (1, 2):
            contador["tarefas"] += 1
            titulos = [
                "Criar a página de agendamento com horários disponíveis",
                "Implementar o lembrete automático por e-mail",
                "Publicar o site em hospedagem gratuita",
                "Escrever a página de ajuda e a política de privacidade",
                "Medir visitas e cadastros da primeira semana",
                "Divulgar o produto em comunidades de barbeiros",
            ]
            titulo = titulos[(contador["tarefas"] - 1) % len(titulos)]
            if contador["tarefas"] > len(titulos):
                titulo += f" (rodada {contador['tarefas'] // len(titulos) + 1})"
            return chamada(
                "tarefa_criar",
                titulo=titulo,
                descricao="Implementar em passos pequenos, testar e registrar o resultado na memória.",
                area=["engenharia", "marketing", "operacoes"][contador["tarefas"] % 3],
                prioridade=2,
            )
        return chamada("concluir_tarefa", resultado="Plano definido: duas novas tarefas na fila.")

    if "Título: Definir a empresa" in pedido or "Título: Escolher o negócio" in pedido:
        etapas = [
            ("empresa_atualizar", {"campo": "nome", "valor": "Agenda Navalha"}),
            ("empresa_atualizar", {"campo": "proposta_de_valor", "valor": "Ajudamos barbearias de bairro a lotar a agenda sem telefone nem papel."}),
            ("empresa_atualizar", {"campo": "publico_alvo", "valor": "Barbearias pequenas com um a três profissionais."}),
            ("empresa_atualizar", {"campo": "produto", "valor": "Página de agendamento online com lembrete automático."}),
            ("empresa_atualizar", {"campo": "modelo_de_receita", "valor": "Plano gratuito com limite de agendamentos e plano pago ilimitado."}),
            ("decisao_registrar", {"titulo": "Negócio escolhido: agenda online para barbearias", "justificativa": "Demanda comprovada em fóruns e concorrentes caros."}),
            ("empresa_atualizar", {"campo": "fase", "valor": "construcao"}),
        ]
        if passo < len(etapas):
            nome, argumentos = etapas[passo]
            return chamada(nome, **argumentos)
        return chamada("concluir_tarefa", resultado="Empresa definida: Agenda Navalha, agenda online para barbearias.")

    roteiro = [
        ("memoria_buscar", {"consulta": "barbearias agenda concorrentes"}),
        ("navegador_abrir", {"url": f"{base}/mercado"}) if "navegador_abrir" in ferramentas else ("escrever_arquivo", {"caminho": "agenda/index.html", "conteudo": "<h1>Agenda Navalha</h1>\n<p>Agende seu horário.</p>\n"}),
        ("executar_comando", {"comando": "echo verificado"}),
        ("memoria_salvar", {"titulo": f"Achados do passo {passo}", "conteudo": "Donos de barbearia reclamam de agenda no papel e de faltas sem aviso. Fonte: fórum local.", "categoria": "mercado"}),
    ]
    if passo < len(roteiro):
        nome, argumentos = roteiro[passo]
        return chamada(nome, **argumentos)
    return chamada("concluir_tarefa", resultado="Trabalho concluído e verificado. Os achados foram salvos na memória.", sucesso=True)


class Manipulador(BaseHTTPRequestHandler):
    def _responder(self, dados: bytes, tipo: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self) -> None:
        if self.path.startswith("/api/tags"):
            self._responder(json.dumps({"models": [{"name": "qwen3:8b"}]}).encode())
        elif self.path.startswith("/mercado"):
            self._responder(PAGINA_MERCADO.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._responder(b'{"version": "simulado"}')

    def do_POST(self) -> None:
        corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        time.sleep(ATRASO)
        self._responder(json.dumps({"model": corpo.get("model"), "message": decidir(corpo), "done": True}).encode())

    def log_message(self, *args) -> None:
        pass


def criar_servidor(porta: int = 0, atraso: float = 0.0) -> ThreadingHTTPServer:
    """Cria o servidor (porta 0 escolhe uma livre). Quem chama decide como executá-lo."""
    global PORTA, ATRASO
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Manipulador)
    PORTA, ATRASO = servidor.server_address[1], atraso
    contador.update(planos=0, tarefas=0)
    return servidor


if __name__ == "__main__":
    servidor = criar_servidor(int(sys.argv[1]) if len(sys.argv) > 1 else 11500, float(sys.argv[2]) if len(sys.argv) > 2 else 0.6)
    print(f"Ollama simulado em http://127.0.0.1:{PORTA}", flush=True)
    servidor.serve_forever()

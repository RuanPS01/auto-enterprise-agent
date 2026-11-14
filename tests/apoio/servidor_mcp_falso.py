"""Servidor MCP mínimo (stdio) usado nos testes do cliente de extensões."""

import json
import os
import sys

FERRAMENTAS = [
    {
        "name": "somar",
        "description": "Soma dois números.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
    {"name": "ler-segredo", "description": "Mostra a variável de ambiente recebida.", "inputSchema": {"type": "object"}},
    {"name": "falhar", "description": "Sempre devolve erro.", "inputSchema": {"type": "object", "properties": {}}},
]


def responder(identificador, resultado):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": identificador, "result": resultado}) + "\n")
    sys.stdout.flush()


print("servidor falso iniciado", file=sys.stderr)
for linha in sys.stdin:
    try:
        mensagem = json.loads(linha)
    except json.JSONDecodeError:
        continue
    metodo, identificador = mensagem.get("method"), mensagem.get("id")
    if identificador is None:
        continue  # notificações não têm resposta
    if metodo == "initialize":
        responder(identificador, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "falso", "version": "1"}})
    elif metodo == "tools/list":
        responder(identificador, {"tools": FERRAMENTAS})
    elif metodo == "tools/call":
        nome = mensagem["params"]["name"]
        args = mensagem["params"].get("arguments") or {}
        if nome == "somar":
            responder(identificador, {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]})
        elif nome == "ler-segredo":
            responder(identificador, {"content": [{"type": "text", "text": os.environ.get("CHAVE_API", "")}]})
        else:
            responder(identificador, {"content": [{"type": "text", "text": "deu errado"}], "isError": True})
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": identificador, "error": {"code": -32601, "message": "método desconhecido"}}) + "\n")
        sys.stdout.flush()

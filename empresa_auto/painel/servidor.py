"""Painel web local: a única interface entre o dono e o agente.

O painel serve para três coisas: dar a partida na empresa (uma única vez),
acompanhar em tempo real o que o agente está fazendo e ler o resumo da semana.
Opcionalmente o dono pode cadastrar um cartão ou fornecer uma conta.

Segurança:

* Em ``127.0.0.1`` (padrão) o painel só aceita o cabeçalho Host local, o que
  bloqueia ataques de religação de DNS vindos de sites abertos no navegador.
* Em qualquer outro endereço (acesso pela rede) é exigido um token.
* Toda alteração exige um cabeçalho próprio, o que impede que outro site
  dispare ações no painel usando o navegador do dono.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agente import Agente
from ..agente import resumo as modulo_resumo
from ..cofre import ErroCofre

DIR_ESTATICO = Path(__file__).resolve().parent / "estatico"
COOKIE = "ea_token"
HOSTS_LOCAIS = {"127.0.0.1", "localhost", "[::1]", "::1"}

PAGINA_ENTRADA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Empresa Automática</title>
<style>body{font-family:system-ui,sans-serif;background:#f4f5f7;color:#1a1d23;display:grid;place-items:center;
min-height:100vh;margin:0}form{background:#fff;padding:32px;border-radius:12px;border:1px solid #d9dce3;width:min(92vw,380px)}
h1{font-size:18px;margin:0 0 8px}p{color:#5b6270;font-size:14px;margin:0 0 16px}
input{width:100%;box-sizing:border-box;padding:10px;border:1px solid #c5c9d3;border-radius:8px;font-size:15px}
button{margin-top:12px;width:100%;padding:10px;border:0;border-radius:8px;background:#1f4fd8;color:#fff;font-size:15px;cursor:pointer}
@media (prefers-color-scheme: dark){body{background:#111318;color:#e8eaf0}form{background:#1a1d24;border-color:#2c313c}
p{color:#9aa1b0}input{background:#111318;color:#e8eaf0;border-color:#3a404d}}</style></head>
<body><form method="get" action="/"><h1>Empresa Automática</h1>
<p>Informe o token de acesso exibido no terminal quando o agente foi iniciado.</p>
<input name="token" type="password" placeholder="Token de acesso" autofocus required>
<button type="submit">Entrar</button></form></body></html>"""


class PedidoInicio(BaseModel):
    modo: str
    ideia: str = ""


class PedidoCartao(BaseModel):
    numero: str
    validade: str
    cvv: str
    titular: str = ""
    limite_mensal: float


class PedidoConta(BaseModel):
    servico: str
    usuario: str
    senha: str
    url: str = ""
    notas: str = ""


def _host_sem_porta(valor: str) -> str:
    valor = valor.strip().lower()
    if valor.startswith("["):
        return valor.split("]")[0] + "]"
    return valor.rsplit(":", 1)[0] if ":" in valor else valor


def obter_token(dir_dados: Path) -> str:
    """Lê (ou cria) o token de acesso ao painel."""
    arquivo = dir_dados / "token_painel.txt"
    if arquivo.exists():
        token = arquivo.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(24)
    arquivo.write_text(token, encoding="utf-8")
    try:
        os.chmod(arquivo, 0o600)
    except OSError:
        pass
    return token


def criar_app(agente: Agente) -> FastAPI:
    cfg = agente.cfg
    app = FastAPI(title="Empresa Automática", docs_url=None, redoc_url=None, openapi_url=None)
    exige_token = cfg.painel_exposto
    token = obter_token(cfg.dir_dados) if exige_token else ""

    @app.middleware("http")
    async def proteger(request: Request, call_next):
        caminho = request.url.path
        if not exige_token:
            if _host_sem_porta(request.headers.get("host") or "") not in HOSTS_LOCAIS:
                return JSONResponse({"erro": "Acesso permitido apenas pelo endereço local."}, status_code=403)
        else:
            informado = request.query_params.get("token")
            if informado and secrets.compare_digest(informado, token):
                resposta = RedirectResponse(caminho, status_code=303)
                resposta.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=90 * 86400)
                return resposta
            apresentado = request.cookies.get(COOKIE) or ""
            cabecalho = request.headers.get("authorization") or ""
            if cabecalho.lower().startswith("bearer "):
                apresentado = cabecalho[7:].strip()
            if not (apresentado and secrets.compare_digest(apresentado, token)):
                if caminho.startswith("/api/"):
                    return JSONResponse({"erro": "Token de acesso ausente ou inválido."}, status_code=401)
                return HTMLResponse(PAGINA_ENTRADA, status_code=401)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") != "empresa-auto":
            return JSONResponse({"erro": "Requisição recusada."}, status_code=403)
        resposta = await call_next(request)
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["X-Frame-Options"] = "DENY"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        return resposta

    app.mount("/estatico", StaticFiles(directory=str(DIR_ESTATICO)), name="estatico")

    @app.get("/")
    def pagina() -> FileResponse:
        return FileResponse(DIR_ESTATICO / "index.html")

    # ------------------------------------------------------------------ leitura
    @app.get("/api/estado")
    def estado() -> dict:
        return agente.estado()

    @app.get("/api/eventos")
    def eventos(depois: int = 0, limite: int = 300) -> dict:
        limite = max(1, min(1000, limite))
        if depois > 0:
            return {"eventos": agente.banco.eventos_depois(depois, limite)}
        return {"eventos": agente.banco.eventos_recentes(limite)}

    @app.get("/api/fluxo")
    async def fluxo(request: Request, depois: int = 0) -> StreamingResponse:
        """Eventos em tempo real (Server-Sent Events)."""
        ultimo = depois
        retomada = request.headers.get("last-event-id")
        if retomada and retomada.isdigit():
            ultimo = max(ultimo, int(retomada))

        async def gerar():
            nonlocal ultimo
            ociosos = 0
            yield "retry: 3000\n\n"
            while not agente._parar.is_set():
                if await request.is_disconnected():
                    break
                novos = await asyncio.to_thread(agente.banco.eventos_depois, ultimo, 200)
                if novos:
                    ociosos = 0
                    for evento in novos:
                        ultimo = evento["id"]
                        yield f"id: {evento['id']}\ndata: {json.dumps(evento, ensure_ascii=False)}\n\n"
                else:
                    ociosos += 1
                    if ociosos % 15 == 0:
                        yield ": ativo\n\n"
                    await asyncio.sleep(1.0)

        return StreamingResponse(
            gerar(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Connection": "keep-alive"}
        )

    @app.get("/api/resumo")
    def resumo(semana: str | None = None) -> dict:
        try:
            return modulo_resumo.dados_do_resumo(agente.banco, semana)
        except ValueError:
            raise HTTPException(400, "Semana inválida.") from None

    @app.get("/api/captura")
    def captura() -> FileResponse:
        arquivo = cfg.dir_capturas / "atual.png"
        if not arquivo.exists():
            raise HTTPException(404, "Sem captura.")
        return FileResponse(arquivo, media_type="image/png")

    # ------------------------------------------------------------------ ações do dono
    @app.post("/api/iniciar")
    def iniciar(pedido: PedidoInicio) -> dict:
        try:
            agente.iniciar_empresa(pedido.modo, pedido.ideia)
        except ValueError as erro:
            raise HTTPException(400, str(erro)) from None
        return {"ok": True}

    @app.post("/api/pausar")
    def pausar() -> dict:
        agente.pausar()
        return {"ok": True}

    @app.post("/api/retomar")
    def retomar() -> dict:
        agente.retomar()
        return {"ok": True}

    @app.post("/api/cartao")
    def definir_cartao(pedido: PedidoCartao) -> dict:
        try:
            agente.cofre.definir_cartao(pedido.numero, pedido.validade, pedido.cvv, pedido.titular, pedido.limite_mensal)
        except (ErroCofre, ValueError) as erro:
            raise HTTPException(400, str(erro)) from None
        resumo_cartao = agente.cofre.resumo_cartao()
        agente.registro.evento(
            "pagamento",
            f"Cartão cadastrado pelo dono (final {resumo_cartao['final']}, limite mensal de R$ {resumo_cartao['limite_mensal']:.2f})",
            nivel="aviso",
        )
        return {"ok": True}

    @app.delete("/api/cartao")
    def remover_cartao() -> dict:
        if agente.cofre.remover_cartao():
            agente.registro.evento("pagamento", "Cartão removido pelo dono", nivel="aviso")
        return {"ok": True}

    @app.post("/api/contas")
    def fornecer_conta(pedido: PedidoConta) -> dict:
        if not pedido.servico.strip() or not pedido.usuario.strip() or not pedido.senha:
            raise HTTPException(400, "Informe serviço, usuário e senha.")
        agente.cofre.salvar_credencial(
            pedido.servico, pedido.usuario, pedido.senha, url=pedido.url, notas=pedido.notas, origem="dono"
        )
        agente.registro.evento("conta", f"Conta fornecida pelo dono: {pedido.servico.strip().lower()}", f"usuário: {pedido.usuario}")
        agente.amb.extensoes.registrar_por_credencial(pedido.servico)
        return {"ok": True}

    @app.post("/api/bloqueios/{bloqueio_id}/resolver")
    def resolver_bloqueio(bloqueio_id: int) -> dict:
        agente.banco.resolver_bloqueio(bloqueio_id)
        agente.registro.evento("sistema", f"Impedimento #{bloqueio_id} marcado como resolvido pelo dono")
        return {"ok": True}

    return app

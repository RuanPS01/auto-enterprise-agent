"""Linha de comando da Empresa Automática.

    python -m empresa_auto              liga o agente e o painel web
    python -m empresa_auto verificar    confere se a máquina está pronta
    python -m empresa_auto zerar --sim  apaga a empresa atual para começar outra
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import sys
import threading

import psutil

from . import __version__
from .config import Config, carregar_config, url_e_local


def _preparar_console() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def _config_dos_argumentos(args: argparse.Namespace) -> Config:
    return carregar_config(
        args.dados,
        host=args.host,
        porta=args.porta,
        modelo=args.modelo,
        url_llm=args.url_llm,
        provedor=args.provedor,
    )


def _ip_da_rede() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "IP-DESTA-MAQUINA"


def _travar_instancia(cfg: Config) -> None:
    """Impede dois agentes no mesmo diretório de dados (eles disputariam a mesma empresa)."""
    arquivo = cfg.dir_dados / "agente.pid"
    if arquivo.exists():
        try:
            pid = int(arquivo.read_text().strip())
            if pid != os.getpid() and psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower():
                print(
                    f"Já existe um agente rodando com estes dados (PID {pid}). "
                    "Encerre-o antes ou use outro diretório com --dados.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
        except (ValueError, psutil.Error):
            pass
    arquivo.write_text(str(os.getpid()))


# ---------------------------------------------------------------------- iniciar
def comando_iniciar(args: argparse.Namespace) -> int:
    import uvicorn

    from .agente import Agente
    from .llm import ErroLLM
    from .painel import criar_app
    from .painel.servidor import obter_token

    cfg = _config_dos_argumentos(args)
    cfg.preparar_diretorios()
    _travar_instancia(cfg)
    try:
        agente = Agente(cfg)
    except ErroLLM as erro:
        print(f"Configuração inválida: {erro}", file=sys.stderr)
        return 1
    app = criar_app(agente)

    print(f"Empresa Automática {__version__}")
    if cfg.painel_exposto:
        token = obter_token(cfg.dir_dados)
        print(f"Painel:  http://{_ip_da_rede()}:{cfg.porta}/?token={token}")
        print("         (o painel está acessível pela rede; o token acima é a chave de acesso)")
    else:
        print(f"Painel:  http://127.0.0.1:{cfg.porta}")
        print(f"         De outra máquina: ssh -L {cfg.porta}:127.0.0.1:{cfg.porta} usuario@{_ip_da_rede()}")
        print("         ou reinicie com --host 0.0.0.0 para liberar o acesso pela rede com token.")
    print(f"Modelo:  {cfg.modelo} ({cfg.provedor} em {cfg.url_llm})")
    print(f"Dados:   {cfg.dir_dados}")
    print("Pressione Ctrl+C para desligar.\n", flush=True)

    def _encerrar_por_sinal(numero: int, quadro: object) -> None:
        raise KeyboardInterrupt

    # O uvicorn devolve o sinal recebido depois de fechar o painel. Sem este tratador, um SIGTERM
    # (systemctl stop, kill) mataria o processo antes de os serviços da empresa serem encerrados.
    signal.signal(signal.SIGTERM, _encerrar_por_sinal)

    trabalhador = threading.Thread(target=agente.rodar, name="agente", daemon=True)
    trabalhador.start()
    servidor = uvicorn.Server(
        uvicorn.Config(
            app,
            host=cfg.host,
            port=cfg.porta,
            log_level="warning",
            access_log=False,
            timeout_graceful_shutdown=3,
        )
    )
    try:
        servidor.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nDesligando o agente...", flush=True)
        agente.parar()
        trabalhador.join(timeout=20)
        if trabalhador.is_alive():
            # O agente está preso em uma chamada longa ao modelo: encerra os serviços daqui mesmo.
            try:
                agente.amb.supervisor.encerrar_todos()
                agente.amb.extensoes.encerrar_todas()
            except Exception:
                pass
        try:
            (cfg.dir_dados / "agente.pid").unlink()
        except OSError:
            pass
    return 0


# ---------------------------------------------------------------------- verificar
def comando_verificar(args: argparse.Namespace) -> int:
    from .llm import ClienteLLM, ErroLLM

    cfg = _config_dos_argumentos(args)
    cfg.preparar_diretorios()
    problemas = 0

    def linha(ok: bool | None, texto: str, dica: str = "") -> None:
        nonlocal problemas
        marca = "[ok]   " if ok else ("[aviso]" if ok is None else "[falta]")
        if ok is False:
            problemas += 1
        print(f"{marca} {texto}")
        if dica and not ok:
            print(f"        {dica}")

    print(f"Empresa Automática {__version__}: verificação do ambiente\n")
    linha(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "É necessário Python 3.10 ou mais novo.")
    linha(True, f"Diretório de dados: {cfg.dir_dados}")
    linha(
        cfg.permitir_llm_remoto or url_e_local(cfg.url_llm),
        f"Endereço do modelo é local: {cfg.url_llm}",
        "Use um servidor de LLM na própria máquina ou na rede privada.",
    )

    try:
        llm = ClienteLLM(cfg)
        instalados = llm.modelos_instalados()
        linha(True, f"Servidor do modelo responde ({cfg.provedor}), {len(instalados)} modelo(s) instalado(s)")
        if llm.modelo_disponivel():
            linha(True, f"Modelo {cfg.modelo} instalado")
            try:
                resposta = llm.conversar(
                    [
                        {"role": "system", "content": "Você é um assistente que usa ferramentas."},
                        {"role": "user", "content": "Use a ferramenta somar para calcular 2 + 3."},
                    ],
                    [
                        {
                            "nome": "somar",
                            "descricao": "Soma dois números.",
                            "parametros": {
                                "type": "object",
                                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                                "required": ["a", "b"],
                            },
                        }
                    ],
                )
                usou = any(c.nome == "somar" for c in resposta.chamadas)
                linha(
                    True if usou else None,
                    f"Chamada de ferramentas pelo modelo (modo {llm.modo_atual})"
                    + ("" if usou else ": o modelo respondeu sem usar a ferramenta"),
                    "O agente funciona melhor com modelos bons em ferramentas, como qwen3 ou gpt-oss.",
                )
            except ErroLLM as erro:
                linha(False, f"Teste de conversa com o modelo falhou: {erro}")
        else:
            dica = f"Rode: ollama pull {cfg.modelo} (o agente também baixa sozinho ao iniciar)." if cfg.provedor == "ollama" else ""
            linha(None if cfg.provedor == "ollama" else False, f"Modelo {cfg.modelo} ainda não instalado", dica)
    except ErroLLM as erro:
        linha(False, f"Servidor do modelo não responde: {erro}", "Instale e inicie o Ollama: https://ollama.com/download")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            opcoes = {"headless": True}
            if cfg.navegador_executavel:
                opcoes["executable_path"] = cfg.navegador_executavel
            navegador = pw.chromium.launch(**opcoes)
            navegador.close()
        linha(True, "Navegador Chromium abre corretamente")
    except Exception as erro:
        resumo = str(erro).splitlines()[0][:160]
        linha(False, f"Navegador Chromium não abriu: {resumo}", "Rode: python -m playwright install --with-deps chromium")

    linha(bool(shutil.which("git")), "git instalado", "Instale o git (necessário para publicar código e instalar habilidades).")
    linha(
        True if shutil.which("node") else None,
        "Node.js instalado" if shutil.which("node") else "Node.js não encontrado (opcional)",
        "Recomendado: muitas extensões da comunidade (MCP) e ferramentas web usam npx.",
    )
    try:
        from .ferramentas.web import pesquisar

        resultados = pesquisar("software de código aberto", 3, cfg.url_searxng)
        linha(bool(resultados), "Pesquisa na web funciona", "Sem resultados: confira a conexão com a internet.")
    except Exception as erro:
        linha(False, f"Pesquisa na web falhou: {erro}", "Confira a conexão com a internet.")

    print()
    if problemas:
        print(f"{problemas} item(ns) precisam de atenção antes de ligar o agente.")
        return 1
    print("Tudo pronto. Ligue o agente com: python -m empresa_auto")
    return 0


# ---------------------------------------------------------------------- zerar
def comando_zerar(args: argparse.Namespace) -> int:
    from .banco import Banco
    from .cofre import Cofre

    cfg = _config_dos_argumentos(args)
    if not args.sim:
        print(
            "Este comando apaga a empresa atual: tarefas, memória, registros, contas do cofre e cartão.\n"
            "Os arquivos da pasta de trabalho são mantidos. Para confirmar, rode novamente com --sim."
        )
        return 1
    cfg.preparar_diretorios()
    _travar_instancia(cfg)
    try:
        Banco(cfg.caminho_banco).zerar()
        Cofre(cfg.dir_dados).zerar()
    finally:
        (cfg.dir_dados / "agente.pid").unlink(missing_ok=True)
    print("Empresa apagada. Ligue o agente e use o painel para começar outra.")
    return 0


def principal(argv: list[str] | None = None) -> int:
    _preparar_console()
    analisador = argparse.ArgumentParser(
        prog="empresa-auto",
        description="Agente autônomo que cria e opera uma empresa usando apenas modelos de linguagem locais.",
    )
    analisador.add_argument("comando", nargs="?", default="iniciar", choices=["iniciar", "verificar", "zerar"])
    analisador.add_argument("--dados", help="diretório de dados (padrão: ~/.empresa-auto)")
    analisador.add_argument("--host", help="endereço do painel (padrão 127.0.0.1; use 0.0.0.0 para a rede)")
    analisador.add_argument("--porta", type=int, help="porta do painel (padrão 8787)")
    analisador.add_argument("--modelo", help="modelo local a usar (padrão qwen3:8b)")
    analisador.add_argument("--url-llm", dest="url_llm", help="endereço do servidor do modelo")
    analisador.add_argument("--provedor", choices=["ollama", "openai"], help="tipo de servidor do modelo")
    analisador.add_argument("--sim", action="store_true", help="confirma o comando zerar")
    analisador.add_argument("--versao", action="version", version=f"empresa-auto {__version__}")
    args = analisador.parse_args(argv)
    comandos = {"iniciar": comando_iniciar, "verificar": comando_verificar, "zerar": comando_zerar}
    try:
        return comandos[args.comando](args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(principal())

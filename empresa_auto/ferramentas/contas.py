"""Cofre de credenciais e e-mail da empresa."""

from __future__ import annotations

import email
import imaplib
import smtplib
import ssl
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from ..cofre import gerar_senha
from .base import Ambiente, Catalogo, P
from .web import html_para_texto

SERVICO_EMAIL = "email"


def _decodificar(valor: str | None) -> str:
    if not valor:
        return ""
    try:
        return str(make_header(decode_header(valor)))
    except Exception:
        return valor


def _corpo_texto(mensagem: email.message.Message) -> str:
    """Extrai o corpo legível de um e-mail (prefere texto puro)."""
    html = ""
    partes = mensagem.walk() if mensagem.is_multipart() else [mensagem]
    for parte in partes:
        if parte.get_content_maintype() == "multipart" or parte.get_filename():
            continue
        carga = parte.get_payload(decode=True)
        if not carga:
            continue
        texto = carga.decode(parte.get_content_charset() or "utf-8", errors="replace")
        if parte.get_content_type() == "text/plain":
            return texto.strip()
        if parte.get_content_type() == "text/html" and not html:
            html = texto
    return html_para_texto(html)[1] if html else ""


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    cofre = amb.cofre
    banco = amb.banco

    # ------------------------------------------------------------------ cofre
    @cat.ferramenta(
        "senha_gerar",
        "Gera uma senha forte e única para uma conta nova. Depois de criar a conta, guarde com credencial_salvar.",
        _grupo="contas",
        tamanho=P("integer", "Quantidade de caracteres (padrão 20).", obrigatorio=False),
    )
    def senha_gerar(tamanho: int = 20) -> str:
        senha = gerar_senha(tamanho)
        cofre.lembrar_segredo_temporario(senha)
        return f"Senha gerada: {senha}"

    @cat.ferramenta(
        "credencial_salvar",
        "Guarda no cofre cifrado o acesso a uma conta da empresa (login e senha, ou chave de API no campo senha). "
        "Tokens com nomes do catálogo (github-token, cloudflare-token, netlify-token, notion-token, sentry-token) "
        "liberam automaticamente as extensões correspondentes.",
        _grupo="contas",
        servico=P("string", "Nome curto do serviço, por exemplo: github, cloudflare, email."),
        usuario=P("string", "Login, e-mail ou identificador da conta."),
        senha=P("string", "Senha ou chave de API."),
        url=P("string", "Endereço de login do serviço.", obrigatorio=False),
        notas=P("string", "Observações úteis (plano gratuito, limites, perguntas de segurança).", obrigatorio=False),
    )
    def credencial_salvar(servico: str, usuario: str, senha: str, url: str = "", notas: str = "") -> str:
        cofre.salvar_credencial(servico, usuario, senha, url=url, notas=notas)
        amb.registro.evento("conta", f"Credencial guardada no cofre: {servico.strip().lower()}", f"usuário: {usuario}")
        liberadas = amb.extensoes.registrar_por_credencial(servico) if amb.extensoes else []
        extra = f" Com ela ficaram disponíveis os grupos de extensão: {', '.join(liberadas)}." if liberadas else ""
        return f"Credencial de '{servico.strip().lower()}' guardada no cofre.{extra}"

    @cat.ferramenta(
        "credencial_obter",
        "Recupera do cofre o login e a senha de um serviço.",
        _grupo="contas",
        _sensivel=True,
        servico=P("string", "Nome do serviço, como aparece em credencial_listar."),
    )
    def credencial_obter(servico: str) -> str:
        item = cofre.obter_credencial(servico)
        if not item:
            nomes = ", ".join(c["servico"] for c in cofre.listar()) or "nenhuma"
            return f"Não há credencial para '{servico}'. Disponíveis: {nomes}."
        linhas = [f"serviço: {item['servico']}", f"usuário: {item['usuario']}", f"senha: {item['senha']}"]
        if item.get("url"):
            linhas.append(f"url: {item['url']}")
        if item.get("notas"):
            linhas.append(f"notas: {item['notas']}")
        for nome, valor in (item.get("extras") or {}).items():
            linhas.append(f"{nome}: {valor}")
        return "\n".join(linhas)

    @cat.ferramenta("credencial_listar", "Lista as contas guardadas no cofre (sem mostrar senhas).", _grupo="contas")
    def credencial_listar() -> str:
        itens = cofre.listar()
        if not itens:
            return "O cofre está vazio: a empresa ainda não tem contas."
        return "\n".join(
            f"- {c['servico']}: {c['usuario']}" + (f" ({c['notas']})" if c["notas"] else "") for c in itens
        )

    # ------------------------------------------------------------------ e-mail
    @cat.ferramenta(
        "email_configurar",
        "Define a conta de e-mail oficial da empresa (qualquer provedor com SMTP e IMAP). Depois disso, "
        "email_enviar e email_ler passam a funcionar.",
        _grupo="contas",
        endereco=P("string", "Endereço de e-mail."),
        senha=P("string", "Senha da conta ou senha de aplicativo."),
        smtp_host=P("string", "Servidor SMTP, por exemplo smtp.provedor.com."),
        imap_host=P("string", "Servidor IMAP, por exemplo imap.provedor.com."),
        smtp_porta=P("integer", "Porta SMTP (587 com STARTTLS ou 465 com SSL; padrão 587).", obrigatorio=False),
        imap_porta=P("integer", "Porta IMAP (padrão 993).", obrigatorio=False),
    )
    def email_configurar(
        endereco: str, senha: str, smtp_host: str, imap_host: str, smtp_porta: int = 587, imap_porta: int = 993
    ) -> str:
        cofre.salvar_credencial(
            SERVICO_EMAIL,
            endereco,
            senha,
            notas="conta de e-mail oficial da empresa",
            extras={"smtp_host": smtp_host, "smtp_porta": smtp_porta, "imap_host": imap_host, "imap_porta": imap_porta},
        )
        amb.registro.evento("conta", "E-mail oficial da empresa configurado", endereco)
        return f"E-mail {endereco} configurado. Teste com email_ler antes de divulgar o endereço."

    def _conta_email() -> dict | None:
        conta = cofre.obter_credencial(SERVICO_EMAIL)
        if not conta or not (conta.get("extras") or {}).get("smtp_host"):
            return None
        return conta

    @cat.ferramenta(
        "email_enviar",
        "Envia um e-mail pela conta oficial da empresa. Use para atender clientes e parceiros. É proibido enviar "
        "spam: escreva apenas para quem entrou em contato ou autorizou o recebimento.",
        _grupo="contas",
        para=P("string", "Endereço do destinatário."),
        assunto=P("string", "Assunto."),
        corpo=P("string", "Texto do e-mail."),
    )
    def email_enviar(para: str, assunto: str, corpo: str) -> str:
        conta = _conta_email()
        if not conta:
            return "ERRO: nenhum e-mail configurado. Crie uma conta gratuita e use email_configurar."
        agora = time.time()
        if banco.contar_envios("email", agora - 3600) >= amb.cfg.limite_emails_hora:
            return "NEGADO: limite de e-mails por hora atingido. Tente novamente mais tarde."
        if banco.contar_envios("email", agora - 86400) >= amb.cfg.limite_emails_dia:
            return "NEGADO: limite diário de e-mails atingido. Tente novamente amanhã."
        extras = conta["extras"]
        mensagem = EmailMessage()
        mensagem["From"] = conta["usuario"]
        mensagem["To"] = para
        mensagem["Subject"] = assunto
        mensagem["Date"] = formatdate(localtime=True)
        mensagem["Message-ID"] = make_msgid()
        mensagem.set_content(corpo)
        porta = int(extras.get("smtp_porta") or 587)
        contexto = ssl.create_default_context()
        if porta == 465:
            servidor: smtplib.SMTP = smtplib.SMTP_SSL(extras["smtp_host"], porta, timeout=60, context=contexto)
        else:
            servidor = smtplib.SMTP(extras["smtp_host"], porta, timeout=60)
            servidor.starttls(context=contexto)
        try:
            servidor.login(conta["usuario"], conta["senha"])
            servidor.send_message(mensagem)
        finally:
            try:
                servidor.quit()
            except Exception:
                pass
        banco.registrar_envio("email", para, assunto)
        amb.registro.evento("comunicacao", f"E-mail enviado para {para}", assunto)
        return f"E-mail enviado para {para}."

    @cat.ferramenta(
        "email_ler",
        "Lê as mensagens mais recentes da caixa de entrada da empresa.",
        _grupo="contas",
        limite=P("integer", "Quantidade de mensagens (padrão 10).", obrigatorio=False),
        apenas_nao_lidas=P("boolean", "Ler só as não lidas (padrão true).", obrigatorio=False),
    )
    def email_ler(limite: int = 10, apenas_nao_lidas: bool = True) -> str:
        conta = _conta_email()
        if not conta:
            return "ERRO: nenhum e-mail configurado. Crie uma conta gratuita e use email_configurar."
        extras = conta["extras"]
        caixa = imaplib.IMAP4_SSL(extras["imap_host"], int(extras.get("imap_porta") or 993), timeout=60)
        try:
            caixa.login(conta["usuario"], conta["senha"])
            caixa.select("INBOX")
            _, dados = caixa.search(None, "UNSEEN" if apenas_nao_lidas else "ALL")
            identificadores = dados[0].split()[-max(1, min(30, limite)) :]
            if not identificadores:
                return "Nenhuma mensagem nova na caixa de entrada."
            blocos = []
            for identificador in reversed(identificadores):
                _, partes = caixa.fetch(identificador, "(RFC822)")
                if not partes or not partes[0]:
                    continue
                mensagem = email.message_from_bytes(partes[0][1])
                corpo = _corpo_texto(mensagem)
                if len(corpo) > 900:
                    corpo = corpo[:900] + " [...]"
                blocos.append(
                    f"De: {_decodificar(mensagem.get('From'))}\n"
                    f"Assunto: {_decodificar(mensagem.get('Subject'))}\n"
                    f"Data: {mensagem.get('Date', '')}\n"
                    f"{corpo}"
                )
            return "\n\n-----\n\n".join(blocos) or "Nenhuma mensagem nova na caixa de entrada."
        finally:
            try:
                caixa.logout()
            except Exception:
                pass

"""Navegador real controlado pelo agente (Chromium via Playwright).

O modelo local não enxerga imagens, então cada página é convertida em texto:
o conteúdo visível e uma lista numerada de elementos interativos. O modelo age
informando o número do elemento.

O perfil do navegador é persistente: sessões e cookies sobrevivem a
reinicializações, então as contas da empresa continuam conectadas.

Limite deliberado: o agente não tenta burlar CAPTCHAs nem verificações
antirrobô. Quando encontra uma, ele é orientado a procurar outro caminho.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from .base import Ambiente, Catalogo, P

TAMANHO_TEXTO = 3000
MAX_ELEMENTOS = 120

_JS_INSTANTANEO = r"""
(limite) => {
  const visivel = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const limpar = (t) => (t || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-ea]').forEach((e) => e.removeAttribute('data-ea'));
  const seletor = 'a[href], button, input, textarea, select, summary, [role=button], [role=link], ' +
    '[role=checkbox], [role=radio], [role=tab], [role=menuitem], [role=option], [role=switch], ' +
    '[role=combobox], [role=textbox], [contenteditable=""], [contenteditable=true], [onclick]';
  const itens = [];
  let n = 0;
  for (const el of document.querySelectorAll(seletor)) {
    if (n >= limite) break;
    const tag = el.tagName.toLowerCase();
    const tipo = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && tipo === 'hidden') continue;
    if (el.disabled || !visivel(el)) continue;
    n += 1;
    el.setAttribute('data-ea', String(n));
    let rotulo = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
    if (!rotulo && el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) rotulo = l.innerText;
    }
    if (!rotulo && (tag === 'input' || tag === 'select' || tag === 'textarea') && el.closest('label')) {
      rotulo = el.closest('label').innerText;
    }
    if (!rotulo) {
      rotulo = el.innerText || (tipo === 'submit' || tipo === 'button' ? el.value : '') ||
        el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('name') || '';
    }
    if (!rotulo) {
      const img = el.querySelector('img[alt]');
      if (img) rotulo = img.getAttribute('alt');
    }
    const identidade = (el.getAttribute('name') || '') + ' ' + (el.id || '') + ' ' + (el.getAttribute('autocomplete') || '');
    const sensivel = tipo === 'password' || /card|cc-|cvv|cvc|cartao|senha|password/i.test(identidade);
    let valor = '';
    if (tag === 'input' || tag === 'textarea') {
      if (tipo === 'checkbox' || tipo === 'radio') valor = el.checked ? 'marcado' : 'desmarcado';
      else if (el.value) valor = sensivel ? '(preenchido)' : el.value.slice(0, 60);
    }
    let opcoes = [];
    if (tag === 'select') {
      opcoes = Array.from(el.options).slice(0, 25).map((o) => limpar(o.text));
      valor = el.selectedOptions[0] ? limpar(el.selectedOptions[0].text) : '';
    }
    itens.push({
      n, tag, tipo,
      papel: el.getAttribute('role') || '',
      rotulo: limpar(rotulo).slice(0, 90),
      nome: el.getAttribute('name') || '',
      valor, opcoes,
      href: tag === 'a' ? el.href : '',
    });
  }
  const captcha = !!document.querySelector(
    'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], ' +
    'iframe[src*="challenges.cloudflare"], iframe[src*="arkoselabs"], iframe[src*="funcaptcha"], ' +
    '.g-recaptcha, .h-captcha, .cf-turnstile, #captcha, [name="captcha"]'
  );
  return {
    url: location.href,
    titulo: document.title,
    texto: (document.body ? document.body.innerText : '').slice(0, 15000),
    itens, captcha,
  };
}
"""

_RE_VERIFICACAO = re.compile(
    r"verify (that )?you are (a )?human|are you a robot|não sou um robô|nao sou um robo|"
    r"verifique que você é humano|checking your browser|unusual traffic|tráfego incomum",
    re.IGNORECASE,
)

AVISO_CAPTCHA = (
    "AVISO: esta página exige uma verificação humana (CAPTCHA ou similar). Não tente burlar. "
    "Procure outro caminho: uma API oficial, outro serviço equivalente ou uma conta já existente no cofre. "
    "Se não houver alternativa, use bloqueio_relatar e siga com outra frente de trabalho."
)


def _descrever(item: dict) -> str:
    tag, tipo, papel = item["tag"], item["tipo"], item["papel"]
    rotulo = item["rotulo"] or item["nome"] or "(sem rótulo)"
    if tag == "a" or papel == "link":
        destino = item["href"]
        destino = destino if len(destino) <= 90 else destino[:87] + "..."
        return f'[{item["n"]}] link "{rotulo}" {destino}'.rstrip()
    if tag == "select":
        opcoes = " | ".join(item["opcoes"])
        return f'[{item["n"]}] seleção "{rotulo}" atual: {item["valor"] or "-"} opções: {opcoes}'
    if tag == "textarea" or papel == "textbox" or (tag == "input" and tipo not in ("submit", "button", "checkbox", "radio", "image", "reset", "file")):
        valor = f' valor: "{item["valor"]}"' if item["valor"] else ""
        return f'[{item["n"]}] campo {tipo or "texto"} "{rotulo}"{valor}'
    if tipo in ("checkbox", "radio") or papel in ("checkbox", "radio", "switch"):
        return f'[{item["n"]}] {tipo or papel} "{rotulo}" {item["valor"]}'.rstrip()
    if tipo == "file":
        return f'[{item["n"]}] envio de arquivo "{rotulo}"'
    return f'[{item["n"]}] botão "{rotulo}"'


class Navegador:
    def __init__(self, amb: Ambiente):
        self.amb = amb
        self.cfg = amb.cfg
        self._pw = None
        self._contexto = None
        self._pagina = None
        self._tentou_instalar = False

    # ------------------------------------------------------------------ ciclo de vida
    def _abrir_contexto(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        opcoes: dict = {
            "user_data_dir": str(self.cfg.dir_navegador),
            "headless": self.cfg.navegador_headless,
            "viewport": {"width": 1280, "height": 900},
            "locale": "pt-BR",
            "accept_downloads": True,
            "downloads_path": str(self.cfg.dir_trabalho / "downloads"),
        }
        if self.cfg.navegador_executavel:
            opcoes["executable_path"] = self.cfg.navegador_executavel
        (self.cfg.dir_trabalho / "downloads").mkdir(parents=True, exist_ok=True)
        return self._pw.chromium.launch_persistent_context(**opcoes)

    def _garantir(self):
        if self._pagina is not None and not self._pagina.is_closed():
            return self._pagina
        if self._contexto is None:
            try:
                self._contexto = self._abrir_contexto()
            except Exception as erro:
                self._descartar()
                faltando = "Executable doesn't exist" in str(erro) or "playwright install" in str(erro)
                if faltando and not self._tentou_instalar and not self.cfg.navegador_executavel:
                    self._tentou_instalar = True
                    self.amb.registro.sistema("Instalando o navegador Chromium (primeiro uso)")
                    subprocess.run(
                        [sys.executable, "-m", "playwright", "install", "chromium"],
                        timeout=1800,
                        capture_output=True,
                    )
                    self._contexto = self._abrir_contexto()
                else:
                    raise
            self._contexto.set_default_timeout(20000)
            self._contexto.on("page", self._ao_abrir_pagina)
        paginas = [p for p in self._contexto.pages if not p.is_closed()]
        self._pagina = paginas[-1] if paginas else self._contexto.new_page()
        self._preparar(self._pagina)
        return self._pagina

    def _preparar(self, pagina) -> None:
        try:
            pagina.on("dialog", lambda dialogo: dialogo.accept())
        except Exception:
            pass

    def _ao_abrir_pagina(self, pagina) -> None:
        # Links que abrem em nova aba: o agente passa a trabalhar na aba nova.
        self._pagina = pagina
        self._preparar(pagina)

    def _descartar(self) -> None:
        for alvo, metodo in ((self._contexto, "close"), (self._pw, "stop")):
            try:
                if alvo is not None:
                    getattr(alvo, metodo)()
            except Exception:
                pass
        self._pw = self._contexto = self._pagina = None

    def fechar(self) -> None:
        self._descartar()

    def _executar(self, acao) -> str:
        """Roda uma ação e reinicia o navegador se ele tiver caído."""
        try:
            return acao()
        except Exception as erro:
            texto = str(erro).splitlines()[0] if str(erro) else type(erro).__name__
            if any(p in str(erro) for p in ("has been closed", "Target closed", "Connection closed", "Browser closed")):
                self._descartar()
                return f"ERRO: o navegador foi reiniciado ({texto}). Abra a página novamente."
            return f"ERRO no navegador: {texto}"

    def _aguardar(self, pagina) -> None:
        try:
            pagina.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        pagina.wait_for_timeout(900)

    # ------------------------------------------------------------------ leitura
    def instantaneo(self, parte: int = 1) -> str:
        pagina = self._garantir()
        try:
            dados = pagina.evaluate(_JS_INSTANTANEO, MAX_ELEMENTOS)
        except Exception:
            self._aguardar(pagina)  # a página pode estar no meio de uma navegação
            dados = pagina.evaluate(_JS_INSTANTANEO, MAX_ELEMENTOS)
        texto = re.sub(r"\n{3,}", "\n\n", dados["texto"]).strip()
        total = max(1, -(-len(texto) // TAMANHO_TEXTO))
        parte = max(1, min(total, parte))
        trecho = texto[(parte - 1) * TAMANHO_TEXTO : parte * TAMANHO_TEXTO]
        linhas = [f"URL: {dados['url']}", f"Título: {dados['titulo']}"]
        if dados["captcha"] or _RE_VERIFICACAO.search(texto[:3000]):
            linhas.append(AVISO_CAPTCHA)
        linhas.append(f"--- Texto visível (parte {parte} de {total}) ---")
        linhas.append(trecho or "(página sem texto)")
        linhas.append("--- Elementos interativos (use o número entre colchetes) ---")
        linhas.extend(_descrever(item) for item in dados["itens"])
        if not dados["itens"]:
            linhas.append("(nenhum elemento interativo visível)")
        elif len(dados["itens"]) >= MAX_ELEMENTOS:
            linhas.append("(lista truncada; role a página para ver mais)")
        self._salvar_captura_atual(pagina)
        return "\n".join(linhas)

    def _salvar_captura_atual(self, pagina) -> None:
        """Mantém uma imagem do que o agente está vendo, exibida no painel."""
        if self.amb.pagamento_autorizado:
            return  # nunca fotografar formulários de pagamento
        try:
            pagina.screenshot(path=str(self.cfg.dir_capturas / "atual.png"), timeout=5000)
        except Exception:
            pass

    def _elemento(self, pagina, indice: int):
        alvo = pagina.locator(f'[data-ea="{int(indice)}"]')
        if alvo.count() == 0:
            raise ValueError(
                f"elemento [{indice}] não existe na página atual. Use navegador_ler para ver os números atualizados"
            )
        return alvo.first

    # ------------------------------------------------------------------ ações
    def abrir(self, url: str) -> str:
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
            url = "https://" + url

        def acao() -> str:
            pagina = self._garantir()
            try:
                pagina.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as erro:
                if "Timeout" not in str(erro):
                    raise
            self._aguardar(pagina)
            return self.instantaneo()

        return self._executar(acao)

    def ler(self, parte: int = 1) -> str:
        return self._executar(lambda: self.instantaneo(parte))

    def clicar(self, indice: int) -> str:
        def acao() -> str:
            pagina = self._garantir()
            alvo = self._elemento(pagina, indice)
            try:
                alvo.scroll_into_view_if_needed(timeout=3000)
                alvo.click(timeout=8000)
            except Exception:
                alvo.evaluate("el => el.click()")  # elemento coberto por outro: clique direto
            self._aguardar(self._pagina or pagina)
            return self.instantaneo()

        return self._executar(acao)

    def digitar(self, indice: int, texto: str, enviar: bool = False) -> str:
        def acao() -> str:
            pagina = self._garantir()
            alvo = self._elemento(pagina, indice)
            try:
                alvo.fill(texto, timeout=8000)
            except Exception:
                alvo.click(timeout=5000)
                pagina.keyboard.press("Control+A")
                pagina.keyboard.type(texto, delay=20)
            if enviar:
                alvo.press("Enter")
                self._aguardar(self._pagina or pagina)
                return self.instantaneo()
            return f"Texto digitado no elemento [{indice}]."

        return self._executar(acao)

    def selecionar(self, indice: int, opcao: str) -> str:
        def acao() -> str:
            pagina = self._garantir()
            alvo = self._elemento(pagina, indice)
            try:
                alvo.select_option(label=opcao, timeout=5000)
            except Exception:
                alvo.select_option(value=opcao, timeout=5000)
            return f"Opção '{opcao}' selecionada no elemento [{indice}]."

        return self._executar(acao)

    def tecla(self, tecla: str) -> str:
        def acao() -> str:
            pagina = self._garantir()
            pagina.keyboard.press(tecla)
            self._aguardar(self._pagina or pagina)
            return self.instantaneo()

        return self._executar(acao)

    def rolar(self, direcao: str = "baixo") -> str:
        def acao() -> str:
            pagina = self._garantir()
            delta = -800 if direcao.lower().startswith("c") else 800
            pagina.mouse.wheel(0, delta)
            pagina.wait_for_timeout(700)
            return self.instantaneo()

        return self._executar(acao)

    def voltar(self) -> str:
        def acao() -> str:
            pagina = self._garantir()
            pagina.go_back(wait_until="domcontentloaded", timeout=30000)
            self._aguardar(pagina)
            return self.instantaneo()

        return self._executar(acao)

    def enviar_arquivo(self, indice: int, caminho: Path) -> str:
        def acao() -> str:
            pagina = self._garantir()
            self._elemento(pagina, indice).set_input_files(str(caminho))
            return f"Arquivo anexado ao elemento [{indice}]."

        return self._executar(acao)

    def captura(self, nome: str) -> str:
        def acao() -> str:
            pagina = self._garantir()
            seguro = re.sub(r"[^a-zA-Z0-9_-]", "_", nome or "") or time.strftime("captura_%Y%m%d_%H%M%S")
            destino = self.cfg.dir_capturas / f"{seguro}.png"
            pagina.screenshot(path=str(destino), full_page=True)
            return f"Captura de tela salva em {destino}"

        return self._executar(acao)


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    from .pagamento import resolver_marcadores
    from .sistema import resolver_caminho

    nav = Navegador(amb)
    amb.navegador = nav

    @cat.ferramenta(
        "navegador_abrir",
        "Abre uma URL no navegador real e devolve o texto da página com os elementos interativos numerados.",
        _grupo="navegador",
        url=P("string", "Endereço a abrir."),
    )
    def navegador_abrir(url: str) -> str:
        return nav.abrir(url)

    @cat.ferramenta(
        "navegador_ler",
        "Relê a página atual do navegador (texto e elementos numerados).",
        _grupo="navegador",
        parte=P("integer", "Parte do texto quando a página é longa (padrão 1).", obrigatorio=False),
    )
    def navegador_ler(parte: int = 1) -> str:
        return nav.ler(parte)

    @cat.ferramenta(
        "navegador_clicar",
        "Clica no elemento com o número informado e devolve a página resultante.",
        _grupo="navegador",
        indice=P("integer", "Número do elemento, como aparece entre colchetes."),
    )
    def navegador_clicar(indice: int) -> str:
        return nav.clicar(indice)

    @cat.ferramenta(
        "navegador_digitar",
        "Digita um texto em um campo da página. Com enviar=true pressiona Enter depois.",
        _grupo="navegador",
        indice=P("integer", "Número do campo."),
        texto=P("string", "Texto a digitar."),
        enviar=P("boolean", "Pressionar Enter após digitar (padrão false).", obrigatorio=False),
    )
    def navegador_digitar(indice: int, texto: str, enviar: bool = False) -> str:
        return nav.digitar(indice, resolver_marcadores(amb, texto), enviar)

    @cat.ferramenta(
        "navegador_selecionar",
        "Escolhe uma opção em um campo de seleção (lista suspensa).",
        _grupo="navegador",
        indice=P("integer", "Número do campo de seleção."),
        opcao=P("string", "Texto da opção desejada."),
    )
    def navegador_selecionar(indice: int, opcao: str) -> str:
        return nav.selecionar(indice, resolver_marcadores(amb, opcao))

    @cat.ferramenta(
        "navegador_tecla",
        "Pressiona uma tecla na página (por exemplo Enter, Tab, Escape, ArrowDown).",
        _grupo="navegador",
        tecla=P("string", "Nome da tecla."),
    )
    def navegador_tecla(tecla: str) -> str:
        return nav.tecla(tecla)

    @cat.ferramenta(
        "navegador_rolar",
        "Rola a página para carregar ou ver mais conteúdo.",
        _grupo="navegador",
        direcao=P("string", "Direção da rolagem.", obrigatorio=False, enum=["baixo", "cima"]),
    )
    def navegador_rolar(direcao: str = "baixo") -> str:
        return nav.rolar(direcao)

    @cat.ferramenta("navegador_voltar", "Volta para a página anterior do histórico.", _grupo="navegador")
    def navegador_voltar() -> str:
        return nav.voltar()

    @cat.ferramenta(
        "navegador_enviar_arquivo",
        "Anexa um arquivo da pasta de trabalho a um campo de envio de arquivo da página.",
        _grupo="navegador",
        indice=P("integer", "Número do campo de envio de arquivo."),
        caminho=P("string", "Caminho do arquivo, relativo à pasta de trabalho."),
    )
    def navegador_enviar_arquivo(indice: int, caminho: str) -> str:
        alvo = resolver_caminho(amb.cfg.dir_trabalho, caminho)
        if not alvo.is_file():
            return f"ERRO: arquivo não encontrado: {caminho}"
        return nav.enviar_arquivo(indice, alvo)

    @cat.ferramenta(
        "navegador_captura",
        "Salva uma imagem da página atual (registro visual para o dono).",
        _grupo="navegador",
        nome=P("string", "Nome do arquivo, sem extensão.", obrigatorio=False),
    )
    def navegador_captura(nome: str = "") -> str:
        return nav.captura(nome)

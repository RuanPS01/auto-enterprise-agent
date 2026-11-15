---
name: construcao-de-software
description: Como construir o produto da empresa em passos pequenos e testados, escolhendo tecnologias que rodam em hospedagem gratuita. Use em qualquer tarefa de engenharia.
area: programacao
---

# Construção de software

## Princípios

- Um projeto por pasta dentro da pasta de trabalho, com git desde o primeiro arquivo.
- Passos pequenos: escreva, rode, confira, registre no git. Nunca escreva o sistema inteiro antes de executar algo.
- Prefira a tecnologia mais simples que resolve. Menos peças significa menos falhas em uma operação sem humanos.
- Segredos nunca entram no código nem no git. Use variáveis de ambiente e um arquivo `.env` listado no `.gitignore`.

## Escolha de tecnologia pensando em custo zero

- **Site ou aplicação só de navegador**: HTML, CSS e JavaScript estáticos. É a opção mais fácil de hospedar de graça e a mais robusta. Dados do usuário podem ficar no próprio navegador (localStorage, IndexedDB).
- **Aplicação com servidor**: funções sem servidor ou um serviço pequeno em Python (FastAPI) ou Node. Confira os limites do plano gratuito antes de escolher a hospedagem.
- **Banco de dados**: SQLite para serviços que rodam na máquina do agente; bancos gerenciados com plano gratuito para o que roda na nuvem.
- **Serviço rodando na máquina do agente**: use servico_iniciar para manter no ar e um túnel gratuito para expor (ver a habilidade publicacao-gratuita).

## Roteiro de uma tarefa de engenharia

1. listar_arquivos para ver o estado do projeto. Leia o README do projeto, se existir.
2. Faça a menor mudança que avança o objetivo.
3. Execute e teste com executar_comando. Para sites, suba um servidor local (por exemplo `python -m http.server 8000` com servico_iniciar) e abra no navegador para conferir.
4. Corrija até funcionar. Leia a mensagem de erro inteira antes de mudar o código.
5. `git add -A && git commit -m "mensagem clara"`.
6. Atualize o README do projeto com: o que é, como rodar, como publicar, o que falta.
7. Salve na memória (categoria tecnico) onde o projeto está e como rodá-lo.

## Qualidade mínima antes de publicar

- Funciona no celular (layout responsivo) e carrega rápido.
- Textos claros, sem erros, no idioma do público.
- Página com contato da empresa e política de privacidade simples e verdadeira.
- Nenhum segredo no repositório: confira com `git grep -n -i -E "senha|password|token|secret|api_key"`.
- Formulários validam a entrada e mostram mensagens de erro compreensíveis.

## Comandos úteis

- Novo repositório: `git init -b main`
- Identidade do git da empresa: `git config user.name "NOME"` e `git config user.email "EMAIL"`
- Ambiente Python isolado: `python -m venv .venv` e depois use `.venv/bin/python` (no Windows: `.venv\Scripts\python`)
- Instalação sem perguntas: `npm install --no-audit --no-fund`, `pip install -q pacote`

Comandos não podem pedir entrada interativa. Use sempre as opções que respondem "sim" automaticamente.

## Habilidades e extensões que aprofundam

- Antes de escrever código novo: spec-driven-development e incremental-implementation.
- Erro que não se resolve: systematic-debugging. Função nova ou correção: test-driven-development.
- Antes de dar por pronto: verification-before-completion e code-review-and-quality.
- Interface: frontend-design, frontend-ui-engineering e web-design-guidelines. Testar no navegador: webapp-testing.
- API: api-and-interface-design. Desempenho: performance-optimization. Segurança: seguranca-defensiva.
- Documentação atual de uma biblioteca: ative o grupo ext_context7 e consulte antes de usar uma API de que não tem certeza.
- Depurar o site em um navegador (console, rede, desempenho): grupo ext_chrome_devtools, com filtro.


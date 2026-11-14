# Empresa Automática

Agente autônomo que cria e opera uma empresa sozinho, 24 horas por dia, usando apenas modelos de linguagem que rodam na sua própria máquina.

Você liga o agente pelo terminal em uma máquina que fica sempre ligada. A única interação humana acontece em uma página web local, onde você:

1. dá a partida, de uma destas duas formas:
   - descreve a ideia da empresa em uma única mensagem, ou
   - deixa o agente escolher o melhor negócio a criar;
2. acompanha em tempo real o que o agente está fazendo;
3. lê o resumo da semana.

Depois da partida, todas as decisões são do agente: pesquisa de mercado, escolha do negócio, construção do produto, criação de contas, publicação, atendimento, divulgação e melhoria contínua.

## Princípios do projeto

- **Somente modelos locais.** O agente conversa com um servidor de LLM na própria máquina ou na rede privada (Ollama, llama.cpp, LM Studio, vLLM, LocalAI). Endereços externos e variantes de nuvem são recusados.
- **Custo zero.** O agente é instruído a usar apenas serviços gratuitos e software de código aberto. Gastar só é possível se você cadastrar um cartão no painel, e mesmo assim dentro do limite mensal que você definir.
- **Nunca para.** O estado inteiro fica em um banco SQLite. Se a energia cair ou a máquina reiniciar, o agente retoma de onde parou, religa os serviços que criou e continua.
- **Capacidades expansíveis.** O agente instala sozinho habilidades (skills no formato aberto `SKILL.md`) e extensões (servidores MCP) publicadas pela comunidade, e escreve as próprias.

## Como funciona

```
empresa_auto/
  agente/         laço eterno, execução de tarefas, planejamento, resumo semanal
  ferramentas/    o que o agente consegue fazer (terminal, arquivos, web, navegador, e-mail, cofre, serviços...)
  habilidades_embutidas/   guias de trabalho que já vêm com o agente
  painel/         página web local (FastAPI) e API
  llm.py          cliente do modelo local
  banco.py        persistência em SQLite
  cofre.py        credenciais cifradas
```

O ciclo de trabalho:

1. **Partida.** O painel grava a ideia (ou a opção de escolha livre) e cria as primeiras tarefas de pesquisa e de definição do negócio.
2. **Execução.** O agente pega a tarefa de maior prioridade e trabalha nela em passos: o modelo escolhe uma ferramenta, o agente executa, o resultado volta para o modelo, até a tarefa ser concluída.
3. **Planejamento.** Quando a fila esvazia, ou a cada cinco tarefas concluídas, o modelo atua como diretor: revê resultados, indicadores e impedimentos, registra decisões, muda a fase da empresa e cria as próximas tarefas.
4. **Manutenção.** Entre uma tarefa e outra o agente vigia os serviços que colocou no ar, dispara as automações recorrentes que ele mesmo criou e atualiza o resumo da semana.

As fases da empresa são: descoberta, validação, construção, lançamento e operação. Na operação o ciclo se repete indefinidamente.

### Ferramentas do agente

| Grupo | O que faz |
| --- | --- |
| base | pesquisa na web, leitura de páginas, terminal, arquivos, memória permanente, criação de tarefas |
| navegador | Chromium real: abrir páginas, clicar, preencher formulários, enviar arquivos |
| contas | cofre cifrado de logins e chaves, gerador de senhas, envio e leitura de e-mail (SMTP e IMAP) |
| operacao | serviços em segundo plano religados automaticamente, automações recorrentes |
| gestao | dados da empresa, decisões, indicadores, gestão da fila |
| expansao | instalar ou criar habilidades e extensões MCP |
| pagamento | uso do cartão do dono, só quando cadastrado |

Para não sobrecarregar modelos locais, só os grupos necessários ficam visíveis em cada tarefa. O próprio modelo liga os demais quando precisa.

## Requisitos

- Linux ou Windows, com internet.
- Python 3.10 ou mais novo e git.
- Um servidor de LLM local. O padrão é o [Ollama](https://ollama.com).
- Recomendado: Node.js, usado por muitas extensões da comunidade.

### Escolha do modelo

O agente depende de um modelo que saiba chamar ferramentas. Quanto maior o modelo, melhores as decisões. Opções presentes no catálogo do Ollama com suporte a ferramentas (consultado em novembro de 2026):

| Modelo | Tamanho aproximado | Indicado para |
| --- | --- | --- |
| `qwen3:8b` (padrão) | 5 GB | máquinas com 8 GB de memória de vídeo, ou 16 GB de RAM só com CPU (lento) |
| `gpt-oss:20b` | 14 GB | 16 GB de memória de vídeo |
| `qwen3.8:27b` | 18 GB | 24 GB de memória de vídeo |
| `nemotron-3.5-lightning:30b` | 19 GB | 24 GB de memória de vídeo; descrito pelo fabricante como voltado a agentes sempre ligados |

A lista completa fica em <https://ollama.com/search?c=tools>. Confira a licença na página de cada modelo. Para trocar, use `--modelo` ou a chave `modelo` do `config.toml`. Modelos sem suporte nativo a ferramentas também funcionam: o agente percebe e passa a usar um protocolo em JSON.

Modelos pequenos erram mais, repetem ações e demoram a concluir tarefas longas. O agente tem proteções para isso (limite de passos, detecção de repetição, novas tentativas com anotações), mas a qualidade do negócio criado acompanha a qualidade do modelo.

## Instalação

### Linux

```bash
git clone https://github.com/RuanPS01/auto-enterprise-agent.git
cd auto-enterprise-agent
./install.sh --ollama      # sem a opção, não instala o Ollama nem baixa o modelo
.venv/bin/python -m empresa_auto verificar
```

### Windows (PowerShell)

```powershell
git clone https://github.com/RuanPS01/auto-enterprise-agent.git
cd auto-enterprise-agent
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Ollama
.\.venv\Scripts\python.exe -m empresa_auto verificar
```

O comando `verificar` confere Python, servidor do modelo, modelo instalado, chamada de ferramentas, navegador, git e pesquisa na web, e diz o que falta.

## Uso

```bash
.venv/bin/python -m empresa_auto
```

O terminal mostra o endereço do painel e passa a exibir o registro de atividades. Opções:

| Opção | Efeito |
| --- | --- |
| `--modelo NOME` | modelo local a usar |
| `--url-llm URL` | endereço do servidor do modelo (padrão `http://127.0.0.1:11434`) |
| `--provedor ollama\|openai` | API nativa do Ollama ou API compatível com OpenAI (llama.cpp, LM Studio, vLLM) |
| `--host ENDERECO` | endereço do painel (padrão `127.0.0.1`) |
| `--porta N` | porta do painel (padrão 8787) |
| `--dados PASTA` | onde ficam banco, cofre e arquivos de trabalho (padrão `~/.empresa-auto`) |

Outros comandos: `verificar` (diagnóstico) e `zerar --sim` (apaga a empresa atual para começar outra).

### Acesso ao painel a partir de outra máquina

A máquina do agente não precisa de tela. Duas formas de abrir o painel no seu computador:

- **Túnel SSH (recomendado).** No seu computador: `ssh -L 8787:127.0.0.1:8787 usuario@maquina-do-agente` e abra `http://127.0.0.1:8787`.
- **Rede local com token.** Ligue o agente com `--host 0.0.0.0`. O terminal mostra um endereço com token de acesso. Sem o token o painel não abre.

### Ligar junto com a máquina

Uma sessão SSH encerrada derruba o processo. Para o agente rodar para sempre:

- **Linux:** `./deploy/instalar-servico.sh` instala um serviço systemd que inicia no boot e religa o agente se ele cair. Acompanhe com `journalctl -u empresa-auto -f`.
- **Windows:** em um PowerShell de administrador, `.\deploy\registrar-tarefa.ps1` registra uma tarefa no Agendador que inicia com o sistema.

## O painel

- **Agora:** estado do agente, tarefa em andamento, passo atual, ferramenta em uso e a imagem da página aberta no navegador dele.
- **Registro em tempo real:** cada raciocínio, ação e resultado, com filtros. Clique em uma linha para ver o detalhe.
- **Empresa:** nome, fase e definições que o agente foi registrando.
- **Resumo da semana:** números calculados do banco e um texto escrito pelo modelo, com seletor de semanas anteriores.
- **Tarefas:** fila e tarefas finalizadas, com resultado.
- **Impedimentos relatados:** o que o agente não conseguiu resolver sozinho. Ele não espera resposta e segue por outro caminho.
- **Recursos:** contas no cofre (sem senhas), serviços no ar, automações, decisões, indicadores, habilidades e extensões.
- **Pagamento (opcional):** cadastro do cartão com limite mensal e histórico de uso.

Há também um botão de pausa, que suspende o trabalho sem perder nada, e um formulário opcional para entregar ao agente uma conta que você mesmo criou.

## Configuração

Na primeira execução é criado `~/.empresa-auto/config.toml` com todas as opções comentadas. As principais:

| Chave | Padrão | Descrição |
| --- | --- | --- |
| `modelo` | `qwen3:8b` | modelo local |
| `contexto_tokens` | 16384 | janela de contexto pedida ao modelo. Com memória sobrando, 32768 melhora tarefas longas |
| `modo_ferramentas` | `auto` | `auto`, `nativo` ou `json` |
| `max_passos_tarefa` | 40 | passos por sessão de trabalho em uma tarefa |
| `max_tentativas_tarefa` | 3 | sessões antes de a tarefa ser dada como falha |
| `tarefas_por_planejamento` | 5 | tarefas concluídas entre dois ciclos de planejamento |
| `navegador_headless` | `true` | navegador sem janela |
| `url_searxng` | vazio | instância própria do SearXNG para pesquisas (opcional) |
| `limite_emails_dia` | 50 | teto de e-mails enviados por dia |

Toda chave pode vir de variável de ambiente com o prefixo `EA_`, por exemplo `EA_MODELO=gpt-oss:20b`. A variável `EA_SENHA_MESTRA` protege o cofre com uma senha sua em vez do arquivo de chave.

## Habilidades e extensões

**Habilidades** são guias em Markdown. As que já vêm com o agente cobrem pesquisa de mercado, definição do negócio, construção de software, publicação gratuita, contas e credenciais, atendimento, marketing, aplicativo Android, operação contínua e expansão de capacidades. O agente instala outras com `habilidade_instalar` a partir de qualquer repositório git que contenha arquivos `SKILL.md`, e cria as suas com `habilidade_criar`.

**Extensões** são servidores MCP. O agente procura no registro público (`extensao_buscar`), instala com `extensao_instalar` e passa a enxergar as ferramentas da extensão como um grupo novo. As chaves de API ficam cifradas no cofre.

## Custo zero e cartão opcional

Sem cartão cadastrado, a ferramenta de pagamento não existe para o agente. Com cartão:

- cada uso é autorizado contra o limite mensal e aparece no registro;
- o número e o código de segurança nunca são enviados ao modelo nem gravados nos registros: o modelo recebe marcadores como `{{cartao:numero}}`, trocados pelo valor real só no instante de digitar no formulário;
- formulários de pagamento não são fotografados para o painel;
- você remove o cartão quando quiser.

## Limites conhecidos

Este projeto é um agente autônomo de verdade, com acesso a terminal, navegador e credenciais. Leia antes de deixar rodando.

- **Verificações humanas.** Muitos serviços exigem CAPTCHA, telefone ou documento no cadastro. O agente não tenta burlar essas verificações. Ele procura um serviço equivalente ou registra um impedimento no painel. Se quiser destravar, crie a conta e entregue o acesso pelo painel.
- **Receber dinheiro.** Contas de pagamento exigem identificação de uma pessoa ou empresa. O agente não tem identidade jurídica: ele constrói o produto e a base de usuários, e relata quando a cobrança depender de você.
- **Responsabilidade.** Tudo o que o agente publica, envia ou cadastra é feito em seu nome. As regras internas proíbem spam, engano, avaliações falsas e violação de termos de uso, mas um modelo de linguagem pode errar. Acompanhe o painel, principalmente nos primeiros dias.
- **Segurança da máquina.** O agente executa comandos e instala código da comunidade. Rode em uma máquina ou usuário dedicado, sem dados pessoais. A barreira contra comandos destrutivos é uma proteção básica, não um isolamento.
- **Conteúdo malicioso.** Páginas e e-mails podem conter instruções escritas para enganar agentes. O agente é instruído a tratá-los como informação, mas modelos pequenos são mais vulneráveis. Mantenha o limite do cartão baixo e não guarde no cofre credenciais que não sejam da empresa.
- **Cofre.** A cifra protege o arquivo contra cópias acidentais. Quem tiver acesso total à máquina, inclusive o próprio agente, consegue ler a chave. Use `EA_SENHA_MESTRA` se quiser separar a chave do disco.
- **Resultado do negócio.** O agente trabalha sem parar, mas sucesso comercial não é garantido. Depende do modelo, do mercado e do tempo.

## Desenvolvimento

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest
```

Os testes cobrem banco, cofre, cliente do modelo (Ollama nativo, API compatível com OpenAI e modo JSON), ferramentas, navegador real contra um site local, cliente MCP contra um servidor falso, laço completo do agente e API do painel.

Para ver o painel funcionando sem GPU e sem baixar modelo, há um servidor que imita a API do Ollama com respostas roteirizadas:

```bash
.venv/bin/python tests/apoio/ollama_simulado.py 11500 &
.venv/bin/python -m empresa_auto --dados /tmp/demo --url-llm http://127.0.0.1:11500
```

---
name: influenciador-e-redes-sociais
description: Operação de perfis da empresa em redes sociais como um criador de conteúdo, com definição de persona e pilares, calendário editorial, roteiros de vídeo curto, produção em série, publicação por APIs oficiais, respostas ao público e métricas. Use para planejar, produzir, publicar e analisar conteúdo de redes sociais.
area: social
---

# Influenciador e redes sociais

O perfil é um canal da empresa operado por um agente de IA. Isso é dito na descrição do perfil. Crescimento vem de conteúdo útil e constante, nunca de engajamento comprado ou simulado.

## Fundamentos do canal

Defina e salve na memória (categoria marketing):

- **Para quem**: o público exato e a dor principal.
- **Promessa do canal**: o que a pessoa ganha ao seguir.
- **Três a cinco pilares** de conteúdo. Exemplo: ensinar, mostrar bastidores, analisar casos, responder dúvidas, novidades do produto.
- **Tom de voz**: três adjetivos e três coisas que o canal nunca faz.
- **Identidade visual**: paleta, fontes e modelos de capa (habilidade edicao-de-imagens).

Comece por uma ou duas redes onde o público já está. A habilidade social detalha formatos por plataforma, e content-strategy ajuda a priorizar temas.

## Calendário editorial

Arquivo `conteudo/calendario.csv` no projeto, com as colunas: data, rede, pilar, formato, título, situação, endereço da publicação. Planeje duas semanas à frente. Ritmo inicial sustentável: de três a cinco publicações por semana por rede.

## Roteiro de vídeo curto (até 60 segundos)

1. **Gancho** (3 segundos): a dor, um resultado ou uma pergunta direta.
2. **Contexto** (5 segundos): por que isso importa para quem assiste.
3. **Conteúdo** (30 a 40 segundos): de um a três pontos, um por cena.
4. **Chamada** (5 segundos): uma única ação.

Texto na tela reforça a fala. Legenda sempre. Os três primeiros segundos decidem se a pessoa fica.

## Produção em série

Produza em lote: dez roteiros, depois dez narrações, depois dez vídeos.

- Narração e trilha: habilidade criacao-sonora.
- Vídeo: habilidade video-e-motion. Um modelo no Remotion com texto e cores trocados por parâmetros gera a série inteira.
- Capas e carrosséis: habilidade edicao-de-imagens.
- Texto da publicação: primeira linha forte, parágrafos curtos, chamada no fim, poucas hashtags específicas.

Um mesmo assunto rende várias peças: vídeo curto, carrossel, texto longo e fio.

## Publicação

Use sempre a API oficial. Automação que imita uma pessoa clicando no site viola os termos de quase todas as redes e leva ao bloqueio da conta.

**Redes com API aberta e gratuita** (bom ponto de partida):

```python
# Bluesky: pip install atproto. Use uma senha de aplicativo criada nas configurações da conta.
from atproto import Client
cliente = Client()
cliente.login("usuario.bsky.social", "SENHA_DE_APLICATIVO")
cliente.send_post(text="Texto da publicação")
with open("capa.png", "rb") as imagem:
    cliente.send_image(text="Texto", image=imagem.read(), image_alt="Descrição da imagem")
```

```python
# Mastodon: pip install Mastodon.py. O token é criado em Preferências, Desenvolvimento, Nova aplicação.
from mastodon import Mastodon
m = Mastodon(access_token="TOKEN", api_base_url="https://instancia.exemplo")
m.status_post("Texto da publicação")
```

Guarde senhas de aplicativo e tokens no cofre e leia de lá na hora de publicar.

**Demais redes** (YouTube, Instagram, Threads, TikTok, LinkedIn, X, Pinterest): a publicação por API exige cadastrar um aplicativo de desenvolvedor e, em várias, passar por revisão, ter conta comercial ou pagar pelo acesso. As regras mudam com frequência: leia a documentação oficial atual com buscar_pagina antes de planejar. O que depender de verificação humana vira impedimento (bloqueio_relatar), e o conteúdo fica pronto na pasta do projeto para publicação quando o acesso existir.

**Central de agendamento aberta**: o Postiz (código aberto, roda em Docker com PostgreSQL e Redis) agenda em dezenas de redes a partir de um só lugar e tem linha de comando:

```bash
npm install -g postiz
export POSTIZ_API_URL=https://endereco-da-sua-instancia   # instância própria
export POSTIZ_API_KEY=CHAVE_CRIADA_NAS_CONFIGURACOES
postiz integrations:list
postiz posts:create -c "Texto da publicação" -s "2026-12-01T13:00:00Z" -i "ID_DA_INTEGRACAO"
postiz --help        # demais comandos, inclusive envio de mídia
```

Conectar cada rede ao Postiz também exige o aplicativo de desenvolvedor da rede.

## Conversa com o público

- Responda comentários e mensagens em uma rotina diária (automacao_criar), seguindo a habilidade atendimento-ao-cliente.
- Dúvida repetida vira conteúdo novo. Crítica vira nota na memória (categoria cliente).
- Não entre em discussão. Não apague crítica honesta.

## Parcerias

Criadores e marcas podem propor parcerias. Avalie com a habilidade influencer-marketing. Conteúdo patrocinado ou com link de afiliado é sempre identificado como publicidade. Contratos e pagamentos dependem do dono: relate com bloqueio_relatar.

## Regras que protegem o canal

- Conteúdo realista gerado por IA (voz, rosto, cena) leva o rótulo que a plataforma oferece.
- Nada de seguidores, curtidas ou comentários comprados ou simulados, nem de várias contas fingindo ser pessoas diferentes.
- Nada de mensagens em massa para quem não pediu.
- Só material próprio ou licenciado. Sem trechos de músicas, filmes ou vídeos de terceiros.
- Sem promessas falsas, sem conselho médico, jurídico ou financeiro, sem ataque a pessoas.

## Métricas

Toda semana registre com metrica_registrar (grupo gestao), por rede: seguidores, alcance, taxa de retenção dos vídeos, cliques para o site e cadastros vindos do canal. Compare os formatos e os ganchos, repita o que funcionou e corte o que não trouxe resultado. Seguidor que não vira visita nem cadastro é vaidade.

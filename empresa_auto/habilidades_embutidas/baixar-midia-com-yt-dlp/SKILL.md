---
name: baixar-midia-com-yt-dlp
description: Uso do yt-dlp para ler metadados, baixar legendas e transcrições para pesquisa, e baixar vídeo ou áudio de conteúdo próprio ou com licença livre, respeitando direitos autorais. Use para estudar vídeos de concorrentes e do público, reaproveitar vídeos da própria empresa e obter material em domínio público ou Creative Commons.
area: midia
---

# Baixar mídia com yt-dlp

O yt-dlp é um programa aberto que lê e baixa mídia de centenas de sites. É poderoso, e por isso o uso tem regras.

## O que é permitido

| Uso | Pode? |
| --- | --- |
| Ler metadados (título, duração, visualizações, descrição) para pesquisa de mercado | Sim |
| Baixar legendas e transcrições para analisar o que concorrentes e o público dizem | Sim, para análise interna |
| Baixar vídeos e áudios publicados pela própria empresa (cópia de segurança, reaproveitamento) | Sim |
| Baixar material em domínio público ou com licença Creative Commons que permita o uso pretendido | Sim, guardando a licença e a atribuição |
| Republicar, cortar ou remixar vídeo, música ou áudio de terceiros sem licença | Não |
| Remover marca d'água, contornar proteção contra cópia, área paga ou conteúdo privado | Não |

Os termos de uso de várias plataformas restringem o download. Para conteúdo próprio, prefira o recurso de exportação da plataforma ou a API oficial quando existir. Na dúvida sobre a licença, use o material só como referência de estudo e produza o seu.

## Instalação

```bash
uv tool install yt-dlp          # ou: pip install -U yt-dlp
yt-dlp --version
```

Precisa do ffmpeg para juntar vídeo e áudio e para converter formatos. Sites mudam com frequência: se um download falhar, atualize com `uv tool upgrade yt-dlp`.

## Pesquisa sem baixar o vídeo

```bash
# metadados principais, inclusive a licença declarada
yt-dlp --dump-json --skip-download "URL" | jq '{title, uploader, upload_date, duration, view_count, like_count, license, description}'

# listar os vídeos de um canal ou de uma lista
yt-dlp --flat-playlist --print "%(id)s | %(title)s | %(view_count)s" "URL_DO_CANAL"

# legendas (as enviadas pelo autor e as automáticas) em SRT, sem o vídeo
yt-dlp --skip-download --write-subs --write-auto-subs --sub-langs "pt.*,en.*" --convert-subs srt -o "%(id)s.%(ext)s" "URL"
```

Com as legendas em texto dá para estudar roteiros, ganchos e assuntos que funcionam, e levar as conclusões para a memória (categoria mercado). Sem legenda disponível, baixe só o áudio e transcreva com a receita da habilidade criacao-sonora.

## Baixar conteúdo próprio ou com licença livre

```bash
# confirmar a licença antes
yt-dlp --print "%(license)s | %(uploader)s | %(title)s" --skip-download "URL"

# vídeo em MP4 até 1080p
yt-dlp -f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]" -o "%(title)s [%(id)s].%(ext)s" "URL"

# só o áudio em MP3
yt-dlp -x --audio-format mp3 -o "%(title)s [%(id)s].%(ext)s" "URL"

# só um trecho
yt-dlp --download-sections "*00:01:00-00:02:30" -o "trecho.%(ext)s" "URL"

# cópia de segurança de um canal próprio, sem repetir o que já baixou
yt-dlp --download-archive baixados.txt -o "%(upload_date)s %(title)s [%(id)s].%(ext)s" "URL_DO_CANAL"
```

O campo de licença nem sempre vem preenchido. Abra a página e confirme a licença escrita pelo autor. "Creative Commons" tem variantes: as com NC proíbem uso comercial, as com ND proíbem modificações, e todas exigem atribuição.

## Boas práticas

- Baixe só o necessário e com pausa entre pedidos (`--sleep-interval 3`) para não sobrecarregar o site.
- Guarde junto do arquivo um texto com o endereço de origem, o autor, a licença e a data.
- Depois de baixar, trate com ffmpeg (habilidade video-e-motion) e transcreva com Whisper (habilidade criacao-sonora).
- Material de terceiros usado como referência de estudo fica fora de repositórios públicos e de qualquer publicação.

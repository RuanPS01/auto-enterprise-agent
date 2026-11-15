---
name: video-e-motion
description: Produção de vídeo e motion graphics por código e linha de comando, escolhendo entre HyperFrames, Remotion, Manim e ffmpeg, com receitas para cortar, juntar, legendar, converter para vertical, sonorizar e exportar para cada rede. Use para criar ou editar qualquer vídeo da empresa.
area: midia
---

# Vídeo e motion graphics

O agente não usa editor com janelas. Vídeo profissional sai de código (animação declarada em arquivos) e de ffmpeg (corte, montagem e finalização). Confira em AMBIENTE se ffmpeg e node estão instalados.

## Qual ferramenta

| Objetivo | Ferramenta |
| --- | --- |
| Motion graphics, vinhetas, vídeos de produto, texto animado, legendas animadas | **HyperFrames** (HTML e CSS, licença Apache 2.0, sem taxa por uso). Leia a habilidade hyperframes |
| O mesmo, quando o projeto já usa React ou precisa de componentes do ecossistema | **Remotion** (React). Leia a habilidade remotion-best-practices |
| Animação explicativa com gráficos, fórmulas e diagramas | **Manim** (Python) |
| Cortar, juntar, converter, legendar, sonorizar, exportar | **ffmpeg** |
| Gravar o produto funcionando | script Playwright com gravação de vídeo (habilidade webapp-testing) |
| Estudar vídeos de referência, ou baixar material próprio ou com licença livre | habilidade baixar-midia-com-yt-dlp |
| Cenas geradas por IA (pessoas, produtos, cenários realistas) | habilidades higgsfield, só com conta paga fornecida pelo dono |
| Decidir o formato e o roteiro | habilidade video (marketing) |

HyperFrames, Remotion e Manim renderizam só com processador. HyperFrames exige Node.js 22 ou mais novo e ffmpeg, e é a escolha padrão por ser totalmente aberto. Remotion é gratuito para pessoas e empresas pequenas e pago acima disso: leia remotion-license antes do primeiro uso.

## HyperFrames em três comandos

```bash
npx hyperframes init meu-video
cd meu-video
npx hyperframes render          # gera o MP4; npx hyperframes preview abre a pré-visualização
```

A habilidade hyperframes-cli traz os demais comandos e hyperframes-registry lista os blocos prontos (transições, títulos, legendas, gráficos).

## Fluxo de produção

1. **Roteiro** em texto: gancho nos três primeiros segundos, uma ideia por cena, chamada final.
2. **Narração** (habilidade criacao-sonora) e medição da duração: `ffprobe -v error -show_entries format=duration -of csv=p=0 fala.wav`.
3. **Animação** no tempo da narração.
4. **Montagem e finalização** com ffmpeg: trilha, legenda, normalização do áudio.
5. **Conferência**: extraia quadros e olhe as medidas e a duração antes de publicar.
6. **Exportação** no formato de cada rede.

## Remotion em três comandos

```bash
npx create-video@latest --yes --blank --no-tailwind meu-video
cd meu-video
npx remotion render [id-da-composicao] out/video.mp4
```

Detalhes de animação, legendas e renderização estão nas habilidades remotion-create, remotion-markup, remotion-captions e remotion-render.

## Manim

```bash
uv tool install manim          # exige ffmpeg e as bibliotecas cairo e pango do sistema
manim -qh cena.py NomeDaCena   # -ql rascunho rápido, -qh alta definição, -qk 4K
```

O arquivo sai em `media/videos/`.

## Receitas de ffmpeg

```bash
# informações do arquivo
ffprobe -v error -show_format -show_streams entrada.mp4

# cortar um trecho com precisão
ffmpeg -i entrada.mp4 -ss 00:00:10 -to 00:00:25 -c:v libx264 -crf 20 -c:a aac corte.mp4

# juntar arquivos de mesmo formato (lista.txt com linhas: file 'a.mp4')
ffmpeg -f concat -safe 0 -i lista.txt -c copy junto.mp4

# horizontal para vertical 9:16, cortando o centro
ffmpeg -i entrada.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" -c:a copy vertical.mp4

# vertical com fundo desfocado, sem cortar o conteúdo
ffmpeg -i entrada.mp4 -filter_complex "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20[fundo];[0:v]scale=1080:-2[frente];[fundo][frente]overlay=(W-w)/2:(H-h)/2" -c:a copy vertical.mp4

# queimar legendas no vídeo
ffmpeg -i video.mp4 -vf "subtitles=legenda.srt:force_style='FontSize=18,Outline=2,MarginV=60'" -c:a copy legendado.mp4

# imagem parada com áudio
ffmpeg -loop 1 -i capa.png -i audio.mp3 -c:v libx264 -tune stillimage -pix_fmt yuv420p -c:a aac -b:a 192k -shortest video.mp4

# sequência de imagens para vídeo
ffmpeg -framerate 30 -i quadro_%04d.png -c:v libx264 -pix_fmt yuv420p video.mp4

# música de fundo baixa sob o áudio original
ffmpeg -i video.mp4 -i musica.mp3 -filter_complex "[1:a]volume=0.15[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]" -map 0:v -map "[a]" -c:v copy -c:a aac final.mp4

# exportação final para a web
ffmpeg -i entrada.mov -c:v libx264 -crf 22 -preset medium -pix_fmt yuv420p -movflags +faststart -c:a aac -b:a 160k saida.mp4

# capa a partir de um quadro e GIF de demonstração
ffmpeg -ss 5 -i video.mp4 -frames:v 1 capa.jpg
ffmpeg -i clipe.mp4 -vf "fps=12,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" demo.gif
```

## Formatos de entrega

| Destino | Proporção | Resolução |
| --- | --- | --- |
| Vídeos curtos verticais (Reels, Shorts, TikTok) | 9:16 | 1080x1920 |
| Vídeo horizontal (YouTube, site) | 16:9 | 1920x1080 |
| Quadrado para feed | 1:1 | 1080x1080 |

Use 30 quadros por segundo, H.264 com `yuv420p` e áudio AAC. Duração e tamanho máximos mudam: confira as regras atuais da rede antes de enviar. Vídeo curto precisa de legenda, porque muita gente assiste sem som.

## Legendas

Gere o arquivo SRT a partir do áudio com a receita de transcrição da habilidade criacao-sonora, revise o texto e queime no vídeo, ou use remotion-captions para legendas animadas.

## Direitos

Use apenas material próprio, gerado pela empresa ou com licença que permita uso comercial. Guarde na memória a origem e a licença de cada trilha, imagem e fonte usada. Vídeo com pessoas, vozes ou cenas sintéticas realistas deve ser rotulado como gerado por IA, como as plataformas exigem.

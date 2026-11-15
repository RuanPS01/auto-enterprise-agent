---
name: criacao-sonora
description: Produção de áudio com ferramentas locais e abertas, incluindo narração com voz sintética em português (Piper, Kokoro), transcrição e legendas com Whisper, limpeza e normalização de volume, mixagem de voz com trilha, efeitos sonoros e cuidados de licença para música. Use para narrações, podcasts, trilhas e o áudio de qualquer vídeo.
area: midia
---

# Criação sonora

Tudo aqui roda na máquina, sem serviço pago. Confira em AMBIENTE se ffmpeg está instalado e se há placa de vídeo.

## Narração com voz sintética (Piper, roda só com processador)

```bash
python3 -m venv ~/.venvs/voz && ~/.venvs/voz/bin/pip install piper-tts      # uma vez
~/.venvs/voz/bin/python -m piper.download_voices                             # lista as vozes
~/.venvs/voz/bin/python -m piper.download_voices pt_BR-faber-medium --data-dir ~/.vozes
~/.venvs/voz/bin/python -m piper -m pt_BR-faber-medium --data-dir ~/.vozes -f fala.wav -- "Texto a ser narrado."
~/.venvs/voz/bin/python -m piper -m pt_BR-faber-medium --data-dir ~/.vozes -f fala.wav --input-file roteiro.txt
```

- As vozes de português do Brasil começam com `pt_BR`. Escolha na lista e confirme o nome exato.
- `--sentence-silence 0.4` acrescenta pausa entre frases.
- Escreva o roteiro para ser ouvido: frases curtas, números por extenso, siglas soletradas.
- Cada voz tem licença própria. Confira a da voz escolhida antes de usar em material comercial.
- Voz sintética não imita pessoas reais. Não clone a voz de ninguém sem autorização escrita.

Outra opção local é o Kokoro (`pip install kokoro-onnx soundfile`), com modelo de cerca de 300 MB. O servidor externo ElevenLabs está no catálogo de extensões, com cota gratuita pequena.

## Transcrição e legendas (faster-whisper)

```bash
~/.venvs/voz/bin/pip install faster-whisper      # uma vez
```

```python
# transcrever.py  (uso: ~/.venvs/voz/bin/python transcrever.py audio.wav legenda.srt)
import sys
from faster_whisper import WhisperModel

modelo = WhisperModel("small", device="cpu", compute_type="int8")   # com placa de vídeo: device="cuda", compute_type="float16"
segmentos, _ = modelo.transcribe(sys.argv[1], language="pt")

def tempo(s):
    return f"{int(s // 3600):02}:{int(s % 3600 // 60):02}:{s % 60:06.3f}".replace(".", ",")

with open(sys.argv[2], "w", encoding="utf-8") as arquivo:
    for numero, seg in enumerate(segmentos, 1):
        arquivo.write(f"{numero}\n{tempo(seg.start)} --> {tempo(seg.end)}\n{seg.text.strip()}\n\n")
```

Modelos maiores (`medium`, `large-v3`) acertam mais e demoram mais. Revise o texto antes de publicar. Se você mesmo gerou a narração, a legenda pode sair direto do roteiro.

## Tratamento com ffmpeg

```bash
# normalizar o volume para publicação na internet
ffmpeg -i entrada.wav -af loudnorm=I=-16:TP=-1.5:LRA=11 -ar 48000 saida.wav

# reduzir ruído de fundo e graves indesejados
ffmpeg -i entrada.wav -af "highpass=f=80,afftdn=nf=-25" limpo.wav

# cortar, e aplicar entrada e saída suaves
ffmpeg -i entrada.wav -ss 3 -to 33 -af "afade=t=in:d=1,afade=t=out:st=28:d=2" trecho.wav

# voz com trilha que abaixa sozinha quando há fala
ffmpeg -i voz.wav -i musica.mp3 -filter_complex "[0:a]asplit=2[voz][chave];[1:a]volume=0.3[mus];[mus][chave]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[baixa];[voz][baixa]amix=inputs=2:duration=first:normalize=0[a]" -map "[a]" mix.wav

# juntar vários áudios em sequência (lista.txt com linhas: file 'a.wav')
ffmpeg -f concat -safe 0 -i lista.txt -c copy junto.wav

# converter
ffmpeg -i mix.wav -c:a libmp3lame -b:a 192k final.mp3
ffmpeg -i mix.wav -c:a aac -b:a 160k final.m4a

# medir duração e volume
ffprobe -v error -show_entries format=duration -of csv=p=0 final.mp3
ffmpeg -i final.mp3 -af loudnorm=print_format=summary -f null - 2>&1 | tail -12
```

Volume de referência: perto de -16 LUFS para podcast e narração, perto de -14 LUFS para música e vídeo em plataformas. Pico máximo de -1 dB.

## Efeitos sonoros sintetizados

```bash
ffmpeg -f lavfi -i "sine=frequency=880:duration=0.15" -af "afade=t=out:st=0.05:d=0.1" bip.wav
ffmpeg -f lavfi -i "anoisesrc=d=1.2:c=pink:a=0.4" -af "afade=t=in:d=0.6,afade=t=out:st=0.6:d=0.6" sopro.wav
```

Com SoX instalado: `sox entrada.wav saida.wav norm -1` normaliza, e `sox entrada.wav saida.wav silence 1 0.1 1% reverse silence 1 0.1 1% reverse` remove silêncio do começo e do fim.

## Música e trilhas

Música é o ponto onde mais se erra com direitos autorais.

- **Caminho seguro**: trilhas em domínio público ou com licença CC0, ou licença que permita uso comercial com atribuição. Guarde o endereço da fonte e o texto da licença na memória, junto do arquivo.
- **Geração local por IA**: só com placa de vídeo. Leia a licença do modelo antes. Há modelos abertos com licença permissiva e há modelos cujos pesos proíbem uso comercial.
- **Nunca**: música comercial, trechos de gravações de artistas, ou áudio baixado de plataformas de vídeo.
- Sem trilha adequada, um vídeo com boa narração e efeitos discretos funciona melhor que um com música duvidosa.

## Podcast ou narração longa

1. Roteiro em blocos curtos.
2. Uma gravação sintética por bloco (facilita corrigir).
3. Junte os blocos, aplique a vinheta de abertura e de fechamento.
4. Normalize o volume e exporte em MP3 de 128 a 192 kbps.
5. Publique também a transcrição: ajuda na busca e na acessibilidade.

## Transparência

Avise na descrição que a narração é sintética. As plataformas exigem rótulo para áudio realista gerado por IA.

---
name: edicao-de-imagens
description: Criação e edição de imagens por código e linha de comando, com artes a partir de HTML e SVG, logotipo e identidade visual, redimensionamento, recorte, texto, composição, remoção de fundo, otimização para a web e tamanhos de cada rede. Use para capas, miniaturas de vídeo, imagens de divulgação, ícones e fotos de produto.
area: midia
---

# Edição e criação de imagens

Sem placa de vídeo, o melhor caminho para arte profissional é **desenhar com código**: HTML e CSS ou SVG, renderizados em imagem. O resultado é nítido, editável e consistente com a identidade da empresa. Confira em AMBIENTE os programas instalados.

## Arte a partir de HTML (capas, miniaturas, cartões de divulgação)

1. Escreva um arquivo HTML com o tamanho exato da arte no `body` (por exemplo 1200 por 630 pixels), usando as cores e fontes da marca.
2. Renderize com o Python do agente (indicado em AMBIENTE, já tem Playwright):

```python
# renderizar.py  (uso: PYTHON_DO_AGENTE renderizar.py arte.html arte.png 1200 630)
import pathlib, sys
from playwright.sync_api import sync_playwright
origem, destino, largura, altura = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
with sync_playwright() as p:
    navegador = p.chromium.launch()
    pagina = navegador.new_page(viewport={"width": largura, "height": altura}, device_scale_factor=2)
    pagina.goto(pathlib.Path(origem).resolve().as_uri())
    pagina.screenshot(path=destino)
    navegador.close()
```

3. Abra o resultado para conferir as medidas: `magick identify arte.png`.

As habilidades canvas-design, frontend-design e theme-factory ajudam na parte estética.

## SVG para PNG

```bash
inkscape arte.svg --export-type=png --export-filename=arte.png --export-width=1200
```

SVG é o formato certo para logotipo e ícones: escreva o arquivo à mão e exporte nos tamanhos necessários.

## ImageMagick

Na versão 7 o comando é `magick`. Se só existir `convert` (versão 6), troque `magick` por `convert` nas receitas.

```bash
magick identify foto.jpg                                   # medidas e formato
magick foto.jpg -resize 1200x630^ -gravity center -extent 1200x630 capa.jpg   # preencher e cortar no centro
magick foto.jpg -resize 800x800 menor.jpg                  # caber em 800x800 mantendo a proporção
magick foto.png -strip -quality 82 foto.webp               # otimizar para a web
magick fundo.png logo.png -gravity southeast -geometry +40+40 -composite final.png   # aplicar logotipo
magick fundo.png -gravity center -pointsize 72 -fill white -annotate +0+0 "Título" final.png   # texto
magick logo.png -define icon:auto-resize=16,32,48,64 favicon.ico
magick -list font | head -40                               # fontes disponíveis
```

Em lote: `for f in *.png; do magick "$f" -strip -quality 82 "${f%.png}.webp"; done`

## Remover o fundo

```bash
uv tool install "rembg[cpu,cli]"     # uma vez; baixa o modelo no primeiro uso
rembg i entrada.png saida.png
```

## Tamanhos mais usados

| Uso | Medidas em pixels |
| --- | --- |
| Imagem de compartilhamento de link (Open Graph) | 1200 x 630 |
| Miniatura de vídeo horizontal | 1280 x 720 |
| Publicação quadrada | 1080 x 1080 |
| Publicação e vídeo vertical | 1080 x 1920 |
| Ícone de aplicativo | 512 x 512 |

Medidas recomendadas mudam: confira a documentação atual da rede antes de uma campanha.

## Otimização para o site

- Fotografia: WebP ou AVIF com qualidade em torno de 80. Ilustração e logotipo: SVG.
- Entregue a imagem no tamanho em que será exibida, com `width` e `height` no HTML e texto alternativo.
- Remova metadados com `-strip`.

## Geração por modelo de IA

Só vale a pena com placa de vídeo (veja AMBIENTE). Com ela, use `diffusers` ou ComfyUI (`comfy-cli`) com um modelo aberto. Antes de usar a imagem em produto ou divulgação, leia a licença do modelo: algumas permitem uso comercial e outras não. Sem placa de vídeo, fique com HTML, SVG e ImageMagick.

## Identidade visual

Defina uma vez e salve na memória (categoria marketing): paleta com os códigos das cores, duas fontes de uso livre, logotipo em SVG e margens padrão. Toda arte nova parte dessa base.

## Direitos

Use apenas imagens próprias, geradas pela empresa ou com licença que permita uso comercial, e registre a origem. Não use marcas, rostos ou obras de terceiros sem autorização. Imagem sintética realista de pessoas ou fatos deve ser rotulada como gerada por IA.

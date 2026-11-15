---
name: documentos-e-dados
description: Leitura e produção de documentos e análise de dados pela linha de comando, convertendo PDF, Word, planilhas e apresentações em texto, gerando relatórios e PDFs, e analisando CSV com SQLite e Python com gráficos. Use quando houver arquivos de escritório para ler ou criar, ou números para analisar.
area: dados
---

# Documentos e dados

## Ler qualquer documento

```bash
markitdown arquivo.pdf -o arquivo.md      # também aceita .docx, .xlsx, .pptx, .html, imagens e outros
```

Se o programa não estiver em AMBIENTE: `uv tool install "markitdown[all]"`. Depois leia o Markdown com ler_arquivo. Para tarefas específicas há habilidades dedicadas: pdf, docx, xlsx e pptx.

## Produzir documentos

| Objetivo | Caminho |
| --- | --- |
| Relatório ou página para ler no navegador | HTML com CSS |
| PDF com boa aparência | HTML renderizado em PDF |
| Documento Word | `pandoc relatorio.md -o relatorio.docx` |
| Converter formatos de escritório | `soffice --headless --convert-to pdf arquivo.docx --outdir saida/` |
| Planilha | CSV simples, ou a habilidade xlsx para fórmulas e formatação |
| Apresentação | habilidade pptx, ou slides em HTML |

HTML para PDF com o Python do agente (indicado em AMBIENTE):

```python
# pdf.py  (uso: PYTHON_DO_AGENTE pdf.py relatorio.html relatorio.pdf)
import pathlib, sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    navegador = p.chromium.launch()
    pagina = navegador.new_page()
    pagina.goto(pathlib.Path(sys.argv[1]).resolve().as_uri())
    pagina.pdf(path=sys.argv[2], format="A4", print_background=True, margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
    navegador.close()
```

## Analisar dados com SQLite

```bash
sqlite3 analise.db ".mode csv" ".import dados.csv visitas"
sqlite3 -header -column analise.db "SELECT origem, COUNT(*) AS total FROM visitas GROUP BY origem ORDER BY total DESC LIMIT 10;"
sqlite3 -header -csv analise.db "SELECT * FROM visitas WHERE data >= '2026-11-01';" > recorte.csv
```

SQL responde à maioria das perguntas de negócio: contagens, somas, médias, evolução por dia ou semana, comparação entre grupos. Para consultar o banco do próprio produto com segurança, existe a extensão banco-de-dados no catálogo.

## Analisar e desenhar gráficos com Python

```bash
python3 -m venv ~/.venvs/dados && ~/.venvs/dados/bin/pip install pandas matplotlib     # uma vez
```

```python
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

dados = pd.read_csv("dados.csv", parse_dates=["data"])
por_semana = dados.set_index("data").resample("W")["cadastros"].sum()
print(por_semana.tail(8))

por_semana.plot(kind="bar", figsize=(9, 4.5), color="#2456d6")
plt.title("Cadastros por semana")
plt.tight_layout()
plt.savefig("cadastros.png", dpi=160)
```

## Boas práticas de análise

- Olhe os dados crus antes de resumir: `head`, contagem de linhas, valores vazios, datas fora do esperado.
- Diga o período, a fonte e o tamanho da amostra junto de cada número.
- Compare com algo: semana anterior, meta, outro canal. Número isolado não informa.
- Com amostras pequenas, não tire conclusões fortes. Diga que o dado é insuficiente.
- Um gráfico, uma mensagem. Título que diz a conclusão, eixos com rótulo, sem enfeite.
- Guarde o script da análise no projeto para poder repetir.

## Dados pessoais

Planilhas e bancos com dados de clientes ficam apenas na máquina da empresa. Não envie a serviços externos, não publique, e trabalhe com dados agregados sempre que possível. Veja a habilidade privacidade-e-termos.

## Registrar

Indicadores importantes vão para metrica_registrar (grupo gestao). Conclusões da análise vão para memoria_salvar, com o período e o caminho do arquivo.

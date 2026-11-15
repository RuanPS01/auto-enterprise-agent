# Instalador da Empresa Automática para Windows (PowerShell).
#
#   .\install.ps1             instala o agente e o navegador
#   .\install.ps1 -Ollama     também instala o Ollama (via winget) e baixa o modelo padrão
#   .\install.ps1 -Completo   também instala os programas usados pelas habilidades de mídia e
#                             infraestrutura (ffmpeg, ImageMagick, Node.js, uv, jq)
#
# Se o PowerShell bloquear a execução:  powershell -ExecutionPolicy Bypass -File .\install.ps1
param([switch]$Ollama, [switch]$Completo, [string]$Modelo = "qwen3:8b")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Dizer($texto) { Write-Host "`n== $texto" }

Dizer "Conferindo o Python"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python não encontrado. Instale o Python 3.10 ou mais novo:  winget install Python.Python.3.12"
    exit 1
}
python -c "import sys; assert sys.version_info >= (3, 10), 'É necessário Python 3.10 ou mais novo'; print('Python', sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { exit 1 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Aviso: git não encontrado. Instale com:  winget install Git.Git"
}

Dizer "Criando o ambiente virtual e instalando o agente"
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -e .
if ($LASTEXITCODE -ne 0) { exit 1 }

Dizer "Instalando o navegador Chromium"
& .\.venv\Scripts\python.exe -m playwright install chromium

if ($Completo) {
    Dizer "Instalando os programas do perfil completo"
    foreach ($pacote in @("Gyan.FFmpeg", "ImageMagick.ImageMagick", "OpenJS.NodeJS.LTS", "astral-sh.uv", "jqlang.jq")) {
        winget install --id $pacote -e --accept-source-agreements --accept-package-agreements | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "  ok     $pacote" } else { Write-Host "  falhou $pacote (instale manualmente se precisar)" }
    }
    Write-Host "As demais ferramentas são instaladas pelo próprio agente quando uma tarefa precisar."
}

if ($Ollama) {
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Dizer "Instalando o Ollama"
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    }
    Dizer "Baixando o modelo $Modelo (pode demorar)"
    ollama pull $Modelo
} elseif (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "`nO Ollama não está instalado. Instale com:  winget install Ollama.Ollama"
    Write-Host "ou rode este instalador novamente com:     .\install.ps1 -Ollama"
}

Dizer "Pronto"
Write-Host "Verifique a máquina:   .\.venv\Scripts\python.exe -m empresa_auto verificar"
Write-Host "Ligue o agente:        .\.venv\Scripts\python.exe -m empresa_auto"
Write-Host "Ligar junto com o Windows:   .\deploy\registrar-tarefa.ps1"

# Registra o agente no Agendador de Tarefas do Windows: liga junto com a máquina,
# sem precisar de sessão aberta, e é reiniciado se cair.
# Execute em um PowerShell aberto como administrador.
param([string]$Nome = "EmpresaAutomatica", [string]$Argumentos = "")

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Ambiente virtual não encontrado. Rode .\install.ps1 primeiro."
    exit 1
}

$acao = New-ScheduledTaskAction -Execute $python -Argument "-m empresa_auto $Argumentos" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -AtStartup
$usuario = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType S4U -RunLevel Limited
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $Nome -Action $acao -Trigger $gatilho -Principal $principal -Settings $ajustes -Force | Out-Null
Start-ScheduledTask -TaskName $Nome

Write-Host "Tarefa '$Nome' registrada e iniciada."
Write-Host "Situação:  Get-ScheduledTask -TaskName $Nome | Get-ScheduledTaskInfo"
Write-Host "Parar:     Stop-ScheduledTask -TaskName $Nome"
Write-Host "Remover:   Unregister-ScheduledTask -TaskName $Nome -Confirm:`$false"

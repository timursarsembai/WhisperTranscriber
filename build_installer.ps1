# Сборка EXE (Python 3.12) и установщика в installer_output.
# Требуется: Python 3.12 (для Whisper-Streaming), Inno Setup 6.

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$InnoPath = "C:\Users\Timsar\AppData\Local\Programs\Inno Setup 6\ISCC.exe"

# Поиск Python 3.12
$Python312 = $null
$candidates = @(
    (Get-Command python -ErrorAction SilentlyContinue).Source,
    $env:PYTHON312_PATH,
    "C:\Users\Timsar\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Python312\python.exe",
    "C:\Program Files\Python312\python.exe"
)
foreach ($c in $candidates) {
    if (-not $c) { continue }
    try {
        $v = & $c --version 2>&1
        if ($v -match "3\.12\.\d+") {
            $Python312 = $c
            break
        }
    } catch {}
}
if (-not $Python312) {
    Write-Host "Python 3.12 не найден. Установите с https://www.python.org/downloads/release/python-3120/" -ForegroundColor Red
    Write-Host "Добавьте в PATH или задайте переменную PYTHON312_PATH." -ForegroundColor Yellow
    exit 1
}
Write-Host "Используется Python 3.12: $Python312"

Set-Location $ProjectRoot

# 1) PyInstaller
Write-Host "`n--- Сборка EXE (PyInstaller) ---" -ForegroundColor Cyan
& $Python312 build.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 2) Inno Setup
if (-not (Test-Path $InnoPath)) {
    Write-Host "Inno Setup не найден: $InnoPath" -ForegroundColor Red
    exit 1
}
Write-Host "`n--- Сборка установщика (Inno Setup) ---" -ForegroundColor Cyan
& $InnoPath "WhisperTranscriber.iss"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nГотово. Установщик: installer_output\WhisperTranscriber_Setup.exe" -ForegroundColor Green

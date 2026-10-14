#Requires -Version 5.1
<#
.SYNOPSIS
    Installa Place4You Automation per la propria scrivania.
.DESCRIPTION
    Scarica la repo, installa uv se mancante, crea il collegamento
    sul desktop e avvia il wizard di configurazione scrivania.
.EXAMPLE
    irm https://raw.githubusercontent.com/Alfred042024/place4you-automation/master/install.ps1 | iex
#>

$RepoUrl    = "https://github.com/Alfred042024/place4you-automation.git"
$InstallDir = "$env:USERPROFILE\place4you-automation"
$Desktop    = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Place4You.lnk"

function Write-Step { param($msg) Write-Host "`n  >> $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "     $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "     $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "     ERRORE: $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |   Place4You  -  Installazione automatica |" -ForegroundColor Cyan
Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# ── 1. Verifica / installa uv ────────────────────────────────────────
Write-Step "Verifico uv..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Warn "uv non trovato, installo..."
    try {
        powershell -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
        $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            Write-Ok "uv installato."
        } else {
            Write-Fail "Impossibile installare uv automaticamente."
            Write-Warn "Installa manualmente da https://docs.astral.sh/uv/getting-started/installation/"
            Write-Warn "Poi riesegui questo script."
            exit 1
        }
    } catch {
        Write-Fail "Errore durante l'installazione di uv: $_"
        exit 1
    }
} else {
    Write-Ok "uv trovato: $(uv --version)"
}

# ── 2. Scarica / aggiorna la repo ────────────────────────────────────
Write-Step "Scarico Place4You..."
if (Test-Path $InstallDir) {
    Write-Warn "Cartella gia presente, aggiorno..."
    try {
        git -C $InstallDir pull --ff-only 2>&1 | Out-Null
        Write-Ok "Aggiornato."
    } catch {
        Write-Warn "git pull fallito, continuo con la versione esistente."
    }
} else {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Warn "Scarico con git..."
        git clone $RepoUrl $InstallDir 2>&1 | Out-Null
    } else {
        Write-Warn "git non trovato, scarico come ZIP..."
        $zip = "$env:TEMP\place4you.zip"
        Invoke-WebRequest -Uri "https://github.com/Alfred042024/place4you-automation/archive/refs/heads/master.zip" `
                          -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath "$env:TEMP\place4you-extract" -Force
        $extracted = Get-ChildItem "$env:TEMP\place4you-extract" | Select-Object -First 1
        Move-Item $extracted.FullName $InstallDir -Force
        Remove-Item $zip -Force
    }

    if (-not (Test-Path $InstallDir)) {
        Write-Fail "Download fallito. Scarica manualmente da $RepoUrl"
        exit 1
    }
    Write-Ok "Scaricato in $InstallDir"
}

# ── 3. Installa Chromium (solo prima volta) ──────────────────────────
Write-Step "Verifico Chromium per Playwright..."
$chromePath = "$env:LOCALAPPDATA\ms-playwright\chromium-1243\chrome-win64\chrome.exe"
if (-not (Test-Path $chromePath)) {
    Write-Warn "Prima esecuzione: installo Chromium (~200 MB)..."
    Push-Location $InstallDir
    uv run book_desk.py --help 2>$null | Out-Null
    Pop-Location
    $uvEnv = Get-ChildItem "$env:LOCALAPPDATA\uv\cache\environments-v2" -Filter "book-desk-*" |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($uvEnv) {
        & "$($uvEnv.FullName)\Scripts\python.exe" -m playwright install chromium 2>&1 | Out-Null
        Write-Ok "Chromium installato."
    } else {
        Write-Warn "Chromium verra installato al primo avvio."
    }
} else {
    Write-Ok "Chromium gia presente."
}

# ── 4. Collegamento sul desktop ──────────────────────────────────────
Write-Step "Creo collegamento sul desktop..."
$ps1Path = Join-Path $InstallDir "p4y.ps1"
try {
    $ws  = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($ShortcutPath)
    $lnk.TargetPath       = "powershell.exe"
    $lnk.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$ps1Path`""
    $lnk.WorkingDirectory = $InstallDir
    $lnk.Description      = "Place4You - Prenotazione scrivania"
    $lnk.Save()
    Write-Ok "Collegamento creato: $ShortcutPath"
} catch {
    Write-Warn "Impossibile creare il collegamento: $_"
    Write-Warn "Crealo manualmente puntando a: $ps1Path"
}

# ── 5. Avvio wizard ──────────────────────────────────────────────────
Write-Host ""
Write-Host "  +------------------------------------------+" -ForegroundColor Green
Write-Host "  |   Installazione completata!              |" -ForegroundColor Green
Write-Host "  +------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Avvio il wizard di configurazione..." -ForegroundColor White
Write-Host "  Tieni pronto il cartellino con il QR della tua scrivania." -ForegroundColor Yellow
Write-Host ""
Start-Sleep -Seconds 2

Push-Location $InstallDir
uv run book_desk.py --setup
Pop-Location

Write-Host ""
Write-Host "  Ora esegui il login SSO. Si aprira un browser." -ForegroundColor Cyan
$doLogin = Read-Host "  Eseguire il login adesso? [S/N]"
if ($doLogin.ToUpper() -eq "S") {
    Push-Location $InstallDir
    uv run book_desk.py --login
    Pop-Location
}

Write-Host ""
Write-Host "  Tutto pronto! Usa il collegamento 'Place4You' sul desktop." -ForegroundColor Green
Write-Host ""

#Requires -Version 5.1
<#
.SYNOPSIS
    Installa Place4You Automation per la propria scrivania.
.DESCRIPTION
    Scarica la repo, installa uv se mancante, crea il collegamento
    sul desktop e avvia il wizard di configurazione scrivania.
.PARAMETER Url
    URL dell'istanza Place4You (es. https://p4y.tuaazienda.it).
    Se omesso, viene chiesto durante il setup.
.EXAMPLE
    # Generico (chiede l'URL durante il setup):
    irm https://raw.githubusercontent.com/Alfred042024/place4you-automation/master/install.ps1 | iex

    # Con URL pre-configurato (nessuna domanda sull'URL):
    & ([scriptblock]::Create((irm 'https://raw.githubusercontent.com/Alfred042024/place4you-automation/master/install.ps1'))) -Url "https://p4y.tuaazienda.it"
#>
param(
    [string]$Url = ""
)

$RepoUrl    = "https://github.com/Alfred042024/place4you-automation.git"
$InstallDir = "$env:USERPROFILE\place4you-automation"
$Desktop    = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Place4You.lnk"

function Write-Step { param($msg) Write-Host "`n  >> $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "     $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "     $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "     ERRORE: $msg" -ForegroundColor Red }

# Tutto in una funzione: 'return' ferma lo script senza chiudere la finestra
# PowerShell dell'utente (succede con 'exit' quando si usa irm | iex).
function Install-Place4You {
    Write-Host ""
    Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |   Place4You  -  Installazione automatica |" -ForegroundColor Cyan
    Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""

    # -- 1. Verifica / installa uv ---------------------------------------
    Write-Step "Verifico uv..."
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Warn "uv non trovato, installo..."
        try {
            powershell -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
            $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
        } catch {
            Write-Fail "Errore durante l'installazione di uv: $_"
            return
        }
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            Write-Ok "uv installato."
        } else {
            Write-Fail "Impossibile installare uv automaticamente."
            Write-Warn "Installa manualmente da https://docs.astral.sh/uv/getting-started/installation/"
            Write-Warn "Poi riesegui questo script."
            return
        }
    } else {
        Write-Ok "uv trovato: $(uv --version)"
    }

    # -- 2. Scarica / aggiorna la repo -----------------------------------
    Write-Step "Scarico Place4You..."
    if (Test-Path $InstallDir) {
        if (Test-Path (Join-Path $InstallDir ".git")) {
            Write-Warn "Cartella gia presente, aggiorno..."
            git -C $InstallDir pull --ff-only 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "Aggiornato."
            } else {
                Write-Warn "Aggiornamento non riuscito, continuo con la versione esistente."
            }
        } else {
            Write-Warn "Installazione da ZIP: per aggiornare cancella $InstallDir e rilancia l'installer."
        }
    } else {
        if (Get-Command git -ErrorAction SilentlyContinue) {
            Write-Warn "Scarico con git..."
            git clone $RepoUrl $InstallDir 2>&1 | Out-Null
        } else {
            Write-Warn "git non trovato, scarico come ZIP..."
            $zip        = "$env:TEMP\place4you.zip"
            $extractDir = "$env:TEMP\place4you-extract"
            try {
                Invoke-WebRequest -Uri "https://github.com/Alfred042024/place4you-automation/archive/refs/heads/master.zip" `
                                  -OutFile $zip -UseBasicParsing
                Expand-Archive -Path $zip -DestinationPath $extractDir -Force
                $extracted = Get-ChildItem $extractDir | Select-Object -First 1
                Move-Item $extracted.FullName $InstallDir -Force
            } catch {
                Write-Fail "Download ZIP fallito: $_"
            } finally {
                Remove-Item $zip -Force -ErrorAction SilentlyContinue
                Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }

        if (-not (Test-Path $InstallDir)) {
            Write-Fail "Download fallito. Scarica manualmente da $RepoUrl"
            return
        }
        Write-Ok "Scaricato in $InstallDir"
    }

    # -- 3. Installa Chromium (idempotente) ------------------------------
    Write-Step "Verifico Chromium per Playwright..."
    Push-Location $InstallDir
    uv run book_desk.py --install-browser
    $chromiumOk = ($LASTEXITCODE -eq 0)
    Pop-Location
    if ($chromiumOk) {
        Write-Ok "Chromium pronto."
    } else {
        Write-Warn "Installazione Chromium non riuscita. Riprova: uv run book_desk.py --install-browser"
    }

    # -- 4. Collegamento sul desktop -------------------------------------
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

    # -- 5. Avvio wizard -------------------------------------------------
    Write-Host ""
    Write-Host "  +------------------------------------------+" -ForegroundColor Green
    Write-Host "  |   Installazione completata!              |" -ForegroundColor Green
    Write-Host "  +------------------------------------------+" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Avvio il wizard di configurazione..." -ForegroundColor White
    Write-Host "  Tieni pronto il cartellino con il QR della tua scrivania." -ForegroundColor Yellow
    Write-Host ""

    # Pre-compila l'URL se passato con -Url. UTF-8 SENZA BOM: Python
    # sotto Windows non parsa il BOM scritto da Set-Content -Encoding UTF8.
    $configPath = Join-Path $InstallDir "desk_config.json"
    if ($Url -and -not (Test-Path $configPath)) {
        Write-Step "Pre-configurazione URL: $Url"
        $json = [PSCustomObject]@{ base_url = $Url.TrimEnd('/') } | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding($false)))
        Write-Ok "URL impostato."
    }

    Start-Sleep -Seconds 2

    # Il wizard propone da solo il login se manca la sessione, cosi
    # puo rilevare floor/room/company/build dal server.
    Push-Location $InstallDir
    uv run book_desk.py --setup
    Pop-Location

    if (-not (Test-Path (Join-Path $InstallDir "auth_state.json"))) {
        Write-Host ""
        $doLogin = Read-Host "  Login SSO non ancora eseguito. Farlo adesso? [S/N]"
        if ($doLogin.ToUpper() -eq "S") {
            Push-Location $InstallDir
            uv run book_desk.py --login
            Pop-Location
            Write-Warn "Per rilevare floor/room/company/build rilancia la voce [6] Configura scrivania."
        }
    }

    Write-Host ""
    Write-Host "  Tutto pronto! Usa il collegamento 'Place4You' sul desktop." -ForegroundColor Green
    Write-Host ""
}

Install-Place4You

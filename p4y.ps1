#Requires -Version 5.1
param([string]$Action = "")

$ScriptDir = $PSScriptRoot
$PyScript  = Join-Path $ScriptDir "book_desk.py"
$AuthFile  = Join-Path $ScriptDir "auth_state.json"

function Write-Title {
    Write-Host ""
    Write-Host "  +--------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |   Place4You  -  Scrivania ABS16      |" -ForegroundColor Cyan
    Write-Host "  +--------------------------------------+" -ForegroundColor Cyan
    if (Test-Path $AuthFile) {
        Write-Host "  [OK] sessione presente" -ForegroundColor Green
    } else {
        Write-Host "  [!] nessuna sessione - esegui Login prima" -ForegroundColor Yellow
    }
    Write-Host ""
}

function Run-Py {
    param([string[]]$PyArgs)
    & uv run $PyScript @PyArgs
    return $LASTEXITCODE
}

function Ensure-Chromium {
    $chromePath = "$env:LOCALAPPDATA\ms-playwright\chromium-1243\chrome-win64\chrome.exe"
    if (Test-Path $chromePath) { return }
    Write-Host "  Prima esecuzione: installo Chromium (~200 MB)..." -ForegroundColor Yellow
    $envDir = "$env:LOCALAPPDATA\uv\cache\environments-v2"
    $uvEnv  = Get-ChildItem $envDir -Filter "book-desk-*" |
              Sort-Object LastWriteTime -Descending |
              Select-Object -First 1
    if ($null -eq $uvEnv) {
        Write-Host "  Inizializzo ambiente uv..." -ForegroundColor Yellow
        & uv run --no-project $PyScript --help 2>$null
        $uvEnv = Get-ChildItem $envDir -Filter "book-desk-*" |
                 Sort-Object LastWriteTime -Descending |
                 Select-Object -First 1
    }
    if ($null -ne $uvEnv) {
        & "$($uvEnv.FullName)\Scripts\python.exe" -m playwright install chromium
    } else {
        Write-Host "  [!] Impossibile trovare l'ambiente uv. Esegui: uv run book_desk.py --login" -ForegroundColor Red
    }
}

function Do-Login {
    Write-Host "  Login SSO Microsoft in corso..." -ForegroundColor Yellow
    Run-Py "--login"
}

function Do-BookToday {
    Write-Host "  Prenoto oggi (1 giorno)..." -ForegroundColor Cyan
    Run-Py "--book", "--today", "--days", "1"
}

function Do-Book7 {
    Write-Host "  Prenoto i prossimi 7 giorni lavorativi..." -ForegroundColor Cyan
    Run-Py "--book", "--today", "--days", "7"
}

function Do-Book30 {
    Write-Host "  Prenoto i prossimi 30 giorni lavorativi..." -ForegroundColor Cyan
    Run-Py "--book", "--today", "--days", "30"
}

function Do-Checkin {
    Write-Host "  Check-in oggi..." -ForegroundColor Cyan
    Run-Py "--checkin"
}

function Do-Setup {
    Write-Host "  Avvio wizard configurazione scrivania..." -ForegroundColor Magenta
    Run-Py "--setup"
}

function Show-Menu {
    Write-Title
    Write-Host "  Cosa vuoi fare?" -ForegroundColor White
    Write-Host ""
    Write-Host "  [1] Prenota oggi" -ForegroundColor Green
    Write-Host "  [2] Prenota 7 giorni lavorativi" -ForegroundColor Green
    Write-Host "  [3] Prenota 30 giorni lavorativi" -ForegroundColor Green
    Write-Host "  [4] Check-in oggi" -ForegroundColor Yellow
    Write-Host "  [5] Login SSO (primo setup o sessione scaduta)" -ForegroundColor Magenta
    Write-Host "  [6] Configura scrivania (prima installazione)" -ForegroundColor DarkCyan
    Write-Host "  [Q] Esci" -ForegroundColor DarkGray
    Write-Host ""
    $choice = Read-Host "  Scelta"
    Write-Host ""
    switch ($choice.ToUpper()) {
        "1"     { Do-BookToday }
        "2"     { Do-Book7 }
        "3"     { Do-Book30 }
        "4"     { Do-Checkin }
        "5"     { Do-Login }
        "6"     { Do-Setup }
        "Q"     { return }
        default { Write-Host "  Scelta non valida." -ForegroundColor Red; Show-Menu; return }
    }
    Write-Host ""
    $again = Read-Host "  Altro? [S/N]"
    if ($again.ToUpper() -eq "S") { Show-Menu }
}

Ensure-Chromium

switch ($Action.ToLower()) {
    "login"   { Write-Title; Do-Login }
    "checkin" { Write-Title; Do-Checkin }
    "book1"   { Write-Title; Do-BookToday }
    "book7"   { Write-Title; Do-Book7 }
    "book30"  { Write-Title; Do-Book30 }
    "setup"   { Write-Title; Do-Setup }
    default   { Show-Menu }
}

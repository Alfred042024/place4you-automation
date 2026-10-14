# Place4You – Automazione prenotazione scrivania

Script per prenotare e fare il check-in della propria scrivania su [Place4You (p4y.alveo.it)](https://p4y.alveo.it) senza dover aprire il browser ogni volta.

## Prerequisiti

- **Windows 10/11**
- [**uv**](https://docs.astral.sh/uv/getting-started/installation/) — gestore Python ultrarapido
  ```
  winget install astral-sh.uv
  ```
  oppure:
  ```
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

## Setup per una nuova scrivania

1. Clona o scarica questo repository.

2. Apri `book_desk.py` e modifica le costanti di configurazione nella sezione `CONFIGURAZIONE`:

   ```python
   DESK_LABEL   = "PA ABS - ABS16"   # Etichetta del posto (solo per i log)
   DESK_ID      = 4648               # ID numerico scrivania (vedi URL su Place4You)
   FLOOR_ID     = 324                # ID piano
   ROOM_ID      = 1130               # ID stanza
   COMPANY_ID   = 103                # ID azienda (invariato per Alveo)
   BUILD_ID     = 127                # ID edificio (invariato per Milano)
   DESK_QR_CODE = "D_4648"           # Codice QR scrivania (D_<DESK_ID>)
   ```

   > **Come trovare i tuoi ID**: apri Place4You nel browser, seleziona la tua scrivania,
   > e guarda la chiamata `POST /api/Booking/Insert` negli strumenti sviluppatore (F12 → Network).
   > Troverai tutti gli ID nel payload JSON.

3. Esegui il **login SSO** (una sola volta, o quando la sessione scade):
   ```
   uv run book_desk.py --login
   ```
   Si aprirà un browser — accedi con Microsoft, poi chiudi quando vieni reindirizzato alla home.

## Utilizzo

### Menu interattivo (consigliato)

Doppio clic sul collegamento **Place4You.lnk** sul desktop, oppure:
```powershell
.\p4y.ps1
```

### Riga di comando

```powershell
uv run book_desk.py --book            # Prenota il prossimo giorno lavorativo
uv run book_desk.py --book --today    # Prenota oggi
uv run book_desk.py --book --days 7   # Prenota i prossimi 7 giorni lavorativi
uv run book_desk.py --book --days 30  # Prenota i prossimi 30 giorni lavorativi
uv run book_desk.py --checkin         # Check-in oggi
uv run book_desk.py --login           # (ri)effettua il login SSO
```

## Collegamento sul desktop

Crea un file `.lnk` con:
- **Destinazione**: `powershell.exe`
- **Argomenti**: `-NoProfile -ExecutionPolicy Bypass -File "C:\path\to\p4y.ps1"`
- **Cartella di avvio**: `C:\path\to\` (cartella dello script)

Oppure esegui in PowerShell (adatta il percorso):

```powershell
$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$env:USERPROFILE\Desktop\Place4You.lnk")
$lnk.TargetPath       = "powershell.exe"
$lnk.Arguments        = '-NoProfile -ExecutionPolicy Bypass -File "C:\percorso\p4y.ps1"'
$lnk.WorkingDirectory = "C:\percorso\"
$lnk.Save()
```

## Note

- `auth_state.json` viene creato al primo login e contiene i cookie di sessione Microsoft.
  **Non condividere questo file** — è nel `.gitignore`.
- La sessione dura di solito qualche settimana; quando scade, riesegui `--login`.
- Il check-in è possibile solo nelle ore in cui la prenotazione è attiva.

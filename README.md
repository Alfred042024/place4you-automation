# Place4You Automation

> Prenota la tua scrivania e fai il check-in su **Place4You** senza aprire il browser — da riga di comando o con un doppio click sul desktop.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-package%20manager-purple)](https://docs.astral.sh/uv/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](https://www.microsoft.com/windows)

---

## Funzionalità

- **Prenotazione** della propria scrivania per oggi, domani o più giorni in avanti
- **Check-in** tramite QR code senza dover usare lo smartphone
- **Login SSO** Microsoft / Azure AD — zero password da salvare
- **Setup guidato**: inquadri il QR sulla scrivania con la webcam, il resto è automatico
- **Menu interattivo** PowerShell per uso quotidiano

---

## Installazione rapida (Windows)

Apri **PowerShell** e incolla:

```powershell
irm https://raw.githubusercontent.com/Alfred042024/place4you-automation/master/install.ps1 | iex
```

Lo script installa tutto da zero:
1. [**uv**](https://docs.astral.sh/uv/) (gestore Python, se non presente)
2. Questa repository in `%USERPROFILE%\place4you-automation`
3. Chromium per Playwright
4. Collegamento **Place4You** sul desktop
5. Wizard di configurazione → inquadra il QR della tua scrivania con la webcam
6. Login SSO Microsoft

---

## Utilizzo

### Menu interattivo (doppio click sul desktop)

```
  +--------------------------------------+
  |   Place4You  -  Scrivania ABS16      |
  +--------------------------------------+
  [OK] sessione presente

  [1] Prenota oggi
  [2] Prenota 7 giorni lavorativi
  [3] Prenota 30 giorni lavorativi
  [4] Check-in oggi
  [5] Login SSO (primo setup o sessione scaduta)
  [6] Configura scrivania (prima installazione)
```

### Riga di comando

```powershell
uv run book_desk.py --setup           # Configura la tua scrivania (una volta)
uv run book_desk.py --login           # Login SSO Microsoft
uv run book_desk.py --book            # Prenota il prossimo giorno lavorativo
uv run book_desk.py --book --today    # Prenota oggi
uv run book_desk.py --book --days 7   # Prenota i prossimi 7 giorni
uv run book_desk.py --book --days 30  # Prenota i prossimi 30 giorni
uv run book_desk.py --checkin         # Check-in oggi
```

---

## Come funziona

Il sito Place4You è una **Single Page Application Angular** con autenticazione Microsoft Entra (Azure AD).

```
Login SSO Microsoft
       │
       ▼
POST /api/user/GetUserTokenByAzureToken   ← token P4Y
       │
       ├──▶ POST /api/Booking/Insert        ← prenotazione
       └──▶ GET  /api/Booking/checkQrCode   ← check-in
```

Playwright viene usato **solo** per eseguire il login SSO e leggere il token da `sessionStorage`. Tutte le operazioni successive avvengono via `requests` (niente browser aperto).

La sessione viene salvata in `auth_state.json` (gitignored) e riutilizzata automaticamente. Dura alcune settimane; quando scade basta rieseguire `--login`.

---

## Configurazione

Al primo avvio (`--setup`) viene creato `desk_config.json` (gitignored) con i dettagli della tua scrivania:

```json
{
  "base_url":     "https://p4y.tuaazienda.it",
  "desk_label":   "DESK-42",
  "desk_id":      1234,
  "floor_id":     10,
  "room_id":      20,
  "company_id":   1,
  "build_id":     1,
  "desk_qr_code": "D_1234"
}
```

Il nome e l'ID scrivania vengono rilevati automaticamente dalla webcam (QR code) e dall'API Place4You. L'URL, `company_id` e `build_id` vengono chiesti durante il setup; tutti i valori sono modificabili manualmente nel file dopo la configurazione.

---

## File

| File | Descrizione |
|------|-------------|
| `book_desk.py` | Script principale (Python + uv inline deps) |
| `p4y.ps1` | Menu interattivo PowerShell |
| `install.ps1` | Installer one-liner |
| `auth_state.json` | Sessione Microsoft (gitignored, creato da `--login`) |
| `desk_config.json` | Config scrivania personale (gitignored, creato da `--setup`) |

---

## Requisiti

- Windows 10 / 11
- [uv](https://docs.astral.sh/uv/) (installato automaticamente dall'installer)
- Account Microsoft con accesso a Place4You

---

## Licenza

[MIT](LICENSE) — © 2026 Gabriele De Prisco

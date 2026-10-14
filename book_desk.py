# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "playwright",
#   "requests",
#   "opencv-python",
# ]
# ///
"""
Place4You - Automazione prenotazione + check-in scrivania
=========================================================
USO (via uv):
    uv run book_desk.py --setup           # Configura la tua scrivania (una tantum)
    uv run book_desk.py --login           # Login SSO Microsoft (una tantum)
    uv run book_desk.py --book            # Prenota prossimo giorno lavorativo
    uv run book_desk.py --book --today    # Prenota oggi
    uv run book_desk.py --book --days 7   # Prenota i prossimi 7 giorni lavorativi
    uv run book_desk.py --book --days 30  # Prenota i prossimi 30 giorni lavorativi
    uv run book_desk.py --checkin         # Check-in oggi
"""

import asyncio
import json
import sys
import requests
from datetime import date, time, datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

# ═══════════════════════════════════════════════════════════
#  DEFAULTS (sovrascritti da desk_config.json se presente)
# ═══════════════════════════════════════════════════════════

BASE_URL     = "https://p4y.alveo.it"
UI_URL       = f"{BASE_URL}/ui/frontoffice"
API_URL      = f"{BASE_URL}/api"

DESK_LABEL   = "PA ABS - ABS16"
DESK_ID      = 4648
FLOOR_ID     = 324
ROOM_ID      = 1130
COMPANY_ID   = 103
BUILD_ID     = 127
DESK_QR_CODE = "D_4648"

TIME_START   = time(9, 0)
TIME_END     = time(18, 0)

AUTH_FILE    = Path(__file__).parent / "auth_state.json"
CONFIG_FILE  = Path(__file__).parent / "desk_config.json"

# ═══════════════════════════════════════════════════════════
#  CONFIGURAZIONE PER SCRIVANIA
# ═══════════════════════════════════════════════════════════

def load_config():
    global DESK_LABEL, DESK_ID, FLOOR_ID, ROOM_ID, COMPANY_ID, BUILD_ID, DESK_QR_CODE
    if not CONFIG_FILE.exists():
        return
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    DESK_LABEL   = cfg.get("desk_label",   DESK_LABEL)
    DESK_ID      = cfg.get("desk_id",      DESK_ID)
    FLOOR_ID     = cfg.get("floor_id",     FLOOR_ID)
    ROOM_ID      = cfg.get("room_id",      ROOM_ID)
    COMPANY_ID   = cfg.get("company_id",   COMPANY_ID)
    BUILD_ID     = cfg.get("build_id",     BUILD_ID)
    DESK_QR_CODE = cfg.get("desk_qr_code", DESK_QR_CODE)


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"  Config salvata in {CONFIG_FILE.name}")


def _decode_frame(detector, frame):
    """Prova più strategie per decodificare un QR blu su sfondo bianco/chiaro."""
    import cv2
    import numpy as np

    candidates = []

    # 1. Canale rosso invertito: pixel blu → basso in rosso → nero dopo inversione.
    #    Dà contrasto ottimale per QR blu su bianco.
    red = frame[:, :, 2]
    _, red_bin = cv2.threshold(red, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    candidates.append(red_bin)

    # 2. Scala di grigi con contrasto aumentato (CLAHE)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    candidates.append(clahe.apply(gray))

    # 3. Scala di grigi semplice
    candidates.append(gray)

    for img in candidates:
        data, _, _ = detector.detectAndDecode(img)
        if data:
            return data.strip()
    return None


def scan_qr_from_camera() -> str | None:
    """Apre la webcam e rileva il QR code della scrivania. Ritorna la stringa QR o None."""
    import cv2
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("  [!] Webcam non trovata.")
        return None

    detector = cv2.QRCodeDetector()
    print("  Inquadra il QR code della scrivania...")
    print("  Premi  Q  per confermare / annullare.")
    found = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        display = frame.copy()
        data = _decode_frame(detector, frame)

        if data:
            found = data.strip()
            cv2.putText(display, f"Trovato: {found}  (premi Q)",
                        (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)

        cv2.imshow("Place4You - Scansiona QR  (Q = conferma/esci)", display)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q"), 27):
            break

    cap.release()
    cv2.destroyAllWindows()
    return found


def _parse_qr(raw: str) -> str | None:
    """Normalizza il testo del QR al formato D_XXXX."""
    raw = raw.strip().upper()
    # Già nel formato corretto
    if raw.startswith("D_") and raw[2:].isdigit():
        return raw
    # Solo numero
    if raw.isdigit():
        return f"D_{raw}"
    # URL tipo https://p4y.alveo.it/...?qr=D_4648 o .../D_4648
    import re
    m = re.search(r"D_(\d+)", raw)
    if m:
        return f"D_{m.group(1)}"
    return None


def _try_autodiscover(token: str, desk_id: int) -> tuple[int, int] | None:
    """Prova endpoint noti per recuperare floor/room ID dalla scrivania."""
    candidates = [
        f"{API_URL}/Desk/GetById/{desk_id}",
        f"{API_URL}/Desk/Get?id={desk_id}",
        f"{API_URL}/Desk/{desk_id}",
        f"{API_URL}/Desk/GetInfo?deskId={desk_id}",
    ]
    headers = {"authorization": f"bearer {token}"}
    for url in candidates:
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    fid = data.get("FloorId") or data.get("Floor_Id")
                    rid = data.get("RoomId")  or data.get("Room_Id")
                    if fid and rid:
                        return int(fid), int(rid)
        except Exception:
            pass
    return None


async def setup_wizard(playwright):
    print("")
    print("  ╔══════════════════════════════════════╗")
    print("  ║   SETUP - Configura la tua scrivania ║")
    print("  ╚══════════════════════════════════════╝")
    print("")
    print("  Come vuoi inserire il codice QR della scrivania?")
    print("")
    print("  [1] Scansiona con la webcam (tieni il cartellino davanti alla camera)")
    print("  [2] Inserisci manualmente (es. D_4648)")
    print("")
    modo = input("  Scelta [1/2]: ").strip()

    qr_raw = None

    if modo == "1":
        scanned = scan_qr_from_camera()
        if scanned:
            qr_raw = _parse_qr(scanned)
            if qr_raw:
                print(f"  QR rilevato: {qr_raw}")
            else:
                print(f"  [!] QR letto ({scanned!r}) non riconosciuto come codice scrivania.")
                print("      Prova l'inserimento manuale.")
        else:
            print("  Scansione annullata o webcam non disponibile.")

    if not qr_raw:
        print("")
        print("  Inserisci il codice QR della scrivania (formato D_XXXX, es. D_4648).")
        raw = input("  Codice QR: ").strip()
        qr_raw = _parse_qr(raw)
        if not qr_raw:
            print(f"  [!] Formato non riconosciuto: {raw!r}")
            return

    try:
        desk_id = int(qr_raw[2:])
    except ValueError:
        print("  [!] QR code non valido.")
        return

    desk_label = input("  Nome scrivania (es. PA ABS - ABS16) [invio per usare il QR]: ").strip()
    if not desk_label:
        desk_label = qr_raw

    # Prova auto-discovery floor/room
    floor_id = FLOOR_ID
    room_id  = ROOM_ID
    auto_ok  = False

    if AUTH_FILE.exists():
        print("")
        print("  Recupero dettagli scrivania dal server...", end=" ", flush=True)
        token = await get_token(playwright)
        if token:
            result = _try_autodiscover(token, desk_id)
            if result:
                floor_id, room_id = result
                auto_ok = True
                print(f"OK  (Floor={floor_id}, Room={room_id})")
            else:
                print("non trovati automaticamente.")
        else:
            print("sessione non disponibile.")

    if not auto_ok:
        print("")
        print("  Floor ID e Room ID non rilevati automaticamente.")
        print("  Per trovarli: apri Place4You in Chrome, fai F12 -> Network,")
        print("  prenota una volta e cerca la chiamata a /api/Booking/Insert.")
        print(f"  (default attuali: Floor={floor_id}, Room={room_id})")
        print("")
        fi = input(f"  Floor ID [{floor_id}]: ").strip()
        ri = input(f"  Room ID  [{room_id}]: ").strip()
        if fi:
            floor_id = int(fi)
        if ri:
            room_id = int(ri)

    cfg = {
        "desk_label":   desk_label,
        "desk_id":      desk_id,
        "floor_id":     floor_id,
        "room_id":      room_id,
        "company_id":   COMPANY_ID,
        "build_id":     BUILD_ID,
        "desk_qr_code": qr_raw,
    }

    print("")
    print("  ┌─────────────────────────────────────┐")
    print("  │  Riepilogo configurazione           │")
    print("  ├─────────────────────────────────────┤")
    for k, v in cfg.items():
        print(f"  │  {k:<14} {str(v):<22}│")
    print("  └─────────────────────────────────────┘")
    print("")

    confirm = input("  Salvare? [S/N]: ").strip().upper()
    if confirm == "S":
        save_config(cfg)
        print("  Setup completato! Esegui ora il Login SSO.")
    else:
        print("  Setup annullato.")


# ═══════════════════════════════════════════════════════════
#  PLAYWRIGHT: solo per login e per leggere il token
# ═══════════════════════════════════════════════════════════

async def login_and_save(playwright):
    print("Apro il browser — accedi con Microsoft SSO, poi attendi il reindirizzamento.")
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page    = await context.new_page()
    await page.goto(f"{UI_URL}/home")
    print("   In attesa del login (max 3 minuti)...")
    await page.wait_for_url(f"{UI_URL}/home", timeout=180_000)
    await page.wait_for_load_state("networkidle")
    await context.storage_state(path=str(AUTH_FILE))
    await browser.close()
    print(f"Sessione salvata -> {AUTH_FILE.name}")


async def get_token(playwright) -> str | None:
    """Carica la home in headless, legge il token P4Y da sessionStorage."""
    if not AUTH_FILE.exists():
        print("Sessione non trovata. Esegui prima: uv run book_desk.py --login")
        return None

    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(storage_state=str(AUTH_FILE))
    page    = await context.new_page()
    try:
        await page.goto(f"{UI_URL}/home", wait_until="networkidle")
        if "microsoftonline.com" in page.url:
            print("Sessione scaduta -> esegui: uv run book_desk.py --login")
            return None
        token = await page.evaluate("() => sessionStorage.getItem('token')")
        if not token:
            print("Token non trovato in sessionStorage.")
            return None
        return token
    finally:
        await context.storage_state(path=str(AUTH_FILE))
        await browser.close()


# ═══════════════════════════════════════════════════════════
#  API: prenotazione e check-in via requests
# ═══════════════════════════════════════════════════════════

def _headers(token: str) -> dict:
    return {
        "authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }


def api_book(token: str, target_date: date) -> bool:
    start = datetime.combine(target_date, TIME_START).strftime("%Y-%m-%dT%H:%M:%S")
    end   = datetime.combine(target_date, TIME_END).strftime("%Y-%m-%dT%H:%M:%S")
    payload = {
        "Desk_Id":    DESK_ID,
        "Floor_Id":   FLOOR_ID,
        "Room_Id":    ROOM_ID,
        "Company_Id": COMPANY_ID,
        "Build_Id":   BUILD_ID,
        "StartDate":  start,
        "EndDate":    end,
    }
    print(f"Prenotazione {DESK_LABEL} - {target_date.strftime('%d/%m/%Y')} "
          f"[{TIME_START.strftime('%H:%M')}-{TIME_END.strftime('%H:%M')}]...", end=" ")

    resp = requests.post(f"{API_URL}/Booking/Insert", json=payload,
                         headers=_headers(token), timeout=15)

    if resp.status_code == 200:
        booking_id = resp.text.strip()
        print(f"OK (ID={booking_id})")
        return True

    body = resp.text.lower()
    if "alreadybooked" in body or "piu di una" in body or "più di una" in body \
            or "desknotavailable" in body:
        print("gia prenotata, skip.")
        return True

    print(f"ERRORE {resp.status_code}: {resp.text[:200]}")
    return False


def api_checkin(token: str) -> bool:
    print(f"Check-in {DESK_LABEL} (QR: {DESK_QR_CODE})...", end=" ")
    url  = f"{API_URL}/Booking/checkQrCode?qrCode={DESK_QR_CODE}"
    resp = requests.get(url, headers={"authorization": f"bearer {token}"}, timeout=15)

    try:
        result = resp.json()
    except Exception:
        print(f"Risposta non JSON ({resp.status_code}): {resp.text[:100]}")
        return False

    if result.get("CheckedIn"):
        print("OK")
        return True
    if result.get("AlreadyCheckedIn"):
        print("gia checked-in.")
        return True
    msg = result.get("Message", "")
    if "already" in msg.lower() or "gia" in msg.lower():
        print("gia checked-in.")
        return True
    if result.get("BookingId") is None and result.get("StartDateNextBooking"):
        next_slot = result["StartDateNextBooking"]
        print(f"nessun booking attivo ora. Prossimo: {next_slot[:16]}")
        return False
    print(f"risposta: {result}")
    return False


# ═══════════════════════════════════════════════════════════
#  UTILITÀ
# ═══════════════════════════════════════════════════════════

def working_days_from(start: date, n: int) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    load_config()

    args = sys.argv[1:]

    setup_mode   = "--setup"   in args
    login_mode   = "--login"   in args
    book_mode    = "--book"    in args
    checkin_mode = "--checkin" in args
    today_mode   = "--today"   in args

    days_count = 1
    if "--days" in args:
        idx = args.index("--days")
        try:
            days_count = int(args[idx + 1])
        except (IndexError, ValueError):
            print("Usa: --days <numero>  (es. --days 7)")
            sys.exit(1)

    if not any([setup_mode, login_mode, book_mode, checkin_mode]):
        book_mode    = True
        checkin_mode = True

    async with async_playwright() as pw:

        if setup_mode:
            await setup_wizard(pw)
            return

        if login_mode:
            await login_and_save(pw)
            return

        if not CONFIG_FILE.exists():
            print("[!] Nessuna configurazione trovata.")
            print("    Esegui prima: uv run book_desk.py --setup")
            sys.exit(1)

        token = await get_token(pw)
        if not token:
            sys.exit(1)

        if book_mode:
            if days_count == 1 and not today_mode:
                d = date.today() + timedelta(days=1)
                while d.weekday() >= 5:
                    d += timedelta(days=1)
                if not api_book(token, d):
                    sys.exit(1)
            else:
                start = date.today() if today_mode else date.today() + timedelta(days=1)
                days  = working_days_from(start, days_count)
                print(f"Prenotazione {days_count} giorni: "
                      f"{days[0].strftime('%d/%m')} -> {days[-1].strftime('%d/%m/%Y')}")
                ok = sum(api_book(token, d) for d in days)
                print(f"\nRisultato: {ok}/{days_count} prenotate.")
                if ok == 0:
                    sys.exit(1)

        if checkin_mode:
            api_checkin(token)


if __name__ == "__main__":
    asyncio.run(main())

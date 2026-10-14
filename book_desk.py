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

BASE_URL     = ""          # impostato da desk_config.json
UI_URL       = ""
API_URL      = ""

DESK_LABEL   = ""
DESK_ID      = 0
FLOOR_ID     = 0
ROOM_ID      = 0
COMPANY_ID   = 0
BUILD_ID     = 0
DESK_QR_CODE = ""

TIME_START   = time(9, 0)
TIME_END     = time(18, 0)

AUTH_FILE    = Path(__file__).parent / "auth_state.json"
CONFIG_FILE  = Path(__file__).parent / "desk_config.json"

# ═══════════════════════════════════════════════════════════
#  CONFIGURAZIONE PER SCRIVANIA
# ═══════════════════════════════════════════════════════════

def load_config():
    global BASE_URL, UI_URL, API_URL
    global DESK_LABEL, DESK_ID, FLOOR_ID, ROOM_ID, COMPANY_ID, BUILD_ID, DESK_QR_CODE
    if not CONFIG_FILE.exists():
        return
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    BASE_URL     = cfg.get("base_url",     BASE_URL)
    UI_URL       = f"{BASE_URL}/ui/frontoffice"
    API_URL      = f"{BASE_URL}/api"
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
    print("  Premi  ESC  per annullare.")
    found = None
    stable = 0
    STABLE_NEEDED = 20  # ~0.7s a 30fps

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        display = frame.copy()
        data = _decode_frame(detector, frame)

        if data:
            stable += 1
            found = data.strip()
            pct = min(stable, STABLE_NEEDED)
            bar = "#" * pct + "-" * (STABLE_NEEDED - pct)
            cv2.putText(display, f"Trovato: {found}",
                        (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 0), 2)
            cv2.putText(display, f"[{bar}]",
                        (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
            if stable >= STABLE_NEEDED:
                cv2.imshow("Place4You - Scansiona QR", display)
                cv2.waitKey(400)
                break
        else:
            stable = 0

        cv2.imshow("Place4You - Scansiona QR", display)
        if cv2.waitKey(1) & 0xFF == 27:
            found = None
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


def _try_autodiscover(token: str, desk_id: int, qr_code: str) -> dict:
    """
    Scopre automaticamente: desk_name, company_id, build_id, floor_id, room_id.
    Usa endpoint confermati dalla ricognizione API.
    """
    headers = {"authorization": f"bearer {token}"}
    result  = {}

    # 1. GetUserLogged → company_id (sempre disponibile dopo il login)
    try:
        resp = requests.get(f"{API_URL}/user/GetUserLogged",
                            headers=headers, timeout=8)
        if resp.status_code == 200:
            d = resp.json()
            if d.get("Company_Id"):
                result["company_id"] = int(d["Company_Id"])
    except Exception:
        pass

    # 2. checkQrCode → desk_name
    try:
        resp = requests.get(f"{API_URL}/Booking/checkQrCode?qrCode={qr_code}",
                            headers=headers, timeout=8)
        if resp.status_code == 200:
            d = resp.json()
            if d.get("Desk_Name"):
                result["desk_name"] = d["Desk_Name"]
    except Exception:
        pass

    # 3. GetBookingByDay → floor_id, room_id, build_id dal booking esistente
    today = date.today().isoformat()
    for date_param in [today, f"{today}T00:00:00", "undefined"]:
        try:
            resp = requests.get(
                f"{API_URL}/Booking/GetBookingByDay?currentDate={date_param}",
                headers=headers, timeout=8)
            if resp.status_code != 200:
                continue
            bookings = resp.json()
            if not isinstance(bookings, list):
                continue
            for b in bookings:
                if b.get("Desk_Id") == desk_id:
                    for src, dst in [("Floor_Id","floor_id"), ("FloorId","floor_id"),
                                     ("Room_Id", "room_id"),  ("RoomId", "room_id"),
                                     ("Build_Id","build_id"), ("BuildId","build_id")]:
                        if b.get(src) and dst not in result:
                            result[dst] = int(b[src])
                    break
        except Exception:
            pass
        if "floor_id" in result:
            break

    return result


async def setup_wizard(playwright):
    global BASE_URL, UI_URL, API_URL
    print("")
    print("  ╔══════════════════════════════════════╗")
    print("  ║   SETUP - Configura la tua scrivania ║")
    print("  ╚══════════════════════════════════════╝")
    print("")

    # URL istanza Place4You
    existing_url = BASE_URL or ""
    prompt_url = f"  URL Place4You [{existing_url}]: " if existing_url else "  URL Place4You (es. https://p4y.tuaazienda.it): "
    raw_url = input(prompt_url).strip().rstrip("/")
    if raw_url:
        BASE_URL = raw_url
    elif not BASE_URL:
        print("  [!] URL obbligatorio.")
        return
    UI_URL = f"{BASE_URL}/ui/frontoffice"
    API_URL = f"{BASE_URL}/api"
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

    # Auto-discovery via API
    floor_id   = FLOOR_ID
    room_id    = ROOM_ID
    company_id = COMPANY_ID
    build_id   = BUILD_ID
    desk_label = qr_raw

    if AUTH_FILE.exists():
        print("  Recupero dettagli dal server...", end=" ", flush=True)
        token = await get_token(playwright)
        if token:
            info = _try_autodiscover(token, desk_id, qr_raw)
            if info.get("desk_name"):
                desk_label = info["desk_name"]
            if info.get("floor_id"):
                floor_id = info["floor_id"]
            if info.get("room_id"):
                room_id = info["room_id"]
            if info.get("company_id"):
                company_id = info["company_id"]
            if info.get("build_id"):
                build_id = info["build_id"]
            found = [k for k in ("desk_name", "company_id", "build_id", "floor_id", "room_id") if k in info]
            print(f"OK  ({', '.join(found) if found else 'nessun campo'})")
        else:
            print("sessione non disponibile, uso default")

    confirmed = input(f"  Nome scrivania [{desk_label}]: ").strip()
    if confirmed:
        desk_label = confirmed

    cfg = {
        "base_url":     BASE_URL,
        "desk_label":   desk_label,
        "desk_id":      desk_id,
        "floor_id":     floor_id,
        "room_id":      room_id,
        "company_id":   company_id,
        "build_id":     build_id,
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

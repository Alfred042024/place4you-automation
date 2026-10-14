# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "playwright",
#   "requests",
# ]
# ///
"""
Place4You - Automazione prenotazione + check-in scrivania ABS16
================================================================
USO (via uv):
    uv run book_desk.py --login           # Login SSO Microsoft (una tantum)
    uv run book_desk.py --book            # Prenota prossimo giorno lavorativo
    uv run book_desk.py --book --today    # Prenota oggi
    uv run book_desk.py --book --days 7   # Prenota i prossimi 7 giorni lavorativi
    uv run book_desk.py --book --days 30  # Prenota i prossimi 30 giorni lavorativi
    uv run book_desk.py --checkin         # Check-in oggi

Meccanismo di auth:
    L'app usa Angular con interceptor: 'authorization: bearer <token>'
    dove il token si trova in sessionStorage['token'] dopo il login SSO.
    Playwright carica la home per inizializzare Angular e leggere il token;
    da quel punto tutto avviene via requests (no UI automation).
"""

import asyncio
import sys
import requests
from datetime import date, time, datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

# ═══════════════════════════════════════════════════════════
#  CONFIGURAZIONE
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

# Orario: "09:00-18:00" oppure "09:00-13:00" oppure "14:00-18:00"
TIME_START   = time(9, 0)
TIME_END     = time(18, 0)

AUTH_FILE    = Path(__file__).parent / "auth_state.json"

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


def _session_expired(page) -> bool:
    return "microsoftonline.com" in page.url


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
        if _session_expired(page):
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
    """Prenota la scrivania per la data indicata tramite POST /api/Booking/Insert."""
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
    """Check-in tramite GET /api/Booking/checkQrCode."""
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
#  MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    args = sys.argv[1:]

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

    if not any([login_mode, book_mode, checkin_mode]):
        book_mode    = True
        checkin_mode = True

    async with async_playwright() as pw:

        if login_mode:
            await login_and_save(pw)
            return

        # Per book e checkin serve il token
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

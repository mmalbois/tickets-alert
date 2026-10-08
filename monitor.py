#!/usr/bin/env python3
"""Surveille les créneaux Galleria Borghese (tosc.it) et alerte sur Telegram."""
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from curl_cffi import requests as cffi
from bs4 import BeautifulSoup

URLS = [
    "https://www.tosc.it/en/event/galleria-borghese-galleria-borghese-22159580/",
    "https://www.tosc.it/en/event/galleria-borghese-galleria-borghese-22159581/",
    "https://www.tosc.it/en/event/galleria-borghese-galleria-borghese-22159571/",
]
TARGET_DATES = {"2026-10-29", "2026-10-30", "2026-10-31"}
LAST_DAY = date(2026, 10, 31)

STATE_FILE = Path("state.json")
CHECK_EVERY = int(os.getenv("CHECK_EVERY", "0"))  # secondes entre 2 vérifs (0 = une seule)
DURATION = int(os.getenv("DURATION", "0"))        # durée max de la boucle en secondes
FAIL_ALERT = 10                                   # nb d'échecs de suite avant alerte d'erreur
DEBUG = os.getenv("DEBUG") == "1"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]


def log(*a):
    print(*a, flush=True)


# ---------- Telegram ----------
def send(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"},
        timeout=30,
    )
    r.raise_for_status()


# ---------- Lecture de la page ----------
TIME_RE = re.compile(r"(\d{1,2})(?:[.:](\d{2}))?\s*(am|pm)", re.I)
PRICE_RE = re.compile(r"€\s*\d+[.,]\d{2}|\d+[.,]\d{2}\s*€")
UNAVAILABLE = ("not available", "sold out", "esaurito", "non disponibile")


def _t24(m):
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    return f"{h:02d}:{m.group(2) or '00'}"


def pretty(label):
    s = TIME_RE.sub(_t24, label)
    return re.sub(r"^IN\s+(.+?)\s*-\s*OUT\s+(.+)$", r"\1 → \2", s)


def fmt_date(iso):
    y, m, d = iso.split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]}"


def fetch(url):
    r = cffi.get(url, impersonate="chrome",
                 headers={"Accept-Language": "en-US,en;q=0.9"}, timeout=25)
    r.raise_for_status()
    return r.text


def parse(html):
    """Retourne (date_iso, {créneau: [tarifs dispos]}, nb_total_créneaux)."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]

    # recolle un "€" isolé avec le montant qui suit
    merged, i = [], 0
    while i < len(lines):
        if lines[i] == "€" and i + 1 < len(lines):
            merged.append(f"€ {lines[i + 1]}")
            i += 2
        else:
            merged.append(lines[i])
            i += 1
    lines = merged
    if DEBUG:
        log("\n".join(lines))

    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", " ".join(lines))
    if not m:
        titre = soup.title.string.strip() if soup.title and soup.title.string else "?"
        debut = " ".join(lines)[:500]
        raise ValueError(f"date introuvable | titre={titre} | début={debut}")
    date_iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    try:
        start = next(i for i, l in enumerate(lines) if "PRICE AND FEES TABLE" in l.upper()
                     or "TABELLA PREZZI" in l.upper())
    except StopIteration:
        raise ValueError("tableau des prix introuvable (page bloquée ou modifiée ?)")
    end = next((i for i, l in enumerate(lines) if i > start and
                l.lower().startswith("info about delivery")), len(lines))
    sec = lines[start + 1:end]

    slots, header, new_block = {}, None, True
    for j, l in enumerate(sec):
        if l.lower().startswith("reset selection"):
            new_block = True
            continue
        if not PRICE_RE.fullmatch(l) or j < 2:
            continue
        if new_block:
            header = sec[j - 2]
            slots.setdefault(header, [])
            new_block = False
        name = sec[j - 1]
        status = sec[j + 1].lower() if j + 1 < len(sec) else ""
        if not any(u in status for u in UNAVAILABLE):
            slots[header].append(f"{name} ({l})")

    if not slots:
        raise ValueError("aucun créneau trouvé dans la page")
    available = {h: sorted(t) for h, t in slots.items() if t}
    return date_iso, available, len(slots)


# ---------- Comparaison ----------
def diff(old, new):
    added = [h for h in new if h not in old]
    removed = [h for h in old if h not in new]
    changed = [h for h in new if h in old and new[h] != old[h]]
    return added, removed, changed


def format_block(url, date_iso, new, added, removed, changed):
    out = [f"📅 {fmt_date(date_iso)}"]
    for h in added:
        out.append(f"🆕 {pretty(h)}")
        out += [f"   • {t}" for t in new[h]]
    for h in removed:
        out.append(f"🕐 {pretty(h)} — plus disponible")
    for h in changed:
        out.append(f"🔄 {pretty(h)} — tarifs modifiés")
        out += [f"   • {t}" for t in new[h]]
    out.append(f"🔗 {url}")
    return "\n".join(out)


# ---------- Boucle principale ----------
def check_all(state):
    pages = state.setdefault("pages", {})
    fails = state.setdefault("fails", {})
    first = not state.get("initialized")
    blocks, summary, ok = [], [], 0
    any_added = False

    for url in URLS:
        try:
            date_iso, avail, total = parse(fetch(url))
        except Exception as e:
            fails[url] = fails.get(url, 0) + 1
            log(f"[ERREUR] {url[-9:]} : {e} (échec n°{fails[url]})")
            if fails[url] == FAIL_ALERT:
                send(f"⚠️ Galleria Borghese : le script n'arrive plus à lire {url}\n{e}")
            continue
        ok += 1
        fails[url] = 0
        if date_iso not in TARGET_DATES:
            log(f"[IGNORÉ] {url[-9:]} date {date_iso} hors cible")
            continue
        log(f"[OK] {fmt_date(date_iso)} : {len(avail)} créneau(x) dispo sur {total}")

        old = pages.get(url, {}).get("slots", {})
        pages[url] = {"date": date_iso, "slots": avail}

        if first:
            if avail:
                summary.append(f"{fmt_date(date_iso)} : " +
                               ", ".join(pretty(h) for h in avail))
            else:
                summary.append(f"{fmt_date(date_iso)} : rien de dispo")
            continue

        added, removed, changed = diff(old, avail)
        if added or removed or changed:
            any_added = any_added or bool(added)
            blocks.append(format_block(url, date_iso, avail, added, removed, changed))

    if first and ok:
        send("✅ Surveillance Galleria Borghese démarrée.\n"
             "État actuel :\n" + "\n".join(summary))
        state["initialized"] = True
    elif blocks:
        title = ("🔔 Galleria Borghese — nouveau créneau !" if any_added
                 else "🔔 Galleria Borghese — changement de disponibilités")
        send(title + "\n\n" + "\n\n".join(blocks))


def main():
    if date.today() > LAST_DAY:
        log("Dates dépassées, rien à surveiller.")
        return
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    start = time.time()
    while True:
        check_all(state)
        if CHECK_EVERY <= 0 or time.time() - start + CHECK_EVERY > DURATION:
            break
        time.sleep(CHECK_EVERY)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())

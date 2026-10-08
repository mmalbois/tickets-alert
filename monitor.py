import asyncio
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://www.tosc.it/en/artist/galleria-borghese/galleria-borghese-2253937/"

DATES = [
    "29 Oct 2026",
    "30 Oct 2026",
    "31 Oct 2026",
]

STATE_FILE = Path("state.json")


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def send_telegram(message):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("ERREUR : secrets Telegram manquants")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "false",
    }).encode("utf-8")

    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=30) as response:
        print("Telegram :", response.status)


async def get_availability(page):
    print("Ouverture de TOSC...")

    await page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    await page.wait_for_timeout(7000)

    body_text = await page.locator("body").inner_text()

    print("Page chargée.")
    print("Recherche des dates...")

    results = {}

    for date in DATES:
        # Recherche de la date dans le texte de la page
        date_pattern = re.escape(date)

        # On récupère le texte autour de la date
        match = re.search(
            rf"{date_pattern}.*?(?=\n##|\Z)",
            body_text,
            re.DOTALL
        )

        if match:
            block = match.group(0)

            # Recherche du statut TOSC
            if re.search(r"\bAvailable\b", block, re.IGNORECASE):
                status = "Available"
            elif re.search(r"\bLimited\b", block, re.IGNORECASE):
                status = "Limited"
            elif re.search(r"\bFew\b", block, re.IGNORECASE):
                status = "Few"
            else:
                status = "Unknown"

            # Recherche éventuelle d'horaires
            times = sorted(set(
                re.findall(
                    r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b",
                    block
                )
            ))

            results[date] = {
                "status": status,
                "times": times,
            }

            print(
                f"{date} : {status}"
                + (f" | horaires : {', '.join(times)}" if times else "")
            )

        else:
            print(f"{date} : date non trouvée")
            results[date] = {
                "status": "Not found",
                "times": [],
            }

    return results


async def main():
    old_state = load_state()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page(
            viewport={
                "width": 1440,
                "height": 1200,
            }
        )

        new_state = await get_availability(page)

        await browser.close()

    print("\n--- Etat actuel ---")
    print(json.dumps(new_state, indent=2, ensure_ascii=False))

    changes = []

    for date in DATES:
        old = old_state.get(
            date,
            {
                "status": "Unknown",
                "times": [],
            }
        )

        new = new_state.get(
            date,
            {
                "status": "Unknown",
                "times": [],
            }
        )

        if old != new:
            changes.append((date, old, new))

    # Première exécution : on mémorise simplement l'état
    if not old_state:
        print("\nPremière exécution : création de l'état de référence.")
        save_state(new_state)
        return

    # Changements détectés
    if changes:
        message_lines = [
            "🚨 GALLERIA BORGHESE — CHANGEMENT !",
            "",
        ]

        for date, old, new in changes:
            message_lines.append(f"📅 {date}")
            message_lines.append(
                f"Avant : {old.get('status', 'Unknown')}"
            )
            message_lines.append(
                f"Maintenant : {new.get('status', 'Unknown')}"
            )

            if new.get("times"):
                message_lines.append(
                    "🕐 Horaires : " + ", ".join(new["times"])
                )

            message_lines.append("")

        message_lines.append("🎟️ Vérifie rapidement les billets :")
        message_lines.append(URL)

        message = "\n".join(message_lines)

        print("\nCHANGEMENT DETECTE !")
        print(message)

        send_telegram(message)

    else:
        print("\nAucun changement.")

    save_state(new_state)


if __name__ == "__main__":
    asyncio.run(main())

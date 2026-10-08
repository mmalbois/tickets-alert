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
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False
        ),
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

    request = urllib.request.Request(
        url,
        data=data
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:
        print("Telegram :", response.status)


def analyse_page_text(text):
    results = {}

    # Nettoyage basique
    text = text.replace("\r", "")

    for date in DATES:
        pattern = re.escape(date)

        match = re.search(
            rf"{pattern}.*?(?=\n\s*\n|\Z)",
            text,
            re.IGNORECASE | re.DOTALL
        )

        if not match:
            # Deuxième tentative plus large
            match = re.search(
                rf"{pattern}.*",
                text,
                re.IGNORECASE | re.DOTALL
            )

        if not match:
            results[date] = {
                "status": "Not found",
                "times": []
            }
            continue

        block = match.group(0)

        if re.search(r"\bAvailable\b", block, re.IGNORECASE):
            status = "Available"
        elif re.search(r"\bLimited\b", block, re.IGNORECASE):
            status = "Limited"
        elif re.search(r"\bFew\b", block, re.IGNORECASE):
            status = "Few"
        elif re.search(r"\bSold\s*out\b", block, re.IGNORECASE):
            status = "Sold out"
        else:
            status = "Unknown"

        times = sorted(set(
            re.findall(
                r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b",
                block
            )
        ))

        results[date] = {
            "status": status,
            "times": times
        }

    return results


async def get_page_with_playwright(page):
    print("Tentative Playwright...")

    last_error = None

    for attempt in range(1, 4):
        try:
            print(f"Tentative {attempt}/3...")

            await page.goto(
                URL,
                wait_until="commit",
                timeout=60000
            )

            await page.wait_for_timeout(8000)

            text = await page.locator("body").inner_text()

            if text.strip():
                print("Page récupérée avec Playwright.")
                return text

        except Exception as error:
            last_error = error
            print(
                f"Échec tentative {attempt} : {error}"
            )

            await asyncio.sleep(3)

    print("Playwright n'a pas réussi.")
    print(f"Dernière erreur : {last_error}")

    return None


async def get_availability():
    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-http2",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = await browser.new_context(
            viewport={
                "width": 1440,
                "height": 1200
            },
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9"
            }
        )

        page = await context.new_page()

        text = await get_page_with_playwright(page)

        await browser.close()

    if text is None:
        raise RuntimeError(
            "Impossible de récupérer la page TOSC."
        )

    print("\nAnalyse de la page...\n")

    results = analyse_page_text(text)

    for date in DATES:
        result = results[date]

        times = result["times"]

        if times:
            times_text = ", ".join(times)
            print(
                f"{date} : "
                f"{result['status']} | "
                f"horaires : {times_text}"
            )
        else:
            print(
                f"{date} : "
                f"{result['status']}"
            )

    return results


async def main():

    print("===================================")
    print("SURVEILLANCE GALLERIA BORGHESE")
    print("===================================\n")

    old_state = load_state()

    new_state = await get_availability()

    print("\n--- Nouvel état ---")

    print(
        json.dumps(
            new_state,
            indent=2,
            ensure_ascii=False
        )
    )

    # Première exécution
    if not old_state:

        print(
            "\nPremière exécution : "
            "création de l'état de référence."
        )

        save_state(new_state)
        return

    changes = []

    for date in DATES:

        old = old_state.get(
            date,
            {
                "status": "Unknown",
                "times": []
            }
        )

        new = new_state.get(
            date,
            {
                "status": "Unknown",
                "times": []
            }
        )

        if old != new:
            changes.append(
                (
                    date,
                    old,
                    new
                )
            )

    if changes:

        print("\n🚨 CHANGEMENT DÉTECTÉ !")

        message_lines = [
            "🚨 GALLERIA BORGHESE",
            "",
            "Nouveau changement de disponibilité :",
            ""
        ]

        for date, old, new in changes:

            message_lines.append(
                f"📅 {date}"
            )

            message_lines.append(
                f"Avant : {old.get('status', 'Unknown')}"
            )

            message_lines.append(
                f"Maintenant : {new.get('status', 'Unknown')}"
            )

            if new.get("times"):
                message_lines.append(
                    "🕐 Horaires : "
                    + ", ".join(new["times"])
                )

            message_lines.append("")

        message_lines.append(
            "🎟️ Billetterie :"
        )

        message_lines.append(URL)

        message = "\n".join(message_lines)

        print(message)

        send_telegram(message)

    else:

        print(
            "\nAucun changement détecté."
        )

    save_state(new_state)


if __name__ == "__main__":
    asyncio.run(main())

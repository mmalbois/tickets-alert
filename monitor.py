import asyncio
import json
import os
import re
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://www.tosc.it/en/artist/galleria-borghese/galleria-borghese-2253937/"

DATES = [
    "29 Oct 2026",
    "30 Oct 2026",
    "31 Oct 2026",
]

STATE_FILE = Path("state.json")


def normalize(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


async def get_times(page, date_text):

    print(f"Recherche : {date_text}")

    await page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    # Laisser TOSC charger son Javascript
    await page.wait_for_timeout(5000)

    # Chercher la date
    locator = page.get_by_text(
        date_text,
        exact=False
    )

    count = await locator.count()

    print(f"  éléments trouvés : {count}")

    clicked = False

    for i in range(count):

        item = locator.nth(i)

        try:
            if await item.is_visible():
                await item.scroll_into_view_if_needed()
                await item.click()
                clicked = True
                break
        except Exception:
            pass

    if not clicked:

        print(
            f"  IMPOSSIBLE DE CLIQUER SUR {date_text}"
        )

        await page.screenshot(
            path=f"debug-{date_text[:2]}.png",
            full_page=True
        )

        return []

    # Attendre l'ouverture de la sélection
    await page.wait_for_timeout(3000)

    # Chercher tous les textes ressemblant à une heure
    elements = await page.locator(
        "button, a, label, [role='button']"
    ).all()

    times = set()

    for element in elements:

        try:

            if not await element.is_visible():
                continue

            text = normalize(
                await element.inner_text()
            )

            matches = re.findall(
                r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b",
                text
            )

            for match in matches:

                times.add(
                    match.replace(".", ":")
                )

        except Exception:
            continue

    result = sorted(times)

    print(
        f"  horaires : "
        f"{', '.join(result) if result else 'AUCUN'}"
    )

    return result


async def main():

    old_state = load_state()

    new_state = {}

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page(
            viewport={
                "width": 1440,
                "height": 1000
            }
        )

        for date in DATES:

            try:

                times = await get_times(
                    page,
                    date
                )

                new_state[date] = times

            except Exception as error:

                print(
                    f"Erreur avec {date}: {error}"
                )

                new_state[date] = []

        await browser.close()

    # -----------------------------------------
    # Comparaison avec la vérification précédente
    # -----------------------------------------

    changes = []

    for date in DATES:

        old = set(
            old_state.get(date, [])
        )

        new = set(
            new_state.get(date, [])
        )

        added = sorted(new - old)
        removed = sorted(old - new)

        if added or removed:

            changes.append({
                "date": date,
                "added": added,
                "removed": removed,
                "current": sorted(new)
            })

    # -----------------------------------------
    # Message Telegram
    # -----------------------------------------

    if changes:

        message = [
            "🚨 GALLERIA BORGHESE",
            "CHANGEMENT DE DISPONIBILITÉ",
            ""
        ]

        for change in changes:

            message.append(
                f"📅 {change['date']}"
            )

            if change["added"]:
                message.append(
                    "🟢 Nouveaux : "
                    + ", ".join(change["added"])
                )

            if change["removed"]:
                message.append(
                    "🔴 Disparus : "
                    + ", ".join(change["removed"])
                )

            message.append(
                "🕐 Maintenant : "
                + (
                    ", ".join(change["current"])
                    if change["current"]
                    else "aucun créneau détecté"
                )
            )

            message.append("")

        message.append(
            "🎟️ Réserver :"
        )
        message.append(URL)

        telegram_message = "\n".join(message)

        print()
        print(telegram_message)

        token = os.environ.get("TELEGRAM_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        if token and chat_id:

            import urllib.request
            import urllib.parse

            data = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": telegram_message,
            }).encode()

            request = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data
            )

            urllib.request.urlopen(request)

    else:

        print("Aucun changement.")

    # Sauvegarder le nouvel état
    save_state(new_state)


if __name__ == "__main__":
    asyncio.run(main())

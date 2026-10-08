import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import requests


URL = "https://www.ticketone.it/en/artist/galleria-borghese/galleria-borghese-2253937/"

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
        raise RuntimeError("Secrets Telegram manquants.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "false",
    }).encode("utf-8")

    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:
        print("Telegram :", response.status)


def get_ticketone_page():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        "Connection": "close",
    }

    print("Ouverture de TicketOne...")

    last_error = None

    for attempt in range(1, 4):

        try:
            print(
                f"Tentative {attempt}/3..."
            )

            response = requests.get(
                URL,
                headers=headers,
                timeout=(15, 90),
            )

            response.raise_for_status()

            print(
                f"Page reçue : {len(response.text)} caractères"
            )

            return response.text

        except requests.RequestException as error:

            last_error = error

            print(
                f"Échec tentative {attempt}/3 : {error}"
            )

            if attempt < 3:
                import time
                time.sleep(5)

    raise RuntimeError(
        f"Impossible de récupérer TicketOne après 3 tentatives : "
        f"{last_error}"
    )


def clean_html(html):
    text = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    text = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = (
        text
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&amp;", "&")
    )

    return re.sub(r"\s+", " ", text)


def find_status(text, date):
    """
    Cherche le statut associé à une date TicketOne.

    Exemple de contenu TicketOne :

    30 Oct 2026
    Few
    Galleria Borghese
    """

    pattern = (
        rf"{re.escape(date)}"
        rf".{{0,500}}?"
        rf"\b(Available|Limited|Few)\b"
    )

    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE
    )

    if match:
        return match.group(1).title()

    return "Unknown"


def main():

    print("==============================")
    print("GALLERIA BORGHESE MONITOR")
    print("==============================")

    old_state = load_state()

    try:
        html = get_ticketone_page()
    except Exception as error:
        print(f"ERREUR TicketOne : {error}")
        raise

    text = clean_html(html)

    new_state = {}

    for date in DATES:

        status = find_status(
            text,
            date
        )

        new_state[date] = {
            "status": status
        }

        print(
            f"{date} : {status}"
        )

    print()
    print("--- Etat actuel ---")

    print(
        json.dumps(
            new_state,
            indent=2,
            ensure_ascii=False
        )
    )

    # Première exécution
    if not old_state:

        print()
        print(
            "Première exécution : "
            "création de l'état de référence."
        )

        save_state(new_state)
        return

    changes = []

    for date in DATES:

        old_status = old_state.get(
            date,
            {}
        ).get(
            "status",
            "Unknown"
        )

        new_status = new_state[date]["status"]

        if old_status != new_status:

            changes.append(
                (
                    date,
                    old_status,
                    new_status
                )
            )

    if not changes:

        print()
        print("Aucun changement.")

    else:

        print()
        print(
            f"{len(changes)} changement(s) détecté(s) !"
        )

        message = [
            "🚨 GALLERIA BORGHESE",
            "",
            "CHANGEMENT DE DISPONIBILITÉ !",
            ""
        ]

        for date, old_status, new_status in changes:

            message.append(
                f"📅 {date}"
            )

            message.append(
                f"Avant : {old_status}"
            )

            message.append(
                f"Maintenant : {new_status}"
            )

            message.append("")

        message.append(
            "🎟️ Billetterie :"
        )

        message.append(URL)

        send_telegram(
            "\n".join(message)
        )

    save_state(new_state)


if __name__ == "__main__":
    main()

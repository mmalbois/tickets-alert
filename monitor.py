import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import requests


EVENTS = {
    "29 Oct 2026": "https://www.tosc.it/en/event/galleria-borghese-galleria-borghese-22159580/",
    "30 Oct 2026": "https://www.tosc.it/en/event/galleria-borghese-galleria-borghese-22159581/",
    "31 Oct 2026": "https://www.tosc.it/en/event/galleria-borghese-galleria-borghese-22159571/",
}

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
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

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
        timeout=20
    ) as response:
        print("Telegram :", response.status)


def get_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    response.raise_for_status()

    return response.text


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
        .replace("&amp;", "&")
        .replace("&#39;", "'")
    )

    return re.sub(r"\s+", " ", text)


def find_status(text):
    """
    On considère la journée disponible si la page contient
    au moins un créneau qui n'est pas marqué 'Not available'.
    """

    available_markers = [
        "Available",
        "Few",
        "Limited",
    ]

    for marker in available_markers:
        if re.search(
            rf"\b{marker}\b",
            text,
            re.IGNORECASE
        ):
            return marker.title()

    if re.search(
        r"\bNot available\b",
        text,
        re.IGNORECASE
    ):
        return "Not available"

    return "Unknown"


def main():

    print("==============================")
    print("GALLERIA BORGHESE MONITOR")
    print("==============================")

    old_state = load_state()
    new_state = {}

    for date, url in EVENTS.items():

        print()
        print(f"Ouverture {date}...")

        try:
            html = get_page(url)
            text = clean_html(html)

            status = find_status(text)

            new_state[date] = {
                "status": status,
                "url": url,
            }

            print(
                f"{date} : {status}"
            )

        except Exception as error:

            print(
                f"{date} : ERREUR - {error}"
            )

            new_state[date] = {
                "status": "ERROR",
                "url": url,
            }

    print()
    print("--- Résultat ---")

    print(
        json.dumps(
            new_state,
            indent=2,
            ensure_ascii=False
        )
    )

    if not old_state:

        print()
        print("Première exécution : état de référence.")

        save_state(new_state)
        return

    changes = []

    for date in EVENTS:

        old_status = old_state.get(
            date,
            {}
        ).get(
            "status",
            "Unknown"
        )

        new_status = new_state[date]["status"]

        # On ne considère pas une erreur réseau
        # comme un changement de disponibilité.
        if new_status == "ERROR":
            continue

        if old_status != new_status:

            changes.append(
                (
                    date,
                    old_status,
                    new_status
                )
            )

    if changes:

        print()
        print(
            f"{len(changes)} changement(s) détecté(s) !"
        )

        message = [
            "🚨 GALLERIA BORGHESE",
            "",
            "CHANGEMENT DE DISPONIBILITÉ !",
            "",
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
            "🎟️ Réserver :"
        )

        message.append(
            EVENTS[changes[0][0]]
        )

        send_telegram(
            "\n".join(message)
        )

    else:

        print()
        print("Aucun changement.")

    save_state(new_state)


if __name__ == "__main__":
    main()

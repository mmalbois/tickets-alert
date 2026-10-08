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
        data = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        # Ancienne structure éventuelle
        if not isinstance(data, dict):
            return {}

        return data

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
    """
    Passe par Jina Reader afin d'éviter le blocage
    de TicketOne/TOSC depuis GitHub Actions.
    """

    jina_url = "https://r.jina.ai/" + url

    print("Source :", jina_url)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/plain",
    }

    response = requests.get(
        jina_url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    print(
        f"Réponse reçue : {len(response.text)} caractères"
    )

    return response.text


def find_status(text):
    text_lower = text.lower()

    # Si on trouve explicitement des billets disponibles.
    if re.search(
        r"\bavailable\b|\bin stock\b",
        text_lower
    ):
        return "Available"

    # TicketOne utilise aussi des quantités numériques.
    # Un prix suivi d'un 0 signifie généralement aucun billet.
    if re.search(
        r"€\s*\d+(?:[.,]\d+)?\s+\d+\s",
        text
    ):
        return "Available"

    if "not available" in text_lower:
        return "Not available"

    if "currently not available" in text_lower:
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
        print(f"Vérification {date}...")

        try:

            text = get_page(url)

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

    # Première exécution = création de la référence.
    if not old_state:

        print()
        print("Création de l'état de référence.")

        save_state(new_state)
        return

    changes = []

    for date in EVENTS:

        old_entry = old_state.get(date, {})

        if not isinstance(old_entry, dict):
            old_status = "Unknown"
        else:
            old_status = old_entry.get(
                "status",
                "Unknown"
            )

        new_status = new_state[date]["status"]

        # Une erreur réseau ne déclenche jamais d'alerte.
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

            message.append(
                EVENTS[date]
            )

            message.append("")

        send_telegram(
            "\n".join(message)
        )

    else:

        print()
        print("Aucun changement.")

    save_state(new_state)


if __name__ == "__main__":
    main()

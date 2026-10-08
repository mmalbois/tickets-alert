import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import requests


DATES = {
    "29 Oct 2026": "https://www.ticketone.it/event/galleria-borghese-galleria-borghese-22159580/",
    "30 Oct 2026": "https://www.ticketone.it/event/galleria-borghese-galleria-borghese-22159581/",
}

# IMPORTANT :
# Le lien du 31 octobre sera ajouté après vérification de son identifiant
# TicketOne. On ne va pas inventer une URL.

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

    request = urllib.request.Request(
        url,
        data=data
    )

    with urllib.request.urlopen(
        request,
        timeout=30
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

    print(f"Lecture : {url}")

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    print(
        f"Page reçue : {len(response.text)} caractères"
    )

    return response.text


def extract_availability(html):
    """
    TicketOne affiche les créneaux sous la forme :

    IN 09:00-OUT 11:00
    Intero
    €18,00
    Non disponibile

    On récupère donc chaque créneau et son statut.
    """

    # Transformer le HTML en texte simple
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

    # Nettoyage des espaces
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    text = (
        text
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&amp;", "&")
    )

    results = []

    # Créneaux classiques : IN 09:00-OUT 11:00
    slots = re.findall(
        r"IN\s+([0-2]\d:[0-5]\d)-OUT\s+([0-2]\d:[0-5]\d)(.*?)(?=IN\s+[0-2]\d:[0-5]\d|$)",
        text,
        flags=re.IGNORECASE
    )

    for start, end, block in slots:
        if re.search(
            r"Non disponibile|Not available",
            block,
            re.IGNORECASE
        ):
            status = "Not available"
        elif re.search(
            r"Disponibile|Available",
            block,
            re.IGNORECASE
        ):
            status = "Available"
        else:
            status = "Unknown"

        results.append({
            "time": f"{start}-{end}",
            "status": status
        })

    # Visites guidées : 09:10, 11:10, etc.
    guided = re.findall(
        r"([0-2]\d:[0-5]\d)\s+([^€]{0,80}?(?:GUIDED TOUR|Visita guidata).*?)(?=[0-2]\d:[0-5]\d|$)",
        text,
        flags=re.IGNORECASE
    )

    for time, block in guided:
        if re.search(
            r"Non disponibile|Not available",
            block,
            re.IGNORECASE
        ):
            status = "Not available"
        elif re.search(
            r"Disponibile|Available",
            block,
            re.IGNORECASE
        ):
            status = "Available"
        else:
            status = "Unknown"

        results.append({
            "time": time,
            "status": status
        })

    # Supprimer les doublons
    unique = {}

    for item in results:
        unique[
            f"{item['time']}|{item['status']}"
        ] = item

    return list(unique.values())


def main():

    print("==============================")
    print("GALLERIA BORGHESE MONITOR")
    print("==============================")

    old_state = load_state()

    new_state = {}

    for date, url in DATES.items():

        print()
        print(f"📅 {date}")

        try:
            html = get_page(url)

            availability = extract_availability(html)

            new_state[date] = {
                "url": url,
                "slots": availability
            }

            available = [
                x["time"]
                for x in availability
                if x["status"] == "Available"
            ]

            if available:
                print(
                    "🚨 DISPONIBILITÉS : "
                    + ", ".join(available)
                )
            else:
                print("Aucune disponibilité détectée.")

        except Exception as error:

            print(
                f"ERREUR pour {date} : {error}"
            )

            # On conserve l'ancien état en cas d'erreur
            new_state[date] = old_state.get(
                date,
                {
                    "url": url,
                    "slots": []
                }
            )

    print()
    print("Comparaison avec le passage précédent...")

    changes = []

    for date in DATES:

        old = old_state.get(
            date,
            {
                "url": DATES[date],
                "slots": []
            }
        )

        new = new_state[date]

        if old.get("slots") != new.get("slots"):
            changes.append(
                (
                    date,
                    old.get("slots", []),
                    new.get("slots", [])
                )
            )

    # Première exécution :
    # on mémorise seulement l'état.
    if not old_state:

        print(
            "Première exécution : "
            "création de l'état de référence."
        )

        save_state(new_state)
        return

    if not changes:

        print("Aucun changement.")

    else:

        print(
            f"{len(changes)} changement(s) détecté(s)."
        )

        message = [
            "🚨 GALLERIA BORGHESE",
            "",
            "CHANGEMENT DE DISPONIBILITÉ !",
            ""
        ]

        for date, old_slots, new_slots in changes:

            message.append(
                f"📅 {date}"
            )

            old_available = [
                x["time"]
                for x in old_slots
                if x["status"] == "Available"
            ]

            new_available = [
                x["time"]
                for x in new_slots
                if x["status"] == "Available"
            ]

            if new_available:
                message.append(
                    "🎟️ Disponible : "
                    + ", ".join(new_available)
                )
            else:
                message.append(
                    "❌ Aucune disponibilité détectée"
                )

            if old_available:
                message.append(
                    "Avant : "
                    + ", ".join(old_available)
                )

            message.append("")

        message.append(
            "👉 Vérifie rapidement la billetterie."
        )

        send_telegram(
            "\n".join(message)
        )

    save_state(new_state)


if __name__ == "__main__":
    main()

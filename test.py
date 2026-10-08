import os
import requests

token = os.environ["TELEGRAM_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

message = "🟢 Test réussi ! Ton robot Borghese fonctionne."

url = f"https://api.telegram.org/bot{token}/sendMessage"

requests.post(
    url,
    data={
        "chat_id": chat_id,
        "text": message
    }
)

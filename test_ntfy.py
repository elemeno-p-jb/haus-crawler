import os
import requests

topic = os.environ["NTFY_TOPIC"]

response = requests.post(
    f"https://ntfy.sh/{topic}",
    data="Der Immobilien-Monitor funktioniert! 🏠".encode("utf-8"),
    headers={
        "Title": "Immobilien-Monitor TEST",
        "Priority": "high",
        "Tags": "white_check_mark,house",
    },
    timeout=20,
)

response.raise_for_status()

print("Testnachricht erfolgreich gesendet.")

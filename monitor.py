import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


SPARKASSE_URL = (
    "https://immobilien.sparkasse.de/immobilien/treffer"
    "?estateTypeGroupingId=396"
    "&marketingType=buy"
    "&perimeter=5"
    "&sortBy=default_asc"
    "&usageType=residential"
    "&zipCityEstateId=52.03608%2F6.82402%2F0__Vreden"
)

VR_URL = (
    "https://www.vr.de/privatkunden/immobilien/immobiliensuche.html"
    "?l=48691%2C+Vreden&d=10&lat=52.060807&lng=6.796994"
)

STATE_FILE = Path("seen.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}


def load_seen():
    if not STATE_FILE.exists():
        return set()

    try:
        return set(json.loads(STATE_FILE.read_text()))
    except Exception:
        return set()


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2)
    )


def send_ntfy(message):
    topic = os.environ["NTFY_TOPIC"]

    response = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={
            "Title": "Neues Immobilien-Inserat",
            "Priority": "high",
            "Tags": "house",
        },
        timeout=20,
    )

    response.raise_for_status()


def get_sparkasse():
    response = requests.get(
        SPARKASSE_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    # Die Inserate sind auf der aktuellen Seite als Links vorhanden.
    for link in soup.find_all("a", href=True):
        href = link["href"]

        if "/immobilien/" not in href:
            continue

        text = " ".join(link.stripped_strings)

        if len(text) < 20:
            continue

        full_url = urljoin(SPARKASSE_URL, href)

        # URL als stabile Kennung verwenden
        key = f"sparkasse:{full_url}"

        results.append({
            "key": key,
            "source": "Sparkasse",
            "title": text,
            "url": full_url,
        })

    # Duplikate entfernen
    unique = {}
    for item in results:
        unique[item["key"]] = item

    return list(unique.values())


def get_vr():
    """
    Die VR-Seite lädt die eigentliche Immobiliensuche dynamisch.
    Dieser erste Test versucht, mögliche Immobilienlinks aus
    dem ausgelieferten HTML zu erkennen.

    Falls die VR-Seite die Ergebnisse erst per JavaScript/API lädt,
    erweitern wir diesen Teil nach dem ersten Test mit Playwright.
    """
    response = requests.get(
        VR_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for link in soup.find_all("a", href=True):
        href = link["href"]

        if "immobilien" not in href.lower():
            continue

        text = " ".join(link.stripped_strings)

        if len(text) < 20:
            continue

        full_url = urljoin(VR_URL, href)

        results.append({
            "key": f"vr:{full_url}",
            "source": "VR",
            "title": text,
            "url": full_url,
        })

    unique = {}
    for item in results:
        unique[item["key"]] = item

    return list(unique.values())


def main():
    seen = load_seen()

    all_results = []

    try:
        all_results.extend(get_sparkasse())
    except Exception as e:
        print(f"Sparkasse Fehler: {e}")

    try:
        all_results.extend(get_vr())
    except Exception as e:
        print(f"VR Fehler: {e}")

    print(f"Gefundene Einträge: {len(all_results)}")

    new_items = [
        item for item in all_results
        if item["key"] not in seen
    ]

    # Beim ersten Lauf nur Bestand speichern.
    # Dadurch bekommst du nicht sofort 6 alte Sparkassen-Inserate als Alarm.
    if not seen:
        print("Erster Lauf – vorhandene Inserate werden als Bestand gespeichert.")

        for item in all_results:
            seen.add(item["key"])

        save_seen(seen)
        return

    for item in new_items:
        message = (
            f"Quelle: {item['source']}\n\n"
            f"{item['title']}\n\n"
            f"{item['url']}"
        )

        print(f"NEU: {item['source']} – {item['title']}")
        send_ntfy(message)

        seen.add(item["key"])

    save_seen(seen)

    print(f"Neue Inserate: {len(new_items)}")


if __name__ == "__main__":
    main()

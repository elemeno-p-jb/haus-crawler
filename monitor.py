import json
import os
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


def send_ntfy(item):
    topic = os.environ["NTFY_TOPIC"]

    message = (
        f"Quelle: {item['source']}\n\n"
        f"{item['title']}\n\n"
        f"{item['url']}"
    )

    response = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={
            "Title": f"Neues Inserat – {item['source']}",
            "Priority": "high",
            "Tags": "house",
            "Click": item["url"],
        },
        timeout=20,
    )

    response.raise_for_status()


def extract_links(html, base_url, source):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()

        if not href:
            continue

        text = " ".join(link.stripped_strings).strip()

        if len(text) < 20:
            continue

        full_url = urljoin(base_url, href)

        results.append(
            {
                "key": f"{source}:{full_url}",
                "source": source,
                "title": text[:300],
                "url": full_url,
            }
        )

    unique = {}

    for item in results:
        unique[item["key"]] = item

    return list(unique.values())


def get_sparkasse():
    print("Prüfe Sparkasse ...")

    response = requests.get(
        SPARKASSE_URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    results = extract_links(
        response.text,
        SPARKASSE_URL,
        "Sparkasse",
    )

    print(f"Sparkasse: {len(results)} mögliche Einträge")

    return results


def get_vr():
    print("Prüfe VR ...")

    response = requests.get(
        VR_URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    results = extract_links(
        response.text,
        VR_URL,
        "VR",
    )

    print(f"VR: {len(results)} mögliche Einträge")

    return results


def main():
    seen = load_seen()

    sparkasse = []
    vr = []

    try:
        sparkasse = get_sparkasse()
    except Exception as e:
        print(f"Sparkasse FEHLER: {e}")

    try:
        vr = get_vr()
    except Exception as e:
        print(f"VR FEHLER: {e}")

    all_results = sparkasse + vr

    print()
    print("================================")
    print(f"Sparkasse: {len(sparkasse)}")
    print(f"VR:        {len(vr)}")
    print(f"Gesamt:    {len(all_results)}")
    print("================================")
    print()

    # Erster Lauf:
    # vorhandenen Bestand nur speichern.
    if not seen:
        print("Erster Lauf – Bestand wird gespeichert.")

        for item in all_results:
            seen.add(item["key"])

        save_seen(seen)

        print(f"{len(all_results)} Einträge gespeichert.")
        return

    new_items = [
        item
        for item in all_results
        if item["key"] not in seen
    ]

    print(f"Neue Inserate: {len(new_items)}")

    for item in new_items:
        print()
        print("NEUES INSERAT")
        print(f"Quelle: {item['source']}")
        print(f"Titel:  {item['title']}")
        print(f"URL:    {item['url']}")

        try:
            send_ntfy(item)
            print("Push: OK")
        except Exception as e:
            print(f"Push FEHLER: {e}")
            continue

        seen.add(item["key"])

    save_seen(seen)


if __name__ == "__main__":
    main()

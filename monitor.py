import json
import os
import re
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


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
    "?l=48691%2C+Vreden"
    "&d=10"
    "&lat=52.060807"
    "&lng=6.796994"
)

NTFY_TOPIC = os.environ["NTFY_TOPIC"]

# Eigene Datei, damit die alten, zu breit erkannten Einträge
# nicht mit dem neuen System vermischt werden.
SEEN_FILE = "seen_v2.json"


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def send_ntfy(title, message, url):
    try:
        response = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            headers={
                # Nur ASCII im Header verwenden!
                "Title": title,
                "Priority": "high",
                "Tags": "house",
                "Click": url,
            },
            data=message.encode("utf-8"),
            timeout=20,
        )

        response.raise_for_status()
        print(f"Push OK: {title}")

        return True

    except Exception as e:
        print(f"Push FEHLER: {e}")
        return False


def get_sparkasse():
    print("Prüfe Sparkasse ...")

    try:
        response = requests.get(
            SPARKASSE_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/131 Safari/537.36"
                )
            },
            timeout=30,
        )
        response.raise_for_status()

    except Exception as e:
        print(f"Sparkasse FEHLER: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    listings = {}

    # Bei Sparkasse sind die echten Exposés an /expose/ erkennbar.
    for link in soup.find_all("a", href=True):
        href = link["href"]

        if "/expose/" not in href:
            continue

        if href.startswith("/"):
            href = "https://immobilien.sparkasse.de" + href

        title = link.get_text(" ", strip=True)

        # Falls der Link selbst keinen brauchbaren Text enthält,
        # versuchen wir den umgebenden Container.
        if len(title) < 20:
            parent = link.find_parent()
            if parent:
                title = parent.get_text(" ", strip=True)

        if not title:
            title = "Neues Sparkassen-Inserat"

        listings[href] = {
            "source": "Sparkasse",
            "url": href,
            "title": title,
        }

    print(f"Sparkasse: {len(listings)} echte Inserate")
    return list(listings.values())


def get_vr():
    print("\nPrüfe VR ...")

    listings = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox"],
            )

            page = browser.new_page(
                viewport={"width": 1440, "height": 1000},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/131 Safari/537.36"
                ),
            )

            page.goto(
                VR_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            # Die VR-Suche wird dynamisch geladen.
            page.wait_for_timeout(8000)

            # Alle Frames untersuchen, da die Immobiliensuche
            # gegebenenfalls in einem eingebetteten Bereich läuft.
            for frame in page.frames:
                try:
                    links = frame.locator("a[href]").all()

                    for link in links:
                        try:
                            href = link.get_attribute("href")
                            text = link.inner_text().strip()
                        except Exception:
                            continue

                        if not href:
                            continue

                        href_lower = href.lower()

                        # Offensichtliche Navigationslinks ignorieren.
                        if any(
                            x in href_lower
                            for x in [
                                "youtube.com",
                                "linkedin.com",
                                "werte-mitgliedschaft",
                                "karte-sperren",
                                "baufinanzierungsrechner",
                                "grundstuecke.html",
                            ]
                        ):
                            continue

                        # Kandidaten für Immobilien-Inserate.
                        candidate = (
                            "/expose" in href_lower
                            or "/immobilien/" in href_lower
                            or "immobilie" in href_lower
                            or "estate" in href_lower
                            or "property" in href_lower
                        )

                        if not candidate:
                            continue

                        if href.startswith("/"):
                            href = "https://www.vr.de" + href

                        if not href.startswith("http"):
                            continue

                        # Sehr kurze/technische Links aussortieren.
                        if len(text) < 10:
                            continue

                        listings[href] = {
                            "source": "VR",
                            "url": href,
                            "title": text,
                        }

                except Exception:
                    continue

            browser.close()

    except Exception as e:
        print(f"VR FEHLER: {e}")

    print(f"VR: {len(listings)} mögliche echte Inserate")
    return list(listings.values())


def main():
    print("================================")
    print("Immobilien-Monitor")
    print("================================\n")

    seen = load_seen()

    sparkasse = get_sparkasse()
    vr = get_vr()

    all_listings = sparkasse + vr

    print("\n================================")
    print(f"Sparkasse: {len(sparkasse)}")
    print(f"VR:        {len(vr)}")
    print(f"Gesamt:    {len(all_listings)}")
    print("================================")

    # Beim allerersten Lauf werden die aktuell vorhandenen
    # Inserate nur gespeichert, nicht als "neu" gemeldet.
    if not seen:
        print("\nErster Lauf: aktuelle Inserate werden gespeichert.")
        print("Noch keine Push-Nachrichten.")
        save_seen({item["url"] for item in all_listings})
        return

    new_items = [
        item
        for item in all_listings
        if item["url"] not in seen
    ]

    print(f"\nNeue Inserate: {len(new_items)}")

    successfully_processed = []

    for item in new_items:
        title = re.sub(r"\s+", " ", item["title"]).strip()

        print(f"\nNEU: {item['source']}")
        print(title)
        print(item["url"])

        # ASCII-only title für den HTTP-Header.
        ntfy_title = f"Neues Inserat - {item['source']}"

        message = (
            f"{title}\n\n"
            f"Quelle: {item['source']}\n"
            f"{item['url']}"
        )

        if send_ntfy(
            ntfy_title,
            message,
            item["url"],
        ):
            successfully_processed.append(item["url"])

    # Nur erfolgreich verarbeitete neue Inserate als bekannt speichern.
    seen.update(successfully_processed)
    save_seen(seen)

    print("\n================================")
    print("Fertig.")
    print(f"Neu verarbeitet: {len(successfully_processed)}")
    print("================================")


if __name__ == "__main__":
    main()

"""
Webseiten-Monitor für GitHub Actions – mit ntfy-Push aufs Handy.
Läuft in der Cloud, deine Geräte können ausgeschaltet sein.

Seiten werden in seiten.json konfiguriert.
Das ntfy-Topic kommt aus dem GitHub Secret NTFY_TOPIC.
"""

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

BASIS = Path(__file__).parent
KONFIG = BASIS / "seiten.json"
STAND = BASIS / "stand.json"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def lade(pfad, standard):
    if pfad.exists():
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return standard


def nur_ascii(text: str) -> str:
    """HTTP-Header vertragen keine Umlaute – daher umwandeln."""
    ersetzt = (text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                   .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
                   .replace("ß", "ss"))
    return unicodedata.normalize("NFKD", ersetzt).encode("ascii", "ignore").decode()


def sende_push(titel: str, text: str, klick_url: str = "") -> None:
    """Schickt eine Push-Nachricht über ntfy an dein Handy."""
    if not NTFY_TOPIC:
        print("  ⚠ Kein NTFY_TOPIC gesetzt – Push übersprungen.")
        return
    kopf = {
        "Title": nur_ascii(titel),
        "Priority": "high",
        "Tags": "bell,shopping",
    }
    if klick_url:
        # Tippen auf die Meldung öffnet direkt das Produkt
        kopf["Click"] = klick_url
    req = Request(f"{NTFY_SERVER}/{NTFY_TOPIC}",
                  data=text.encode("utf-8"), headers=kopf)
    try:
        with urlopen(req, timeout=20) as r:
            r.read()
        print("  🔔 Push verschickt.")
    except Exception as e:
        print(f"  ⚠ Push fehlgeschlagen: {e}")


def sammle_urls(start_url: str, max_seiten: int) -> set[str]:
    """Sammelt URLs der Domain: erst Sitemap, dann Crawling ab der Startseite."""
    parsed = urlparse(start_url)
    basis = f"{parsed.scheme}://{parsed.netloc}"
    gefunden: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(
            locale="de-DE", user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        # 1) Sitemap – dort listet die Seite ihre Unterseiten selbst auf
        try:
            page.goto(f"{basis}/sitemap.xml", timeout=45_000)
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", page.content())
            gefunden.update(u.split("?")[0] for u in locs
                            if parsed.netloc in u and not u.endswith(".xml"))
            for unter in [u for u in locs if u.endswith(".xml")][:5]:
                try:
                    page.goto(unter, timeout=45_000)
                    gefunden.update(
                        u.split("?")[0]
                        for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", page.content())
                        if parsed.netloc in u and not u.endswith(".xml"))
                except Exception:
                    pass
            if gefunden:
                print(f"  Sitemap: {len(gefunden)} Seiten")
        except Exception as e:
            print(f"  Keine Sitemap ({type(e).__name__})")

        # 2) Crawling ab der Startseite
        warteschlange, besucht = [start_url], set()
        while warteschlange and len(besucht) < max_seiten:
            url = warteschlange.pop(0)
            if url in besucht:
                continue
            besucht.add(url)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                time.sleep(5)
                for _ in range(4):
                    page.mouse.wheel(0, 2500)
                    time.sleep(1.2)
                links = page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(a => a.href.split('#')[0].split('?')[0])")
                for link in links:
                    if link.startswith(basis):
                        neu = link not in gefunden
                        gefunden.add(link)
                        if neu and link not in besucht and len(besucht) < max_seiten:
                            warteschlange.append(link)
            except Exception:
                continue
        print(f"  Crawl: {len(besucht)} Seiten besucht")
        browser.close()
    return gefunden


def main() -> None:
    konfig = lade(KONFIG, {"seiten": []})
    stand = lade(STAND, {})
    aenderung = False

    if not NTFY_TOPIC:
        print("⚠ Secret NTFY_TOPIC fehlt – es werden keine Push-Nachrichten verschickt.")

    for eintrag in konfig["seiten"]:
        url = eintrag["url"]
        max_seiten = eintrag.get("max_seiten", 25)
        name = urlparse(url).netloc
        print(f"\n▶ {url}")
        try:
            aktuelle = sammle_urls(url, max_seiten)
        except Exception as e:
            print(f"  ⚠ Fehler: {e}")
            continue

        if not aktuelle:
            print("  ⚠ Nichts gefunden (Bot-Schutz?) – Stand bleibt unverändert.")
            continue

        bekannte = set(stand.get(url, []))
        if not bekannte:
            print(f"  Erster Lauf: {len(aktuelle)} Seiten erfasst.")
        else:
            neue = sorted(aktuelle - bekannte)
            if neue:
                print(f"  🎉 {len(neue)} neue Seiten!")
                for u in neue[:20]:
                    print(f"     {u}")
                text = "\n\n".join(neue[:8])
                if len(neue) > 8:
                    text += f"\n\n… und {len(neue) - 8} weitere."
                sende_push(
                    titel=f"{len(neue)} neue Seiten: {name}",
                    text=text,
                    klick_url=neue[0],
                )
            else:
                print("  Keine neuen Seiten.")

        stand[url] = sorted(bekannte | aktuelle)
        aenderung = True

    if aenderung:
        STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print("\nStand gespeichert.")
    else:
        print("\nKein Durchlauf erfolgreich – Stand unverändert.")
        sys.exit(0)


if __name__ == "__main__":
    main()

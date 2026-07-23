"""
Webseiten-Monitor für GitHub Actions – mit ntfy-Push aufs Handy.
Läuft in der Cloud, deine Geräte können ausgeschaltet sein.

Meldet neue Produkte in Portionen zu je 8 Stück – alle, nichts wird
abgeschnitten. Jedes Produkt mit lesbarem Namen und Direktlink.

Konfiguration in seiten.json, ntfy-Topic im Secret NTFY_TOPIC.
"""

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

BASIS = Path(__file__).parent
KONFIG = BASIS / "seiten.json"
STAND = BASIS / "stand.json"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

PRO_NACHRICHT = 8        # Produkte pro Push-Nachricht
MAX_NACHRICHTEN = 30     # Sicherheitsgrenze gegen ntfy-Ratelimit
PAUSE = 2                # Sekunden zwischen den Nachrichten


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


def name_aus_url(url: str) -> str:
    """Leitet aus der URL einen lesbaren Produktnamen ab.
    .../product/70-11095-101/pokemon-trainer-umhaengetasche
        → 'Pokemon Trainer Umhaengetasche'
    """
    segmente = [s for s in urlparse(url).path.split("/") if s]
    teil = ""
    for seg in reversed(segmente):
        kandidat = unquote(seg)
        # ID-Segmente wie "70-11095-101" überspringen
        if re.fullmatch(r"[\d\-_]+", kandidat):
            continue
        if re.search(r"[a-zA-Z]", kandidat):
            teil = kandidat
            break
    if not teil:
        return url
    return re.sub(r"[-_]+", " ", teil).strip().title()


def sende_push(titel: str, text: str, klick_url: str = "",
               tags: str = "bell") -> bool:
    """Schickt eine Push-Nachricht über ntfy."""
    if not NTFY_TOPIC:
        print("  ⚠ Kein NTFY_TOPIC gesetzt – Push übersprungen.")
        return False
    kopf = {"Title": nur_ascii(titel), "Priority": "high", "Tags": tags}
    if klick_url:
        kopf["Click"] = klick_url
    req = Request(f"{NTFY_SERVER}/{NTFY_TOPIC}",
                  data=text.encode("utf-8"), headers=kopf)
    try:
        with urlopen(req, timeout=20) as r:
            r.read()
        return True
    except Exception as e:
        print(f"  ⚠ Push fehlgeschlagen: {e}")
        return False


def melde_produkte(neue: list[str], shop: str, start_url: str) -> None:
    """Verschickt alle neuen Produkte portionsweise, je PRO_NACHRICHT Stück."""
    pakete = [neue[i:i + PRO_NACHRICHT]
              for i in range(0, len(neue), PRO_NACHRICHT)]
    gesamt = len(pakete)

    if gesamt > MAX_NACHRICHTEN:
        sende_push(
            titel=f"{len(neue)} neue Produkte – sehr viele!",
            text=(f"Es sind {len(neue)} neue Produkte aufgetaucht. "
                  f"Das sind zu viele fuer Einzelmeldungen. "
                  f"Schau direkt im Shop nach."),
            klick_url=start_url, tags="warning")
        print(f"  ⚠ {len(neue)} neue Produkte – zu viele, nur Sammelmeldung.")
        return

    verschickt = 0
    for nr, paket in enumerate(pakete, 1):
        zeilen = []
        for pos, url in enumerate(paket, 1):
            zeilen.append(f"{pos}. {name_aus_url(url)}\n{url}")
        titel = (f"🆕 {len(neue)} neue Produkte ({nr}/{gesamt})"
                 if gesamt > 1 else f"🆕 {len(neue)} neue Produkte")
        if sende_push(titel=titel, text="\n\n".join(zeilen),
                      klick_url=paket[0], tags="new,shopping"):
            verschickt += 1
        if nr < gesamt:
            time.sleep(PAUSE)
    print(f"  🔔 {verschickt} von {gesamt} Nachrichten verschickt.")


def sammle_sitemap_urls(page, sitemap_url: str, netloc: str) -> set[str]:
    """Liest eine Sitemap (auch Sitemap-Index) rekursiv aus."""
    urls: set[str] = set()
    try:
        page.goto(sitemap_url, timeout=60_000)
        inhalt = page.content()
    except Exception:
        return urls
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", inhalt)
    unter = [u for u in locs if u.endswith(".xml")]
    urls.update(u.split("?")[0] for u in locs
                if netloc in u and not u.endswith(".xml"))
    # Produkt-Sitemaps zuerst
    reihenfolge = sorted(unter, key=lambda u: "product" not in u.lower())
    for sm in reihenfolge[:10]:
        try:
            page.goto(sm, timeout=60_000)
            for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", page.content()):
                if netloc in u and not u.endswith(".xml"):
                    urls.add(u.split("?")[0])
        except Exception:
            continue
    return urls


def sammle_urls(start_url: str, max_seiten: int) -> set[str]:
    """Sammelt alle URLs der Domain über die Sitemap (+ optional Crawl)."""
    parsed = urlparse(start_url)
    basis = f"{parsed.scheme}://{parsed.netloc}"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(
            locale="de-DE", user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        alle = sammle_sitemap_urls(page, f"{basis}/sitemap.xml", parsed.netloc)
        print(f"  Sitemap: {len(alle)} URLs")

        if max_seiten > 0:
            besucht = set()
            warteschlange = [start_url]
            while warteschlange and len(besucht) < max_seiten:
                url = warteschlange.pop(0)
                if url in besucht:
                    continue
                besucht.add(url)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    time.sleep(4)
                    for _ in range(3):
                        page.mouse.wheel(0, 2500)
                        time.sleep(1)
                    links = page.eval_on_selector_all(
                        "a[href]",
                        "els => els.map(a => a.href.split('#')[0].split('?')[0])")
                    alle.update(l for l in links if l.startswith(basis))
                except Exception:
                    continue
            print(f"  Crawl: {len(besucht)} Seiten besucht")

        browser.close()
    return alle


def main() -> None:
    konfig = lade(KONFIG, {"seiten": []})
    stand = lade(STAND, {})
    aenderung = False

    if not NTFY_TOPIC:
        print("⚠ Secret NTFY_TOPIC fehlt – keine Push-Nachrichten.")

    for eintrag in konfig["seiten"]:
        url = eintrag["url"]
        max_seiten = eintrag.get("max_seiten", 0)
        muster = re.compile(eintrag.get("produkt_muster", r"/product/"), re.I)
        nur_pfad = eintrag.get("nur_pfad", "")   # z.B. "/de-de/"
        shop = urlparse(url).netloc
        print(f"\n▶ {url}")

        try:
            alle = sammle_urls(url, max_seiten)
        except Exception as e:
            print(f"  ⚠ Fehler: {e}")
            continue

        produkte = {u for u in alle if muster.search(u)}
        if nur_pfad:
            produkte = {u for u in produkte if nur_pfad in u}
            print(f"  Produkte (nur {nur_pfad}): {len(produkte)}")
        else:
            print(f"  Produkte: {len(produkte)}")

        if not produkte:
            print("  ⚠ Nichts gefunden – Stand bleibt unverändert.")
            continue

        bekannte = set(stand.get(url, []))
        if not bekannte:
            print(f"  Erster Lauf: {len(produkte)} erfasst (keine Meldung).")
        else:
            neue = sorted(produkte - bekannte)
            if neue:
                print(f"  🎉 {len(neue)} NEUE Produkte:")
                for u in neue[:20]:
                    print(f"     {name_aus_url(u)}  →  {u}")
                melde_produkte(neue, shop, url)
            else:
                print("  Keine neuen Produkte.")

        stand[url] = sorted(bekannte | produkte)
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

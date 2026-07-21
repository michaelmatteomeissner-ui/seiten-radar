"""
Webseiten-Monitor für GitHub Actions.
Läuft in der Cloud – dein Handy und PC können ausgeschaltet sein.

Konfiguriert wird alles in seiten.json.
Zugangsdaten kommen aus GitHub Secrets (Umgebungsvariablen).
"""

import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASIS = Path(__file__).parent
KONFIG = BASIS / "seiten.json"
STAND = BASIS / "stand.json"

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORT = os.environ.get("SMTP_PASSWORT", "")
EMPFAENGER = os.environ.get("EMPFAENGER", "")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def lade(pfad, standard):
    if pfad.exists():
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return standard


def sammle_urls(start_url: str, max_seiten: int) -> set[str]:
    """Sammelt URLs der Domain: erst Sitemap, dann Crawling der Startseite."""
    parsed = urlparse(start_url)
    basis = f"{parsed.scheme}://{parsed.netloc}"
    gefunden: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(
            locale="de-DE", user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900})
        # Automatisierungs-Merkmal verstecken
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        # 1) Sitemap – die Seite listet ihre Unterseiten dort selbst auf
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


def sende_mail(betreff: str, html: str) -> None:
    if not (SMTP_USER and SMTP_PASSWORT and EMPFAENGER):
        print("  ⚠ E-Mail nicht konfiguriert – Secrets fehlen.")
        return
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = betreff
    msg["From"] = SMTP_USER
    msg["To"] = EMPFAENGER
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASSWORT)
        s.send_message(msg)
    print("  ✉ E-Mail verschickt.")


def main() -> None:
    konfig = lade(KONFIG, {"seiten": []})
    stand = lade(STAND, {})
    aenderung = False

    for eintrag in konfig["seiten"]:
        url = eintrag["url"]
        max_seiten = eintrag.get("max_seiten", 25)
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
                zeilen = "".join(f'<li><a href="{u}">{u}</a></li>' for u in neue[:60])
                rest = (f"<p>… und {len(neue) - 60} weitere.</p>"
                        if len(neue) > 60 else "")
                sende_mail(
                    f"🔔 {len(neue)} neue Seiten: {urlparse(url).netloc}",
                    f"<h2>{len(neue)} neue Seiten auf {urlparse(url).netloc}</h2>"
                    f"<ul>{zeilen}</ul>{rest}"
                    f"<p><small>Gefunden am {datetime.now():%d.%m.%Y %H:%M} UTC</small></p>")
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

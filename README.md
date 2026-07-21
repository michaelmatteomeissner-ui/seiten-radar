# Seiten-Radar

Überwacht Webseiten samt Unterseiten und schickt eine E-Mail mit Direktlinks,
sobald neue Seiten auftauchen. Läuft in GitHub Actions — **dein Handy und PC
können komplett ausgeschaltet sein.**

## Einrichtung (ca. 10 Minuten)

### 1. Repository anlegen

1. Auf github.com einloggen (kostenloses Konto genügt)
2. **New repository** → Name z. B. `seiten-radar` → **Public** wählen
   *(Public = unbegrenzte kostenlose Laufzeit. Private hat nur 2.000 Minuten
   im Monat, das reicht bei 15-Minuten-Takt nicht.)*
3. Alle Dateien aus diesem Ordner hochladen — inklusive des Ordners
   `.github/workflows/`. Beim Hochladen im Browser: **Add file → Upload files**,
   dann den gesamten Ordnerinhalt hineinziehen.

### 2. E-Mail-Zugang hinterlegen

Im Repository: **Settings → Secrets and variables → Actions →
New repository secret**. Diese fünf Einträge anlegen:

| Name | Wert (Beispiel Gmail) |
|---|---|
| `SMTP_SERVER` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `deine.adresse@gmail.com` |
| `SMTP_PASSWORT` | dein 16-stelliges **App-Passwort** |
| `EMPFAENGER` | `deine.adresse@gmail.com` |

**App-Passwort bei Gmail:** Google-Konto → Sicherheit → Bestätigung in zwei
Schritten aktivieren → dann erscheint der Punkt „App-Passwörter". Dort eines
erzeugen. Das normale Kontopasswort funktioniert nicht.

Andere Anbieter:
- GMX: `mail.gmx.net`, Port `587`
- Web.de: `smtp.web.de`, Port `587`
- Outlook: `smtp-mail.outlook.com`, Port `587`

### 3. Seiten festlegen

`seiten.json` bearbeiten. Beliebig viele Einträge möglich:

```json
{
  "seiten": [
    { "url": "https://www.pokemoncenter.com/de-de", "max_seiten": 25 },
    { "url": "https://beispiel-shop.de/neuheiten", "max_seiten": 15 }
  ]
}
```

`max_seiten` begrenzt, wie viele Unterseiten aktiv besucht werden. Gefundene
Links werden trotzdem alle erfasst — höhere Werte kosten nur Laufzeit.

### 4. Takt einstellen

In `.github/workflows/monitor.yml` die Zeile mit `cron`:

- `*/15 * * * *` = alle 15 Minuten
- `*/30 * * * *` = alle 30 Minuten
- `0 * * * *` = stündlich zur vollen Stunde

Unter 5 Minuten lässt GitHub nicht zu. Der Zeitplan ist außerdem
„best effort": bei hoher Auslastung kann ein Lauf 10–20 Minuten später
starten. Für Produktbeobachtung ist das unerheblich.

### 5. Starten

Reiter **Actions** → „Seiten-Radar" → **Run workflow**. Der erste Lauf erfasst
nur den Ist-Zustand und schickt noch keine Mail. Ab dem zweiten Lauf kommen
Benachrichtigungen. Danach läuft alles automatisch weiter.

## Gut zu wissen

**Bot-Schutz.** Das Pokémon Center blockiert Zugriffe aus Rechenzentren recht
zuverlässig — GitHubs Server gehören dazu. Wenn im Actions-Protokoll
`⚠ Nichts gefunden` steht, ist genau das passiert. Der gespeicherte Stand
bleibt dann unangetastet, du bekommst also keine falschen Meldungen. Bei
normalen Shops und Blogs funktioniert es in aller Regel problemlos. Falls es
dauerhaft blockiert wird, ist ein Raspberry Pi im Heimnetz die Alternative —
der greift über deine normale Privat-IP zu und fällt deutlich weniger auf.

**Ruhende Repositories.** GitHub schaltet Zeitpläne ab, wenn 60 Tage lang
niemand am Repository arbeitet. Der Workflow committet zwar bei jedem Lauf,
das zählt aber nicht immer als Aktivität. Falls die Mails irgendwann
ausbleiben: einmal in **Actions** auf **Enable workflow** klicken.

**Kosten.** Bei einem öffentlichen Repository entstehen keine.

**Zeitzone.** Die Protokolle und Zeitstempel in den Mails sind in UTC,
im Sommer also zwei Stunden vor deutscher Zeit.

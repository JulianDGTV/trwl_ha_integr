# 🚆 Träwelling für Home Assistant · v1.9.5

Custom Integration für [traewelling.de](https://traewelling.de): deine laufende
Fahrt, die Fahrten deiner Freunde, deine Reisestatistiken – und Check-in direkt
aus dem Dashboard.

> [!NOTE]
> **Inoffizielles Projekt der [V8B KG](https://v8b.eco).** Träwelling selbst wird
> vom nicht gewinnorientierten **[Träwelling e.V.](https://traewelling.org)**
> betrieben. Diese Integration ist davon unabhängig und nicht mit dem Verein
> verbunden.
>
> 💚 Dir gefällt Träwelling? **[Unterstütze den Träwelling e.V. mit einer
> Spende](https://traewelling.org/support-us)** – per Überweisung oder z. B.
> [GitHub Sponsors](https://github.com/sponsors/Traewelling) – und hilf, Träwelling
> am Laufen zu halten.

## ✨ Features

- **Meine Fahrt** – Linie, Start/Ziel, Zeiten, Verspätung, Gleis, Fortschritt, Restzeit
- **Nächste Fahrt & Anschlüsse** – eingecheckte Fahrten, die in der nächsten Stunde starten, erscheinen als „Bald unterwegs“; dahinter die ganze eingecheckte Reisekette (Anschluss → Anschluss → …) mit Live-Umstiegszeiten aus Plan- und Echtzeitdaten
- **Freunde unterwegs** – alle gerade laufenden und bald startenden Fahrten der Accounts, denen du folgst, mit Link zum Profil
- **Check-in-Karte** – Station suchen (oder per Standort), Live-Abfahrten mit Verspätung und Gleis, Ausstieg wählen, Fahrkarte (z. B. BahnCard 100) hinterlegen, einchecken – auch als Anschluss während einer laufenden Fahrt
- **Freunde-Karte** – laufende und bald startende Fahrten deiner Freunde im selben Design wie die eigene Fahrt („in 15 min“, „Danach: …“), Name antippen → Profil, ❤️ Like direkt aus der Karte
- **Statistik-Karte** – Kennzahlen für Woche, Monat, Jahr und gesamt, Balkendiagramm der letzten 12 Monate (Check-ins/km), längste Fahrt, Favoriten, Freunde-Rangliste
- **Favoriten** – Lieblingsstationen, -linien und -strecken des laufenden Jahres (in der Statistik-Karte)
- **Freunde-Rangliste** – dein Rang unter Freunden (Punkte der letzten 7 Tage)
- **Services** für Stationssuche, Abfahrten, Fahrtverlauf und Check-in – nutzbar in eigenen Automationen

## 📦 Installation

**HACS (empfohlen):** HACS → ⋮ → *Benutzerdefinierte Repositories* →
`https://github.com/v8b-kg/trwl_ha_integr`, Kategorie *Integration* →
*Träwelling* herunterladen → Home Assistant neu starten.

**Updates:** Jede Version erscheint als [GitHub-Release](https://github.com/v8b-kg/trwl_ha_integr/releases).
Home Assistant meldet neue Versionen dann von selbst unter *Einstellungen → Updates* –
mit Changelog; *Installieren* und anschließend neu starten.

**Manuell:** Ordner `custom_components/traewelling` nach
`<config>/custom_components/traewelling` kopieren und neu starten.

Danach: **Einstellungen → Geräte & Dienste → Integration hinzufügen → Träwelling**.

## 🔑 Access Token

Auf traewelling.de unter **Einstellungen → API / Anwendungen** einen persönlichen
Access Token anlegen:

| Scope | Wofür |
|---|---|
| `read-statuses` | aktive Fahrt und Fahrten deiner Freunde |
| `read-statistics` | Statistik-Sensoren |
| `write-statuses` | Check-in-Karte (Stationen, Abfahrten, Einchecken, Fahrkarte) |
| `write-likes` | Freunden in der Freunde-Karte Likes geben |

Fehlt ein Scope, läuft der Rest trotzdem weiter – nur der betroffene Teil bleibt
leer bzw. zeigt einen Hinweis.

**Token austauschen** (z. B. um `write-statuses` nachzurüsten):
Einstellungen → Geräte & Dienste → Träwelling → ⋮ → **Neu konfigurieren**.

## 📊 Entitäten

> Die Entity-IDs enthalten den Gerätenamen, z. B.
> `sensor.trawelling_deinname_punkte_gesamt`. Unten steht jeweils nur das Ende.
> Die Dashboard-Vorlage findet die Entitäten automatisch.

**Aktive Fahrt** (standardmäßig jede Minute, solange eine eigene Fahrt läuft oder in Kürze startet – sonst alle 5 min)

| Entität endet auf | Beschreibung |
|---|---|
| `binary_sensor…_unterwegs` | An, solange ein Check-in läuft; alle Fahrtdetails als Attribute |
| `…_aktuelle_fahrt` | Linienname, z. B. „RE 5“ |
| `…_start` / `…_ziel` | Start- und Zielhaltestelle |
| `…_abfahrt` / `…_ankunft` | Zeitstempel (Echtzeit, sonst Plan) |
| `…_verspatung_abfahrt` / `…_verspatung_ankunft` | Minuten |
| `…_restfahrzeit` | Minuten bis Ankunft |
| `…_fahrtfortschritt` | 0–100 % |
| `…_distanz_aktuelle_fahrt` / `…_punkte_aktuelle_fahrt` | km / Punkte |

**Nächste Fahrt**

| Entität endet auf | Beschreibung |
|---|---|
| `…_nachste_fahrt` | Abfahrtszeit deiner nächsten eingecheckten Fahrt (während einer Fahrt: der erste Anschluss, sonst innerhalb 1 h); Details wie bei der aktiven Fahrt als Attribute, dazu `minutes_until`, `after_current`, `chain` (alle Anschlüsse inkl. `transfer`), `transfers`, `warnings`, `final_destination`, `final_arrival` |
| `…_nachster_umstieg` | Minuten für den nächsten Umstieg nach Echtzeit; Attribute `minutes_planned`, `rating` (`ok`, `tight`, `risk`, `missed`, `cancelled`, `unknown` = Anschluss ohne Echtzeit, `conflict` = laut Fahrplan unmöglich), `warning` (Klartext), `arrival_source`/`departure_source` (`live`, `board`, `estimate`, `manual`, `plan`), `station`, `arrival_platform`, `departure_platform`, `to_station`/`walk_m` (bei Stationswechsel), `from_line`, `to_line` |

**Reisekette:** Nach der laufenden Fahrt (bzw. der nächsten Fahrt) sucht die Integration den frühesten eigenen Check-in, der nach der planmäßigen Ankunft startet (max. 3 h später) – und von dort den nächsten usw. Umstiegszeiten werden aus Ankunft und Abfahrt berechnet (manuell > Echtzeit > Plan). Bei verschiedenen Stationen (z. B. Hbf → ZOB) wird die Luftlinie als Fußweg eingerechnet.

**Warnungen:** Knappe, gefährdete, verpasste oder ausgefallene Umstiege werden markiert, ebenso „unlogische“ Check-ins, die laut Fahrplan schon vor der Ankunft abfahren – die Kette läuft trotzdem weiter und zeigt alle folgenden Fahrten. Hat die Ankunft Echtzeit (verspätet), der Anschluss aber nicht, wird er nicht als verpasst gewertet, sondern als „unklar“. Dann holt die Integration die Echtzeit des Anschlusses von der Live-Abfahrtstafel der Umstiegsstation (je Anschluss höchstens alle 3 min). Fährt ein Anschluss verspätet ab, wird seine Ankunft mit derselben Verspätung geschätzt (`~+55`).

Quellen: eigene Status im Dashboard (bis ~20 min voraus, jede Minute mit Echtzeit), `/dashboard/future` (alle 5 min, >20 min voraus – Träwelling holt Echtzeit ohnehin erst ab 20 min vor Abfahrt) und jeder Check-in über die Karte, der sofort übernommen wird. Fehlt eine Fahrt kurz vor Abfahrt im Dashboard (z. B. vor über 7 Tagen eingecheckt), wird sie einzeln über `/status/{id}` nachgeladen. Gelöschte Check-ins verschwinden automatisch. Solange eine andere Fahrt noch läuft, bleibt diese die Hauptanzeige.

**Freunde unterwegs** (zusammen mit der aktiven Fahrt abgefragt)

| Entität endet auf | Beschreibung |
|---|---|
| `…_freunde_unterwegs` | Anzahl der Freunde, die gerade fahren oder bald losfahren; Attribute `travelling` (fahren gerade) und `soon` (starten bald) |

„Freunde“ sind alle Accounts, denen du folgst (Quelle `/dashboard`, inkl.
privater Profile, die dich zugelassen haben). Das Attribut `trips` enthält pro
Person die laufende Fahrt (nach Ankunft sortiert), danach Fahrten, die bald
starten (nach Abfahrt). Träwelling liefert fremde Check-ins erst ca. 20 min vor
Abfahrt im Dashboard – früher tauchen Freunde also nicht auf. Wer gerade fährt
und den Anschluss schon eingecheckt hat, bekommt ihn als `next`
(`line`, `origin`, `destination`, `departure`, `minutes_until`, …).

| Feld | Inhalt |
|---|---|
| `name`, `username`, `avatar`, `profile_url` | Anzeigename, Benutzername, Profilbild, Link zum Profil |
| `upcoming`, `minutes_until` | `true`, solange die Fahrt noch nicht begonnen hat; Minuten bis zur Abfahrt |
| `likes`, `liked`, `likable` | Anzahl Likes, ob du schon geliked hast, ob Liken erlaubt ist |
| `line`, `category` | Linie und Verkehrsmittel |
| `origin`, `destination` | Start- und Zielhaltestelle |
| `departure`, `arrival` | Abfahrt/Ankunft (Echtzeit, sonst Plan) |
| `departure_planned`, `arrival_planned`, `delay_arrival` | Planzeiten, Verspätung in Minuten |
| `progress`, `minutes_left` | Fortschritt und Restzeit (Stand letzte Abfrage) |
| `distance_km`, `body`, `url` | Distanz, Status-Text, Link zum Status |

**Statistik** (Profil-Punkte und Rangliste standardmäßig alle 60 min; Zeiträume, Favoriten und Verlauf nach eigenen Check-ins, beim Datumswechsel und sonst alle 6 h – die API cacht serverseitig 1–6 h)

| Entität endet auf | Inhalt | Quelle |
|---|---|---|
| `…_punkte_gesamt`, `…_distanz_gesamt`, `…_reisezeit_gesamt` | Punkte (Träwelling: letzte 7 Tage), km, Stunden | Profil |
| `…_check_ins_gesamt` | Check-ins seit Statistik-Start, längste/kürzeste Fahrten als Attribute | `/statistics/overview` |
| `…_aktive_reisetage`, `…_durchschnittsdistanz` | Reisetage, Ø km pro Fahrt | `/statistics/overview` |
| `…_check_ins_diese_woche`, `…_distanz_diese_woche` | ab Montag | `/statistics/overview` |
| `…_check_ins_diesen_monat`, `…_distanz_diesen_monat` | ab Monatsanfang | `/statistics/overview` |
| `…_check_ins_dieses_jahr`, `…_distanz_dieses_jahr` | ab Jahresanfang | `/statistics/overview` |
| `…_monatsverlauf` | Check-ins im laufenden Monat; Attribut `months` mit Check-ins und km der letzten 12 Monate | `/statistics/history` bzw. `/statistics/overview` je Monat (zwischengespeichert) |
| `…_langste_fahrt_dieses_jahr` | km, Details (Linie, Start, Ziel, Datum, Link) als Attribute | `/statistics/overview` |

**Favoriten & Rangliste**

| Entität endet auf | Zustand | Attribute |
|---|---|---|
| `…_lieblingsstation` | meistbesuchte Station dieses Jahr | `top` (Top 10 mit Anzahl) |
| `…_lieblingslinie` | meistgefahrene Linie | `top` (Anzahl, km) |
| `…_lieblingsstrecke` | häufigste Strecke „A → B“ | `top` (Anzahl, km) |
| `…_haufigstes_verkehrsmittel` | z. B. „Fernverkehr (ICE)“ | `categories`, `operators`, `purposes` |
| `…_rang_unter_freunden` | dein Platz (letzte 7 Tage) | `leaderboard` (Top 10), `my_points`, `participants` |

Intervalle und Statistik-Startdatum: Integration → **Konfigurieren**.

## 🎫 Check-in-Karte

Die Karte wird von der Integration automatisch mitgeliefert – keine Ressource,
kein HACS-Frontend-Repo nötig. Im Karten-Picker heißt sie **„Träwelling Check-in“**.

```yaml
type: custom:traewelling-checkin-card
# alles optional:
title: Einchecken
show_current_trip: true   # false = Karte ausblenden, solange du unterwegs bist
entity: binary_sensor.trawelling_deinname_unterwegs   # sonst automatisch
location_entity: device_tracker.mein_handy            # Standortquelle, sonst automatisch
```

**So funktioniert sie:**

1. **Nicht unterwegs** → Suchfeld, Button „Station in meiner Nähe“, dazu Heimatbahnhof und die 5 zuletzt genutzten Stationen
2. **Station gewählt** → Live-Abfahrten (aktualisieren sich jede Minute) mit Verspätung, Gleis(wechsel) und Ausfällen, Filter nach Verkehrsmittel, blättern mit „Früher/Später“
3. **Abfahrt gewählt** → alle folgenden Halte mit Ankunftszeiten
4. **Ausstieg gewählt** → Statustext, Fahrkarte, Sichtbarkeit und Reiseart, dann „Jetzt einchecken“
5. **Bald unterwegs** → steht eine eingecheckte Fahrt in der nächsten Stunde an, zeigt die Karte sie mit „Abfahrt in X min“
6. **Unterwegs** → die Karte zeigt deine laufende Fahrt mit Fortschrittsbalken, der nächsten Fahrt (allen eingecheckten Anschlüssen samt Umstiegszeit (grün/gelb/rot, ● = Echtzeit) und dem Button „Anschluss ab … einchecken“ – der öffnet direkt die Abfahrten am Ziel der letzten Fahrt ab deren Ankunftszeit

**Fahrkarte:** Die Karte listet deine Träwelling-Fahrkarten, die am Reisetag gültig sind, und schlägt die zuletzt genutzte vor – solange sie noch gültig ist. Abgelaufene Fahrkarten tauchen nicht auf. Hast du keine Fahrkarten angelegt, bleibt das Feld ausgeblendet.

Ein angefangener Check-in wird nie unterbrochen – auch nicht, wenn sich im Hintergrund der Fahrtstatus ändert oder Home Assistant die Karte neu aufbaut.

**„Station in meiner Nähe“:** Träwelling sucht serverseitig nur in einem kleinen Umkreis (laut Quellcode standardmäßig ~200 m). Findet es dort nichts, erweitert die Integration die Suche stufenweise auf ca. 400 m, 1 km und 2 km und zeigt die gefundenen Stationen mit Entfernung zur Auswahl. Das sind je nach Stufe bis zu 19 Anfragen, aber nur, wenn am Standort selbst nichts gefunden wurde. Liegt direkt eine Station in der Nähe, öffnen sich sofort ihre Abfahrten.

Im Browser wird der Browser-Standort genutzt. In der
Home-Assistant-App (oder wenn der Browser den Standort verweigert) nimmt die Karte
automatisch den Standort, den die App an Home Assistant meldet – über deine
`person`-Entität bzw. deren Device-Tracker. Voraussetzung: In der App unter
**Einstellungen → Companion App → Standort** ist die Standortfreigabe aktiv. Wie
alt der Standort ist, steht über den Abfahrten.

Sichtbarkeit und Reiseart merkt sich die Karte pro Gerät. Der Verkehrsmittel-Filter startet bei jeder Station auf „Alle“; liefert Träwelling mit einem Filter nichts (z. B. „Fern“ an einer Stadtbahn-Haltestelle), lädt die Karte automatisch alle Verkehrsmittel.

## 👥 Freunde-Karte

```yaml
type: custom:traewelling-friends-card
# alles optional:
entity: sensor.trawelling_deinname_freunde_unterwegs   # sonst automatisch
empty_text: Gerade ist niemand unterwegs.
```

Pro Freund: Profilbild und Name (→ Profil), Linie, Start und Ziel mit Zeiten, Verspätung und Gleis, Fortschrittsbalken und Restzeit – bei Fahrten, die bald starten, wie bei deinen eigenen „in 15 min“ und „Abfahrt in …“; ist der Anschluss schon eingecheckt, „Danach: …“ – Link zum Status und ein ❤️-Button mit Like-Zahl. Das Herz reagiert sofort; klappt das Liken nicht (z. B. Scope `write-likes` fehlt), springt es zurück und die Karte zeigt den Grund.
Der Token bleibt dabei in Home Assistant – die Karte spricht nur mit den
Services der Integration.

## 📈 Statistik-Karte

```yaml
type: custom:traewelling-stats-card
# alles optional:
title: Statistik
show_leaderboard: true
show_favorites: true
metric: checkins        # oder km – Startansicht des Diagramms
header: true            # false = ohne eigene Kopfzeile (wenn das Dashboard Überschriften hat)
show: [kpis, chart]     # nur bestimmte Bausteine, Standard: alle
```

Bausteine für `show`: `kpis`, `facts`, `chart`, `longest`, `favorites`
(oder einzeln `fav_stations`, `fav_lines`, `fav_routes`) und `leaderboard`.
So lässt sich die Statistik auf mehrere kleine Karten verteilen – siehe
Dashboard-Vorlage unten.

- **Kennzahlen:** Check-ins und km für Woche, Monat, Jahr und gesamt
- **Fakten:** Punkte, Stunden unterwegs, Reisetage, Ø km pro Fahrt
- **Balkendiagramm** der letzten 12 Monate, umschaltbar zwischen Check-ins und km; Balken antippen zeigt beide Werte
- **Längste Fahrt** des Jahres (antippen → Status)
- **Favoriten** des Jahres: Top-3-Stationen, -Linien und -Strecken
- **Freunde-Rangliste** der letzten 7 Tage (Top 5)

Die Monatswerte kommen aus `/statistics/history`. Liefert Träwelling das nicht,
holt die Integration jeden abgeschlossenen Monat **einmalig** über
`/statistics/overview` und speichert ihn dauerhaft in Home Assistant – danach wird
nur noch der laufende Monat abgefragt.

## 🛠️ Services

| Service | Rückgabe | Zweck |
|---|---|---|
| `traewelling.search_stations` | ✅ | `query` → Treffer · `latitude`/`longitude` → nächste Station · ohne Angaben → Heimatbahnhof + zuletzt genutzt |
| `traewelling.get_departures` | ✅ | `station_id`, optional `when`, `travel_type` |
| `traewelling.get_trip` | ✅ | `trip_id`, `line_name` → alle Halte |
| `traewelling.checkin` | optional | `trip_id`, `line_name`, `start_id`, `destination_id`, `departure`, `arrival`, optional `body`, `visibility`, `business`, `toot`, `ticket_id` |
| `traewelling.like` | optional | `status_id`, optional `like` (Standard `true`, `false` = Like zurücknehmen) |
| `traewelling.get_tickets` | ✅ | optional `date` → am Tag gültige Fahrkarten + `suggested` (zuletzt genutzte, falls gültig) |

Beispiel (Entwicklerwerkzeuge → Aktionen, „Antwort zurückgeben“):

```yaml
action: traewelling.search_stations
data:
  query: Hannover Hbf
```

## 🖥️ Dashboard

Aufgeteilt in viele kleine Karten, die sich im Sections-Layout von selbst
anordnen: **Meine Fahrt**, **Freunde unterwegs**, **Statistik** (Kennzahlen,
Fakten, längste Fahrt), **Monatsverlauf**, **Favoriten** und **Freunde-Rangliste**.
Die Karten finden die Träwelling-Entitäten automatisch.

Einfügen: Dashboard bearbeiten → **„+“** (neue Ansicht) → ⋮ →
**„In YAML bearbeiten“** → Inhalt ersetzen → Speichern.
`location_entity` auf den eigenen Handy-Tracker anpassen oder die Zeile löschen.

```yaml
title: Träwelling
path: traewelling
icon: mdi:train
type: sections
max_columns: 4
sections:
  - type: grid
    cards:
      - type: heading
        heading: Meine Fahrt
        icon: mdi:train
      - type: custom:traewelling-checkin-card
        location_entity: device_tracker.julianultra26
        grid_options:
          columns: full

  - type: grid
    cards:
      - type: heading
        heading: Freunde unterwegs
        icon: mdi:account-group
      - type: custom:traewelling-friends-card
        grid_options:
          columns: full

  - type: grid
    cards:
      - type: heading
        heading: Statistik
        icon: mdi:chart-box
        tap_action:
          action: url
          url_path: https://traewelling.de/statistics
      - type: custom:traewelling-stats-card
        header: false
        show: kpis
        grid_options:
          columns: full
      - type: custom:traewelling-stats-card
        header: false
        show: facts
        grid_options:
          columns: full
      - type: custom:traewelling-stats-card
        header: false
        show: longest
        grid_options:
          columns: full

  - type: grid
    cards:
      - type: heading
        heading: Monatsverlauf
        icon: mdi:chart-bar
      - type: custom:traewelling-stats-card
        header: false
        show: chart
        grid_options:
          columns: full

  - type: grid
    cards:
      - type: heading
        heading: Favoriten
        icon: mdi:heart
      - type: custom:traewelling-stats-card
        header: false
        show: fav_stations
        grid_options:
          columns: 6
      - type: custom:traewelling-stats-card
        header: false
        show: fav_lines
        grid_options:
          columns: 6
      - type: custom:traewelling-stats-card
        header: false
        show: fav_routes
        grid_options:
          columns: full

  - type: grid
    cards:
      - type: heading
        heading: Freunde-Rangliste · 7 Tage
        icon: mdi:podium
      - type: custom:traewelling-stats-card
        header: false
        show: leaderboard
        grid_options:
          columns: full
```

## 📱 Sperrbildschirm & Handy-Widgets (nur mit Home Assistant)

**Live-Aktivität (iPhone) / Live Update (Android):** Die laufende Fahrt auf dem
Sperrbildschirm und in der Dynamic Island – Linie und Ziel, Fortschrittsbalken,
Live-Countdown bis zur Ankunft, Farbe je Verkehrsmittel. Beim Anschluss wechselt
sie automatisch, nach der Ankunft verschwindet sie. Braucht Home Assistant 2026.7+,
die Companion-App und iOS 17.2+ bzw. Android 16+.

[![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fv8b-kg%2Ftrwl_ha_integr%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ftraewelling%2Flive_activity.yaml)

Blueprint importieren → **Automatisierung erstellen** → „Unterwegs“-Sensor und Handy
wählen → speichern. Optionen: Countdown oder Strecke als Text, Dashboard-Pfad beim
Antippen. Updates kommen bei Abfahrt/Ankunft, Verspätungsänderung und sonst alle 10 min
(iOS drosselt häufigere). Auf dem iPhone muss unter *Einstellungen → Home Assistant*
„Live-Aktivitäten“ an sein.

**Android-Homebildschirm:** Widget **Template** der Companion-App mit diesem Template
(findet die Entitäten selbst):

```jinja
{%- set b = integration_entities('traewelling') | select('search', '^binary_sensor\\.') | list | first | default('') -%}
{%- set u = integration_entities('traewelling') | select('search', '_nachste_fahrt$') | list | first | default('') -%}
{%- if b and is_state(b, 'on') -%}
{%- set dp = as_timestamp(state_attr(b, 'departure_planned'), 0) -%}
{%- set dr = as_timestamp(state_attr(b, 'departure_real'), dp) -%}
{%- set ap = as_timestamp(state_attr(b, 'arrival_planned'), 0) -%}
{%- set ar = as_timestamp(state_attr(b, 'arrival_real'), ap) -%}
{%- set p = ([[(now().timestamp() - dr) / ([ar - dr, 60] | max), 0] | max, 1] | min * 100) | round(0) | int -%}
{%- set dd = ((dr - dp) / 60) | round(0) | int -%}
{%- set da = ((ar - ap) / 60) | round(0) | int -%}
{%- set left = ([ar - now().timestamp(), 0] | max / 60) | round(0) | int -%}
<b><font color='#ec0016'>{{ state_attr(b, 'line') }}</font></b>
{%- if da > 0 %} <font color='#db4437'><b>+{{ da }} min</b></font>{% elif state_attr(b, 'arrival_real') %} <font color='#43a047'>pünktlich</font>{% endif %}<br>
<big><b>{{ dp | timestamp_custom('%H:%M') }}</b></big>{% if dd > 0 %} <font color='#db4437'>+{{ dd }}</font>{% endif %} {{ state_attr(b, 'origin') }}
{%- if state_attr(b, 'origin_platform') %} <small>Gl. {{ state_attr(b, 'origin_platform') }}</small>{% endif %}<br>
<big><b>{{ ap | timestamp_custom('%H:%M') }}</b></big>{% if da > 0 %} <font color='#db4437'>+{{ da }}</font>{% endif %} {{ state_attr(b, 'destination') }}
{%- if state_attr(b, 'destination_platform') %} <small>Gl. {{ state_attr(b, 'destination_platform') }}</small>{% endif %}<br>
<font color='#ec0016'>{{ '━' * (p // 5) }}</font>●<font color='#777777'>{{ '━' * (20 - p // 5) }}</font><br>
<b>{{ p }} %</b> · noch {{ left }} min · {{ state_attr(b, 'distance_km') }} km · {{ state_attr(b, 'points') }} Punkte
{%- elif u and states(u) not in ['unknown', 'unavailable'] -%}
{%- set d = as_timestamp(state_attr(u, 'departure_real') or state_attr(u, 'departure_planned'), 0) -%}
<b><font color='#03a9f4'>Bald: {{ state_attr(u, 'line') }}</font></b> · in {{ ([d - now().timestamp(), 0] | max / 60) | round(0) | int }} min<br>
<big><b>{{ as_timestamp(state_attr(u, 'departure_planned'), d) | timestamp_custom('%H:%M') }}</b></big> {{ state_attr(u, 'origin') }}
{%- if state_attr(u, 'origin_platform') %} <small>Gl. {{ state_attr(u, 'origin_platform') }}</small>{% endif %}<br>
<big><b>{{ as_timestamp(state_attr(u, 'arrival_planned'), 0) | timestamp_custom('%H:%M') }}</b></big> {{ state_attr(u, 'destination') }}
{%- else -%}
🚆 Gerade keine Fahrt
{%- endif -%}
```

**iPhone ohne Live-Aktivität:** In der HA-App gibt es für den Sperrbildschirm das
Widget *Gauge* (rund, z. B. Fortschritt in %) und *Details* (einzeilig), jeweils mit
Templates.

## 🤖 Automatisierungs-Beispiele

```yaml
automation:
  - alias: "Benachrichtigung, wenn ein Freund losfährt"
    triggers:
      - trigger: state
        entity_id: sensor.traewelling_freunde_unterwegs
        attribute: travelling
    conditions:
      - condition: template
        value_template: >-
          {{ trigger.to_state.attributes.travelling | int(0) > trigger.from_state.attributes.travelling | int(0) }}
    actions:
      - action: notify.notify
        data:
          message: >-
            {% set t = state_attr('sensor.traewelling_freunde_unterwegs', 'trips') | rejectattr('upcoming') | sort(attribute='departure') | last %}
            {{ t.name }} fährt gerade {{ t.line }} von {{ t.origin }} nach {{ t.destination }}.

  - alias: "Licht an, wenn Zug bald ankommt"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.traewelling_restfahrzeit
        below: 10
    conditions:
      - condition: state
        entity_id: binary_sensor.traewelling_unterwegs
        state: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.flur

  - alias: "Warnung, wenn der Anschluss wackelt"
    triggers:
      - trigger: state
        entity_id: sensor.traewelling_nachster_umstieg
        attribute: rating
        to: [risk, missed, cancelled]
    actions:
      - action: notify.notify
        data:
          message: >-
            Umstieg in {{ state_attr('sensor.traewelling_nachster_umstieg', 'station') }}:
            nur noch {{ states('sensor.traewelling_nachster_umstieg') }} min bis
            {{ state_attr('sensor.traewelling_nachster_umstieg', 'to_line') }}.
```

Entity-IDs an deine Installation anpassen.

## 🔌 Verwendete Endpunkte

| Endpunkt | Scope |
|---|---|
| `GET /api/v1/auth/user` | – |
| `GET /api/v1/user/statuses/active` (404 = keine Fahrt) | `read-statuses` |
| `GET /api/v1/dashboard` | `read-statuses` |
| `GET /api/v1/dashboard/future` (bis 3 Seiten) | `read-statuses` |
| `GET /api/v1/status/{id}` (nur Anschlüsse <20 min, die im Dashboard fehlen) | `read-statuses` |
| `GET /api/v1/statistics/overview`, `/statistics/history`, `/statistics/favorites`, `/statistics` | `read-statistics` |
| `GET /api/v1/leaderboard/friends` | `read-statistics` |
| `GET /api/v1/trains/station/autocomplete/{query}`, `/nearby`, `/history` | `write-statuses` |
| `GET /api/v1/station/{id}/departures` (auch für Echtzeit verspäteter Anschlüsse) | `write-statuses` |
| `GET /api/v1/trains/trip` | `write-statuses` |
| `POST /api/v1/trains/checkin` | `write-statuses` |
| `GET /api/v1/tickets?validOn=` | – |
| `PUT /api/v1/statuses/{id}/tickets` | `write-statuses` |
| `POST`/`DELETE /api/v1/status/{id}/like` | `write-likes` |

## 🤝 Fair Use

Träwelling erlaubt maximal 500 Anfragen pro 5 Minuten. Die Integration braucht im
Normalbetrieb etwa **7 pro 5 Minuten** (vorher ~16), während einer Fahrt etwa 12:

| Was | Wie oft |
|---|---|
| `/dashboard` (Freunde + eigene Fahrten) | jeden Poll; Seite 2 nur, wenn Seite 1 weniger als 24 h zurückreicht |
| `/user/statuses/active` | jeden Poll, solange eine eigene Fahrt läuft oder in 5 min startet und direkt nach einem Check-in – sonst alle 5 min |
| `/dashboard/future` | alle 5 min |
| `/status/{id}`, Abfahrtstafel | nur für Anschlüsse, die es brauchen (max. 3 bzw. 2 pro Poll) |
| Profil + Rangliste | alle 60 min |
| Zeiträume, Favoriten, Verkehrsmittel (6 Anfragen) | nach eigenen Check-ins, beim Datumswechsel, sonst alle 6 h |
| Monats-/Wochenverlauf | alle 6 h (Träwelling cacht 6 h) |

Statistik-Anfragen laufen im Hintergrund nacheinander mit 3 s Abstand. Der
Monatsverlauf wird einmalig nachgeladen (bis zu 11 Anfragen, ebenfalls mit Abstand)
und danach gespeichert. Freunde- und Statistik-Karte lesen nur die Sensoren und
stellen keine eigenen Anfragen; die Check-in-Karte nur, während du sie bedienst –
Live-Abfahrten nur, solange sie sichtbar sind. Kurz zwischengespeichert werden
Abfahrten (20 s, z. B. Handy und iPad gleichzeitig), Fahrtverläufe (30 s),
zuletzt genutzte Stationen und Fahrkarten (10 min, nach einem Check-in sofort neu),
Stationssuche (6 h) und „In meiner Nähe“ (24 h). Antwortet Träwelling mit HTTP 429,
pausiert die Integration alle Anfragen für die Dauer aus `Retry-After` (ohne Angabe: 60 s).

Alle Anfragen tragen den User-Agent
`trwl-ha-integration/<version> (Home Assistant; +https://github.com/v8b-kg/trwl_ha_integr; @<dein-username>)`.
Der Träwelling-Account steht auf Wunsch der Träwelling-Betreiber mit drin, damit sie Anfragen einem Nutzer zuordnen können.

## 🩺 Fehlersuche

- **Check-in-Karte meldet „Zugriff abgelehnt“** → Token ohne `write-statuses`; neuen Token anlegen und über *Neu konfigurieren* eintragen.
- **Neue Funktionen fehlen nur in der Handy-App** (z. B. der ❤️-Button) → die App hält eine alte Version der Karte im Zwischenspeicher: in der App unter Einstellungen → Companion App → Fehlerbehebung/Debugging „Frontend-Cache zurücksetzen“ (oder App komplett schließen und neu öffnen).
- **Karte „Custom element doesn't exist“** → Home Assistant nach dem Update neu starten und die Seite neu laden (Browser-Cache).
- **Statistik-Werte fehlen** → der Token braucht `read-statistics`; Träwelling cacht die Werte bis zu 6 h.
- **Debug-Logging:**

```yaml
logger:
  logs:
    custom_components.traewelling: debug
```

## 📄 Lizenz

Copyright © 2026 [V8B KG](https://v8b.eco)

Diese Integration ist freie Software unter der
[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0) – derselben Lizenz wie
Träwelling. Du darfst sie nutzen, verändern und weitergeben, auch kommerziell;
wer sie verändert weitergibt oder als Dienst anbietet, muss den Quellcode ebenfalls
unter der AGPL-3.0 veröffentlichen. Ohne Gewähr.

**Beiträge:** Mit einem Pull Request erklärst du dich einverstanden, dass die V8B KG
deinen Beitrag unter der AGPL-3.0 und künftig auch unter anderen Lizenzen
veröffentlichen darf.

**Träwelling** ([traewelling.de](https://traewelling.de)) ist ein Projekt des
[Träwelling e.V.](https://traewelling.org) und steht selbst unter der AGPL-3.0
([Quellcode](https://github.com/Traewelling/traewelling)). Diese Integration ist ein
eigenständiges, inoffizielles Projekt der V8B KG und nicht mit dem Träwelling e.V.
verbunden. Wenn du Träwelling unterstützen möchtest:
[Spenden an den Träwelling e.V.](https://traewelling.org/support-us) 💚

## 📝 Changelog

- **1.9.5** – 🔄 Update-Hinweise in Home Assistant: jede Version wird automatisch als GitHub-Release veröffentlicht (mit Changelog), HACS meldet sie unter Einstellungen → Updates · HACS bietet damit fertige Versionen an statt halb hochgeladener Zwischenstände
- **1.9.4** – 💚 Hinweis auf den Träwelling e.V. als Betreiber von Träwelling und Spendenaufruf (oben in der README und im Lizenz-Abschnitt) · 🧹 Umzugs-Hinweis entfernt
- **1.9.3** – 📄 Lizenz: AGPL-3.0, Copyright V8B KG (wie Träwelling) · Hinweis zu Beiträgen und „inoffiziell, nicht verbunden mit Träwelling“
- **1.9.2** – 🏢 Repository ist zu [V8B KG](https://v8b.eco) umgezogen: neue Adresse github.com/v8b-kg/trwl_ha_integr in Doku- und Issue-Links, User-Agent und Blueprint (alte Links leiten automatisch weiter)
- **1.9.1** – 📱 Blueprint „laufende Fahrt als Live-Aktivität“ für den Sperrbildschirm (iPhone + Dynamic Island, Android Live Update) mit Fortschritt, Countdown und automatischem Wechsel beim Anschluss · Template für das Android-Homebildschirm-Widget
- **1.9.0** – 🧹 Aufgeräumt und sparsamer: gut die Hälfte weniger Anfragen im Normalbetrieb bei gleichem Funktionsumfang · aktive Fahrt nur abfragen, wenn eine eigene Fahrt läuft oder bald startet · Dashboard-Seite 2 nur bei Bedarf · Statistik nach „Lebensdauer“ gruppiert (Zeiträume nur nach eigenen Check-ins/Datumswechsel) · 💾 Zwischenspeicher für Abfahrten, Fahrtverläufe, Stationssuche, „In meiner Nähe“, zuletzt genutzte Stationen und Fahrkarten; gleiche parallele Anfragen werden zusammengefasst · 📵 Live-Abfahrten pausieren, solange die Karte nicht sichtbar ist · 🗄️ Große Listen-Attribute (Anschlüsse, Freunde, Ranglisten …) werden nicht mehr in die Datenbank geschrieben · 🐛 „Punkte gesamt“ (= Punkte der letzten 7 Tage) nicht mehr als stetig steigend markiert · 🔌 HTTP-Verbindungen werden immer sauber freigegeben · 🏗️ Code in Module aufgeteilt (Anschlüsse, Statistik, Cache), `runtime_data` statt `hass.data`, Beschreibungen in den Optionen
- **1.8.2** – 👥 Freunde, die bald losfahren, erscheinen schon in der Freunde-Karte – mit „in 15 min“ und „Abfahrt in …“ wie bei deinen eigenen Fahrten · „Danach: …“, wenn ein Freund den Anschluss schon eingecheckt hat · Sensor „Freunde unterwegs“ mit `travelling` und `soon` · 🏷️ Versionsnummer im README-Titel
- **1.8.1** – ⚠️ Warnungen bei knappen, gefährdeten, verpassten und „unlogischen“ Anschlüssen (Banner + Hinweis am Umstieg), die folgenden Fahrten bleiben sichtbar · ❔ Verspätete Ankunft + Anschluss ohne Echtzeit = „unklar“ statt „verpasst“ · 📡 Echtzeit für solche Anschlüsse von der Live-Abfahrtstafel · 🔮 Ankunft wird aus der Abfahrtsverspätung geschätzt · 🔗 Große Verspätungen lassen die Kette nicht mehr abreißen
- **1.8.0** – 🔗 Mehrere Anschlüsse: die ganze eingecheckte Reisekette wird angezeigt (Anschluss → Anschluss → …), nicht mehr nur der nächste · ⏱️ Live-Umstiegszeiten zwischen den Fahrten aus Plan- und Echtzeitdaten mit Einschätzung (ok / knapp / gefährdet / verpasst / fällt aus), Gleiswechsel und Fußweg bei Stationswechsel · 🆕 Sensor „Nächster Umstieg“ · 🔁 „Anschluss ab … einchecken“ öffnet direkt die Abfahrten am Ziel der letzten Fahrt ab Ankunftszeit · 🧹 Gelöschte Check-ins verschwinden automatisch · 📄 `/dashboard/future` wird geblättert (die nächsten Fahrten stehen dort hinten)
- **1.7.2** – 🪪 User-Agent enthält jetzt den Träwelling-Account (@username), auf Wunsch der Träwelling-Betreiber
- **1.7.1** – 🐛 Abfahrten laden wieder an Haltestellen ohne Fernverkehr: Verkehrsmittel-Filter wird nicht mehr gespeichert und fällt bei Fehlern automatisch auf „Alle“ zurück · 💬 Lesbare Fehlermeldungen von Träwelling (Umlaute, ohne JSON)
- **1.7.0** – ❤️ Freunden direkt aus der Freunde-Karte Likes geben (Scope `write-likes`) · 🛠️ Service `traewelling.like`
- **1.6.2** – 🧩 Statistik-Karte lässt sich in einzelne Bausteine aufteilen (`show`, `header`) · 🖥️ Dashboard-Vorlage mit vielen kleinen Karten statt einer langen
- **1.6.1** – 📍 „Station in meiner Nähe“ erweitert den Suchradius stufenweise (400 m → 1 km → 2 km), wenn direkt am Standort nichts gefunden wird, und bietet die Treffer mit Entfernung zur Auswahl an
- **1.6.0** – 🎨 Neues Design für eigene, bevorstehende und Freundes-Fahrten (Linienfarbe, Zeitleiste, Fortschritt mit Verkehrsmittel-Symbol, Verspätungs-Badges, Profilbilder) · 📈 Neue Statistik-Karte mit Monatsdiagramm, Kennzahlen, Favoriten und Rangliste · ⏱️ Statistik standardmäßig nur noch stündlich · 📡 Sensor „Monatsverlauf“ · 🚉 Check-in zeigt nur noch die 5 zuletzt genutzten Stationen
- **1.5.0** – 🕐 Eingecheckte Fahrten der nächsten Stunde erscheinen als „Bald unterwegs“, während einer Fahrt als „Danach: …“ · neuer Sensor „Nächste Fahrt“ · 🧹 Favoriten-Bereich aus der Dashboard-Vorlage entfernt
- **1.4.0** – 🎫 Fahrkarte beim Check-in (Vorschlag: zuletzt genutzte, solange gültig) · 👥 Freunde-Karte im Design der eigenen Fahrt · 🔁 „Anschluss einchecken“ während einer Fahrt · 🐛 Check-in wird nicht mehr durch Hintergrund-Aktualisierungen unterbrochen · 🤝 Fair Use: Statistik-Anfragen laufen im Hintergrund mit 3 s Abstand statt als Stoß · ⏳ Bei HTTP 429 wird `Retry-After` respektiert – bis dahin gehen keine Anfragen an Träwelling raus · 🪪 Eindeutiger User-Agent mit Version und Repo-Link
- **1.3.2** – 📍 „Station in meiner Nähe“ funktioniert in der HA-App: Standort kommt aus Home Assistant (person/device_tracker), wenn der Browser-Standort nicht verfügbar ist
- **1.3.1** – 🔧 Check-in-Karte wird als Dashboard-Ressource registriert und lädt nach Neustarts zuverlässig
- **1.3.0** – 🐛 Distanz für Woche/Monat/Jahr repariert (richtige API-Felder) · 📊 Neu: Woche, Ø-Distanz, längste Fahrt des Jahres · ❤️ Favoriten (Stationen, Linien, Strecken, Verkehrsmittel) · 🏆 Freunde-Rangliste · 🖥️ erweiterte Dashboard-Karten
- **1.2.0** – 🎫 Check-in-Karte mit Stationssuche, Standort, Live-Abfahrten und Ausstiegswahl · 🛠️ Services `search_stations`, `get_departures`, `get_trip`, `checkin` · 👤 Freunde verlinken auf ihr Profil · 🔑 Token über „Neu konfigurieren“ austauschbar
- **1.1.1** – 🐛 Monat/Jahr-Statistik über `/statistics/overview`
- **1.1.0** – 👥 Sensor „Freunde unterwegs“, Dashboard-Vorlage
- **1.0.0** – 🎉 Erste Version: aktive Fahrt und Statistiken

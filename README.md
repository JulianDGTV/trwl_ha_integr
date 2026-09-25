# 🚆 Träwelling für Home Assistant

Custom Integration für [traewelling.de](https://traewelling.de): deine laufende
Fahrt, die Fahrten deiner Freunde, deine Reisestatistiken – und Check-in direkt
aus dem Dashboard.

## ✨ Features

- **Meine Fahrt** – Linie, Start/Ziel, Zeiten, Verspätung, Gleis, Fortschritt, Restzeit
- **Nächste Fahrt & Anschlüsse** – eingecheckte Fahrten, die in der nächsten Stunde starten, erscheinen als „Bald unterwegs“; dahinter die ganze eingecheckte Reisekette (Anschluss → Anschluss → …) mit Live-Umstiegszeiten aus Plan- und Echtzeitdaten
- **Freunde unterwegs** – alle gerade laufenden Fahrten der Accounts, denen du folgst, mit Link zum Profil
- **Check-in-Karte** – Station suchen (oder per Standort), Live-Abfahrten mit Verspätung und Gleis, Ausstieg wählen, Fahrkarte (z. B. BahnCard 100) hinterlegen, einchecken – auch als Anschluss während einer laufenden Fahrt
- **Freunde-Karte** – laufende Fahrten deiner Freunde im selben Design wie die eigene Fahrt, Name antippen → Profil, ❤️ Like direkt aus der Karte
- **Statistik-Karte** – Kennzahlen für Woche, Monat, Jahr und gesamt, Balkendiagramm der letzten 12 Monate (Check-ins/km), längste Fahrt, Favoriten, Freunde-Rangliste
- **Favoriten** – Lieblingsstationen, -linien und -strecken des laufenden Jahres (in der Statistik-Karte)
- **Freunde-Rangliste** – dein Rang unter Freunden (Punkte der letzten 7 Tage)
- **Services** für Stationssuche, Abfahrten, Fahrtverlauf und Check-in – nutzbar in eigenen Automationen

## 📦 Installation

**HACS (empfohlen):** HACS → ⋮ → *Benutzerdefinierte Repositories* →
`https://github.com/JulianDGTV/trwl_ha_integr`, Kategorie *Integration* →
*Träwelling* herunterladen → Home Assistant neu starten.

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

**Aktive Fahrt** (Abfrage standardmäßig alle 60 s)

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
| `…_nachste_fahrt` | Abfahrtszeit deiner nächsten eingecheckten Fahrt (während einer Fahrt: der erste Anschluss, sonst innerhalb 1 h); Details wie bei der aktiven Fahrt als Attribute, dazu `minutes_until`, `after_current`, `chain` (alle Anschlüsse inkl. `transfer`), `transfers`, `final_destination`, `final_arrival` |
| `…_nachster_umstieg` | Minuten für den nächsten Umstieg nach Echtzeit; Attribute `minutes_planned`, `rating` (`ok`, `tight`, `risk`, `missed`, `cancelled`), `station`, `arrival_platform`, `departure_platform`, `to_station`/`walk_m` (bei Stationswechsel), `from_line`, `to_line` |

**Reisekette:** Nach der laufenden Fahrt (bzw. der nächsten Fahrt) sucht die Integration den frühesten eigenen Check-in, der nach der planmäßigen Ankunft startet (max. 3 h später) – und von dort den nächsten usw. Umstiegszeiten werden aus Ankunft und Abfahrt berechnet (manuell > Echtzeit > Plan). Bei verschiedenen Stationen (z. B. Hbf → ZOB) wird die Luftlinie als Fußweg eingerechnet.

Quellen: eigene Status im Dashboard (bis ~20 min voraus, jede Minute mit Echtzeit), `/dashboard/future` (alle 5 min, >20 min voraus – Träwelling holt Echtzeit ohnehin erst ab 20 min vor Abfahrt) und jeder Check-in über die Karte, der sofort übernommen wird. Fehlt eine Fahrt kurz vor Abfahrt im Dashboard (z. B. vor über 7 Tagen eingecheckt), wird sie einzeln über `/status/{id}` nachgeladen. Gelöschte Check-ins verschwinden automatisch. Solange eine andere Fahrt noch läuft, bleibt diese die Hauptanzeige.

**Freunde unterwegs** (zusammen mit der aktiven Fahrt abgefragt)

| Entität endet auf | Beschreibung |
|---|---|
| `…_freunde_unterwegs` | Anzahl der Freunde, die gerade fahren |

„Freunde“ sind alle Accounts, denen du folgst (Quelle `/dashboard`, inkl.
privater Profile, die dich zugelassen haben). Das Attribut `trips` enthält pro
Person die laufende Fahrt, nach Ankunft sortiert:

| Feld | Inhalt |
|---|---|
| `name`, `username`, `avatar`, `profile_url` | Anzeigename, Benutzername, Profilbild, Link zum Profil |
| `likes`, `liked`, `likable` | Anzahl Likes, ob du schon geliked hast, ob Liken erlaubt ist |
| `line`, `category` | Linie und Verkehrsmittel |
| `origin`, `destination` | Start- und Zielhaltestelle |
| `departure`, `arrival` | Abfahrt/Ankunft (Echtzeit, sonst Plan) |
| `departure_planned`, `arrival_planned`, `delay_arrival` | Planzeiten, Verspätung in Minuten |
| `progress`, `minutes_left` | Fortschritt und Restzeit (Stand letzte Abfrage) |
| `distance_km`, `body`, `url` | Distanz, Status-Text, Link zum Status |

**Statistik** (standardmäßig alle 60 min – die API cacht serverseitig 1–6 h)

| Entität endet auf | Inhalt | Quelle |
|---|---|---|
| `…_punkte_gesamt`, `…_distanz_gesamt`, `…_reisezeit_gesamt` | Punkte, km, Stunden | Profil |
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

Pro Freund: Profilbild und Name (→ Profil), Linie, Start und Ziel mit Zeiten, Verspätung und Gleis, Fortschrittsbalken und Restzeit, Link zum Status und ein ❤️-Button mit Like-Zahl. Das Herz reagiert sofort; klappt das Liken nicht (z. B. Scope `write-likes` fehlt), springt es zurück und die Karte zeigt den Grund.
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

## 🤖 Automatisierungs-Beispiele

```yaml
automation:
  - alias: "Benachrichtigung, wenn ein Freund losfährt"
    triggers:
      - trigger: state
        entity_id: sensor.traewelling_freunde_unterwegs
    conditions:
      - condition: template
        value_template: >-
          {{ trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}
    actions:
      - action: notify.notify
        data:
          message: >-
            {% set t = state_attr('sensor.traewelling_freunde_unterwegs', 'trips') | sort(attribute='departure') | last %}
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
| `GET /api/v1/station/{id}/departures` | `write-statuses` |
| `GET /api/v1/trains/trip` | `write-statuses` |
| `POST /api/v1/trains/checkin` | `write-statuses` |
| `GET /api/v1/tickets?validOn=` | – |
| `PUT /api/v1/statuses/{id}/tickets` | `write-statuses` |
| `POST`/`DELETE /api/v1/status/{id}/like` | `write-likes` |

## 🤝 Fair Use

Träwelling erlaubt maximal 500 Anfragen pro 5 Minuten. Die Integration braucht im
Normalbetrieb etwa 13–20: aktive Fahrt und Freunde jeden Poll (kurz vor einem Anschluss ggf. 1–3 Einzelabfragen), geplante Fahrten
alle 5 Minuten, die Statistik alle 60 Minuten nacheinander mit 3 s Abstand. Der
Monatsverlauf wird einmalig nachgeladen (bis zu 11 Anfragen, ebenfalls mit Abstand)
und danach gespeichert. Freunde- und Statistik-Karte lesen nur die Sensoren und
stellen keine eigenen Anfragen; die Check-in-Karte nur, während du sie bedienst. Antwortet Träwelling mit HTTP 429, pausiert die
Integration alle Anfragen für die Dauer aus `Retry-After` (ohne Angabe: 60 s).

Alle Anfragen tragen den User-Agent
`trwl-ha-integration/<version> (Home Assistant; +https://github.com/JulianDGTV/trwl_ha_integr; @<dein-username>)`.
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

## 📝 Changelog

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

# Panasonic Cascade / Smart Edge für Home Assistant

Experimentelle Custom Integration für die lokale FIN-/Haystack-Schnittstelle der Panasonic Cascade Control Oberfläche (`panCascadeControlExt`). Version 0.3.0 bereinigt die Anzeigenamen, ergänzt einen eigenen Zone-1-Schalter und einen Dashboard-Assistenten. Anmeldung mit Benutzername/Passwort und Projektauswahl sind seit 0.2.0 enthalten. Schreibzugriffe sind noch nicht an einer realen Anlage geprüft.

Repository: [rommelfs/home-assistant-panasonic-cascade](https://github.com/rommelfs/home-assistant-panasonic-cascade).

## Installation zum lokalen Testen

1. Den Ordner `custom_components/panasonic_cascade` aus diesem Paket nach `/config/custom_components/panasonic_cascade` auf dem Home-Assistant-System kopieren.
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Panasonic Cascade / Smart Edge** öffnen.
4. HTTPS-Adresse des Controllers, **Benutzername und Passwort** eingeben. Eine vollständige URL zur Anlagenübersicht wird ebenfalls akzeptiert. Für Konten ohne Passwort darf das Passwortfeld leer bleiben.
5. Bei einem selbstsignierten Zertifikat kann **HTTPS-Zertifikat prüfen** ausgeschaltet werden. Die Verbindung bleibt verschlüsselt, aber die Serveridentität wird dann nicht geprüft. Es ist kein individueller Fingerprint fest eingebaut.
6. Ein Projekt aus der automatisch geladenen **Projektauswahl** auswählen, anschließend die Anlage in diesem Projekt auswählen.
7. Für weitere Projekte die Integration erneut hinzufügen. Einträge und Entitäten verschiedener Projekte sind voneinander getrennt; dieselbe Anlage wird nicht doppelt eingerichtet.

Die Anmeldung folgt dem vom Server angebotenen FIN-Verfahren (SCRAM, älteres HMAC oder vom Server angefordertes Plaintext über HTTPS). Cookies und `SkyArc-Attest-Key` werden automatisch bezogen und nur im Arbeitsspeicher gehalten. Nach einer ausdrücklich abgelaufenen Sitzung erfolgt genau eine erneute Anmeldung und Wiederholung der Anfrage. Falsche Zugangsdaten oder fehlende Rechte lösen eine Aufforderung zur erneuten Anmeldung aus. Passwortberechnungen blockieren nicht die Home-Assistant-Ereignisschleife.

Der Home-Assistant-Rechner muss die Controller-Adresse selbst erreichen können. Die Beispieladresse `172.17.0.1` ist nicht auf jedem Rechner dieselbe Anlage und muss gegebenenfalls durch die LAN-Adresse ersetzt werden.

## Vorhandene Einträge aus Version 0.1.0

Bestehende cookiebasierte Einträge bleiben nutzbar. Zur Umstellung auf Benutzername/Passwort im Menü des vorhandenen Integrationseintrags **Neu konfigurieren** wählen. Nach Ablauf einer Sitzung ist auch **Erneut authentifizieren** möglich. Projekt, Anlage und Entitäts-IDs bleiben dabei erhalten. Alternativ kann ein Eintrag neu eingerichtet werden; ein noch vorhandener Eintrag für dieselbe Anlage muss dann zuvor entfernt werden.

Benutzername und Passwort werden in der Home-Assistant-Konfiguration gespeichert. Die automatisch ausgestellten Sitzungscookies und Attestierungsschlüssel werden nicht in die Konfiguration geschrieben. Zugangsdaten und Home-Assistant-Backups entsprechend schützen und nicht in GitHub oder diesen Chat kopieren.

## Aktualisierung auf 0.3.0: Namen, Zone 1 und Dashboard

In HACS Version **0.3.0** herunterladen (gegebenenfalls Vorabversionen anzeigen) und Home Assistant neu starten. Anzeigenamen enthalten jetzt keine senkrechten Striche mehr. Die eindeutigen Entitäts- und Gerätekennungen bleiben erhalten; bereits verwendete Entitäts-IDs und selbst vergebene Namen ändern sich nicht.

### Zone 1 schalten

Unter **Einstellungen → Geräte & Dienste → Panasonic Cascade / Smart Edge → Konfigurieren** die Option **Steuerungen aktivieren** einschalten und speichern. Danach erscheint **Zone 1 – Ein/Aus**, sofern der Regler den gemeinsamen Zone-1/2-Punkt als beschreibbar bereitstellt. Der Schalter zeigt den aktuellen wirksamen Zustand von Zone 1.

Vor jedem Schalten liest die Integration den gemeinsamen Wert erneut aus der gewählten Anlage. Sie verändert nur den ersten Teil von beispielsweise `On/On` zu `Off/On`; Zone 2 wird aus dieser aktuellen Abfrage übernommen. Eigene Schreibvorgänge werden nacheinander ausgeführt. Wenn die aktuellen Werte unbekannt sind oder vom Standardwert abweichen, wird kein Schreibbefehl gesendet. Dann zunächst ein Zeitprogramm oder eine Übersteuerung in der Regleroberfläche prüfen. Der Schalter verwendet wie die anderen Bedienelemente `pointSetDef`. Eine zeitgleiche Änderung durch einen anderen Bediener zwischen Lesen und Schreiben kann das Protokoll nicht atomar ausschließen.

### Dashboard mit aktuellen Werten

1. **Einstellungen → Dashboards → Dashboard hinzufügen** öffnen und ein **leeres Dashboard** anlegen. Als Titel beispielsweise **Panasonic Cascade** und als URL **panasonic-cascade** wählen. In der Seitenleiste anzeigen lassen.
2. **Entwicklerwerkzeuge → Aktionen** öffnen und **Panasonic Cascade: Cascade-Dashboard befüllen** auswählen (Aktion `panasonic_cascade.populate_dashboard`).
3. Als **Dashboard-Adresse** `panasonic-cascade` eingeben und die Aktion ausführen. Das ist der URL-Pfad ohne Schrägstriche, nicht der Titel. Bei mehreren Installationen kann optional ein einzelner Integrationseintrag ausgewählt werden.
4. Das neue Dashboard in der Seitenleiste öffnen. Es enthält **Übersicht** mit Schaltern, Sollwerten, Leistung, aktuellen Temperaturen und Betriebszuständen sowie **Alle Werte**, nach Gerät gruppiert. Verläufe füllen sich mit den von Home Assistant aufgezeichneten Messwerten; es wird keine frühere Controller-Historie importiert.

Alternativ die Aktion in der YAML-Ansicht ausführen:

```yaml
action: panasonic_cascade.populate_dashboard
data:
  url_path: panasonic-cascade
```

Es werden die tatsächlichen Entitäts-IDs aus Home Assistant verwendet, auch wenn sie umbenannt wurden oder einen Zahlensuffix tragen. Die Aktion benötigt Administratorrechte und befüllt nur ein bereits vorhandenes Dashboard. Vorhandene Karten werden ohne ausdrücklich aktivierte Option **Vorhandene Dashboard-Konfiguration ersetzen** nicht ersetzt. Wurden Steuerungen erst später aktiviert oder neue Geräte erkannt, dieselbe Aktion erneut mit dieser Option ausführen. Individuelle Änderungen an diesem Dashboard werden dabei ersetzt; andere Dashboards bleiben erhalten.

## Daten und Bedienelemente

Die Integration erkennt Anlagen-, Geräte- und Punktreferenzen vom Server. Es gibt keine fest eingebauten Anlagen-IDs oder Wärmepumpenanzahlen.

- Sensoren: Zahlen und Texte aus `curVal`, Einheit aus den Punktmetadaten; zusätzlich Betriebsart und Kaskaden-Zähler.
- Binärsensoren: Boolesche Datenpunkte sowie Verbindung, Betrieb, Alarm und Verfügbarkeit der Geräte.
- Leistungsanzeigen: erzeugte thermische und aufgenommene elektrische Leistung. Die FIN-Abrufe heißen `totalGeneratedEnergy` und `totalConsumedEnergy`, liefern in der Aufzeichnung aber **kW**. Die tatsächliche Einheit wird übernommen; es wird kein kWh-Zähler daraus errechnet.
- Aktualisierung: alle 30 Sekunden; in den Optionen auf 15–300 Sekunden einstellbar. Die Daten werden über `eval` gelesen, ohne serverseitige Watch-Sitzungen anzulegen.
- Ein nicht als `ok` gemeldeter Punkt ist nicht verfügbar. Auch `NA`, `NaN` und unendliche Zahlen werden nicht als Messwerte ausgegeben. Andere Werte werden unverändert übernommen: So stammt die aufgezeichnete Puffertemperatur von **−78 °C** vom Controller selbst und muss an der Anlage geprüft werden.

Unter **Konfigurieren** lassen sich experimentelle Steuerungen aktivieren. Die Auswertung der Aufzeichnungen hat acht passende Punkte ergeben:

| Bedienelement | FIN-Modell |
| --- | --- |
| SG Ready aktivieren | `sgReady` |
| Warmwasser deaktivieren | `stopRun` (wahr bedeutet deaktiviert) |
| Leisemodus | `quietModeRequest` |
| Puffer-Betriebsart | `bufferMode` |
| Zone 1/2 ein/aus | `zone1Zone2OnOffSetpoint` |
| Zone 1 Heiz-Solltemperatur | `zone1WaterTemperatureHotSetpoint` |
| Zone 1 Kühl-Solltemperatur | `zone1WaterTemperatureColdSetpoint` |
| Warmwasser-Solltemperatur | `tankWaterTempSpBeforeSgReady` |

Die Steuerungen verwenden ausschließlich die in den Punktmetadaten beworbene Aktion **`pointSetDef` / Set Default**. Die allgemeinen Schalter, Auswahl- und Temperaturfelder zeigen `writeDef`, also den zu bearbeitenden Standardwert. Der neue Zone-1-Schalter zeigt hingegen den wirksamen Zustand aus `curVal`. Der separate Sensor zeigt `curVal`, also den wirksamen aktuellen Wert. Zeitprogramme und manuelle Übersteuerungen können dafür sorgen, dass diese beiden Werte voneinander abweichen. Die Integration erzeugt keine manuellen oder Notfall-Übersteuerungen.

Temperaturen sind auf konservative Bereiche beschränkt (Heizen 20–55 °C, Kühlen 5–25 °C, Warmwasser 40–60 °C); engere Servergrenzen haben Vorrang. Nummern werden mit ihrer °C-Einheit übertragen. Sterilisationsauslösung, Notfallaktionen und beliebige FIN-Ausdrücke sind nicht als Steuerungen freigegeben. Ob ein Punkt tatsächlich ein Bedienelement erhält, hängt zusätzlich von den Servermetadaten und Schreibrechten ab.

## HACS / GitHub

In HACS unter **Benutzerdefinierte Repositories** die URL `https://github.com/rommelfs/home-assistant-panasonic-cascade` eintragen und als Kategorie **Integration** auswählen. Danach herunterladen und Home Assistant neu starten. HACS-Katalogaufnahme und Hardware-Kompatibilität sind noch nicht bestätigt.

Bei anderem Repository-Namen:

```sh
python3 prepare_hacs.py OWNER/REPOSITORY --maintainer USERNAME
```

Der Befehl ändert ausschließlich das lokale Manifest. Die Vorlage `validation-workflow.yml` prüft Protokolltests und Home-Assistant-Hassfest. Sie ist noch nicht aktiv: Die beim Veröffentlichen verwendete GitHub-Anmeldung erlaubt keine Workflow-Änderungen. Zur Aktivierung die Datei mit einem berechtigten Zugang nach `.github/workflows/validate.yml` verschieben. Eine Aufnahme in den allgemeinen HACS-Katalog ist ein gesonderter Schritt. Brand-Dateien und Lizenzwahl sind noch offen.

## Prüfung und Grenzen

Lokal bestanden: **49 Tests**, darunter Protokolltests, Authentifizierungstests gegen einen lokalen aiohttp-Testserver und Tests des echten Home-Assistant-Konfigurationsdialogs (2026.10.0) mit nachgebildetem FIN-Backend. Dazu kommen Zone-1-Tests für alle Kombinationen, frische Abfragen, Übersteuerungen und gleichzeitige Bedienung sowie Dashboard-Tests einschließlich Speichern/Laden im echten Lovelace-Speicher. Zusätzlich: Import- und Syntaxprüfung aller Integrationsmodule sowie Wiedergabe von 192 Daten-Grids / 308 Zeilen aus den ursprünglichen zwei HAR-Dateien. 54 eindeutige Datenpunkte wurden erfasst. Die umfangreiche Definitionsabfrage `defs()` wurde dabei ausgelassen, da sie keine Betriebsdaten liefert. Die Testdateien und `point-inventory.json` enthalten keine übernommenen Anmelde-Cookies, Tokens oder individuellen Referenz-IDs.

```sh
# Für den vollständigen Testumfang Python 3.14 verwenden.
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
python3 replay_har.py /PFAD/overview.har /PFAD/settings.har
```

Die Authentifizierungstests verwenden echte lokale HTTP-Anfragen mit erfundenen Konten und prüfen vollständigen Login, Cookie/Attestierung, mehrere Projekte, abgelaufene Sitzungen und fehlerhafte Zugangsdaten. Die SCRAM-Berechnung ist zusätzlich mit dem öffentlichen SHA-256-Testvektor aus RFC 7677 geprüft. Sie sind kein erfolgreicher Hardwaretest. Für den vollständigen Testumfang `requirements-dev.txt` installieren. Ohne `aiohttp` werden die lokalen Transporttests, ohne Home Assistant die Einrichtungstests übersprungen. Home Assistant liefert `aiohttp` zur Laufzeit selbst. Ein kompletter laufender Home-Assistant-Eintrag mit angeschlossener Anlage ist noch nicht geprüft.

Bei Änderungen der Anlagenstruktur die Integration neu laden, um neue Punkte zu erkennen. Keine automatische History-Übernahme, kein COP aus den Leistungswerten, kein Climate-Entity und keine Browsersteuerung. Die Login-HAR enthält den Login-Bildschirm und seinen JavaScript-Code, aber nicht den abgeschickten Challenge-Austausch. Die Implementierung ist daher gegen Testserver geprüft und muss an der tatsächlichen Installation bestätigt werden.

Quellen für die Implementierung: bereitgestellte HAR-Dateien, [Haystack Zinc](https://project-haystack.org/doc/docHaystack/Zinc), [Haystack Auth](https://project-haystack.org/doc/docHaystack/Auth), [SCRAM-SHA-256 / RFC 7677](https://www.rfc-editor.org/rfc/rfc7677), [Home-Assistant-Konfigurationsdialog](https://developers.home-assistant.io/docs/core/integration/config_flow/), [DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/), [HACS-Anforderungen](https://www.hacs.dev/docs/publish/integration/).

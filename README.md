# Panasonic Cascade / Smart Edge für Home Assistant

Experimentelle Custom Integration für die lokale FIN-/Haystack-Schnittstelle der Panasonic Cascade Control Oberfläche (`panCascadeControlExt`). Version 0.5.0 ergänzt Alarm-Pushs auf ein ausgewähltes Handy, einschließlich iPhone über die iOS-Companion-App und Apple Push. Seit 0.4.0 gibt es zusätzliche Geräte- und Energiedetails sowie eine Alarmansicht anhand neuer HAR-Aufzeichnungen. Seit 0.3.1 ist die Warmwasseransicht abschaltbar. Seit 0.3.0 gibt es bereinigte Anzeigenamen, einen eigenen Zone-1-Schalter und einen Dashboard-Assistenten. Anmeldung mit Benutzername/Passwort und Projektauswahl sind seit 0.2.0 enthalten. Schreibzugriffe sind noch nicht an einer realen Anlage geprüft.

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

## Alarm-Push auf iPhone / Handy (0.5.0)

1. In HACS auf **0.5.0** aktualisieren und Home Assistant neu starten.
2. Die **Home-Assistant-Companion-App** auf dem iPhone mit demselben Home Assistant verbinden und **Mitteilungen erlauben**. Das iPhone erscheint dadurch als Benachrichtigungsziel in Home Assistant. Für iOS-Cloud-Push nutzt die App die Push-Infrastruktur einschließlich Apple APNs; ist lokaler Push verfügbar, kann Home Assistant diesen Zustellweg bevorzugen.
3. **Einstellungen → Geräte & Dienste → Panasonic Cascade / Smart Edge → Konfigurieren** öffnen. Unter **Alarm-Push aufs Handy** das eigene iPhone auswählen und speichern. Die Auswahl **Ausgeschaltet** deaktiviert Pushs und die zusätzliche schnelle Alarmprüfung. Bestehende Einträge starten mit ausgeschalteten Pushs.
4. Optional **iPhone/iPad: zeitkritische Alarm-Pushs** einschalten. Diese Option setzt `interruption-level: time-sensitive`; die entsprechende Berechtigung muss auf dem iPhone für Home Assistant erlaubt sein. Ohne diese Option wird eine normale iOS-Mitteilung gesendet. Die Integration fordert keinen kritischen Alarm mit erzwungenem Ton an.
5. Auf der Geräteseite der Integration unter Diagnose **Alarm-Push testen** drücken und prüfen, ob die Testnachricht auf dem iPhone ankommt. Dieser Knopf meldet ausdrücklich einen Test und erzeugt keinen echten Anlagenalarm. Er ist nur bei gewähltem Benachrichtigungsziel vorhanden.

Bei aktiviertem Alarm-Push prüft eine separate, lesende Abfrage die aktiven Alarme **etwa alle fünf Sekunden**. Eine neue Meldung wird an das gewählte Handy übergeben, sobald sie dabei erkannt wird; hinzu kommen Reglerantwort- und Push-Laufzeit. Bei Verbindungsfehlern erfolgen Wiederholungen mit Wartezeit. Das normale Messwert-Abfrageintervall bleibt unverändert. Sehr kurze Alarme zwischen zwei Abfragen können bei dieser Abfrageweise unentdeckt bleiben.

Ein aktiver Alarm wird einmal pro erkanntem Auftreten gemeldet. Der Merker wird lokal gespeichert, damit gewöhnliche Neustarts nicht denselben weiterhin aktiven Alarm erneut melden. Ein neues Auftreten mit neuer Alarmzeit sowie ein Alarm nach einem erkannten Normalzustand werden wieder benachrichtigt. Bereits aktive, noch nicht gemeldete Alarme werden auch beim Aktivieren der Funktion gemeldet. Wird ein anderes Handy ausgewählt, erhält es noch aktive Alarme ebenfalls einmal. Historische/auf Normal zurückgekehrte Meldungen und reine Warmwasseralarme bei abgeschalteter Warmwasseroption werden nicht gepusht. Bei unbekannter Zuordnung bleibt ein aktiver Alarm sichtbar und wird nicht vorsorglich ausgefiltert.

Wenn Home Assistant beim Aufruf des Benachrichtigungsziels einen Fehler zurückgibt, bleibt der Alarm für eine erneute Übergabe vorgemerkt. Eine erfolgreich ausgeführte Aktion bestätigt nur die Übergabe an die Companion-App-Benachrichtigung, nicht die tatsächliche Anzeige auf dem Handy. Einige Fehler der nachgelagerten Push-Infrastruktur werden nur durch die Mobile-App-Integration protokolliert. Die tatsächliche Zustellung hängt von Internetverbindung und Mitteilungsberechtigungen ab; deshalb den Test auf dem echten Handy prüfen.

Quellen: [Companion-App-Benachrichtigungen](https://companion.home-assistant.io/docs/notifications/notifications-basic/), [Mobile-App-Push-Anbindung](https://contributors.home-assistant.io/companion/mobile-app-api/notifications/).

## Neue Geräte-, Energie- und Alarmdaten (0.4.0)

Nach dem HACS-Update Home Assistant neu starten. Vorhandene Entitätskennungen bleiben erhalten. Neue Punkte werden beim Laden erkannt. Für die zusätzlichen Dashboard-Ansichten **Energie** und **Alarme** das Cascade-Dashboard erneut befüllen:

```yaml
action: panasonic_cascade.populate_dashboard
data:
  url_path: panasonic-cascade
  overwrite: true
```

Dabei werden individuelle Karten dieses Dashboards ersetzt. Andere Dashboards bleiben bestehen. Die ausgeschaltete Warmwasseroption wird auch für die neuen Gerätedaten berücksichtigt.

- **Je Wärmepumpe:** aufgenommene elektrische und erzeugte thermische Leistung aus der Detailansicht, minimale/maximale Betriebsstunden, Fehlercode der Regleranzeige sowie zusätzliche vom Regler gelieferte Punkte wie Betriebsanforderung, Fehlerstatus, Leistungsanteile und Solltemperaturen. Bereits vorhandene COP-, Druck- und Temperaturpunkte bleiben bestehen.
- **Energiezähler:** Die neuen Daten enthalten echte kWh-Zähler für Heizen, Warmwasser und Kühlen/Wärmerückgewinnung. Nur Energiepunkte mit ausdrücklicher `hisTotalized`-Kennzeichnung erhalten `total_increasing`; kW/W bleiben Leistung. Diese Zähler sind dadurch für passende Home-Assistant-Energieauswertungen verwendbar. Tagesstatistiken entstehen erst durch Home Assistants Aufzeichnung nach dem Update. Es wird keine frühere Energiehistorie importiert. Die vom Regler gelieferte Rohleistung und die berechnete Leistung der Detailansicht können abweichen; die Integration führt diese Anzeigen nicht zu einer neuen Summe zusammen.
- **Geräteparameter:** konfigurierte Zonen, maximale Solltemperaturen, Sensortypen/Regelungstypen, Speicheranschlüsse, Nennleistung und Modellcodes werden zusätzlich als Diagnosewerte gelesen. Vorhandene Modellbezeichnungen, PID- und Kaskadenparameter, Zuschalt-/Abschaltverzögerungen sowie Sollwertverschiebungen werden aus den Geräte- und Anlagendatensätzen angezeigt. Codes ohne bestätigte Zuordnung werden als Codes bezeichnet. Diese neuen Konfigurationsdaten sind ausschließlich lesbar; daraus entstehen keine zusätzlichen Schalt- oder Inbetriebnahmeaktionen.
- **Alarme:** Anzahl aktueller Alarme, Anzahl der Alarmdatensätze im letzten Jahr und letzter Alarm. Attribute und Dashboard zeigen maximal 20 Einträge mit Zeit, Gerät, Text und Status. Historische, bereits normale Alarme werden nicht als aktuell aktive Alarme ausgegeben. Ein numerischer Rohfehlercode allein wird ebenfalls nicht als aktiver Alarm interpretiert. Es gibt keine Quittierungs- oder Löschaktionen. Reine Warmwasseralarme werden bei abgeschalteter Warmwasseransicht ausgefiltert, soweit ihr Zielgerät über die Anlagenmetadaten zugeordnet werden kann.
- **Messqualität:** Der vom Regler als Temperatur gelieferte Wert `−32768` wird als fehlender Messwert behandelt. Andere Werte wie die aufgezeichneten `−78 °C` bleiben unverändert und müssen an der Anlage geprüft werden.

Die optionalen aktuellen Detailwerte werden zusammen in einer `evalAll`-Anfrage pro Abfrageintervall gelesen. Geräteparameter und Alarmverlauf werden innerhalb dieser Anfrage nur alle fünf Minuten neu abgefragt. Nicht unterstützte oder nicht berechtigte optionale Abfragen lassen die normalen Punktabfragen weiterlaufen. Eine fehlgeschlagene Alarmabfrage erscheint als nicht verfügbar und wird nicht als „keine Alarme“ ausgegeben. Wetterprognosen, Rohkurven und vollständige Controller-Historien werden nicht in Home Assistants Recorder nachgetragen.

## Warmwasseraufbereitung ausblenden (ab 0.3.1)

In HACS auf **0.5.0** aktualisieren und Home Assistant neu starten. Unter **Einstellungen → Geräte & Dienste → Panasonic Cascade / Smart Edge → Konfigurieren** die Option **Warmwasseraufbereitung verwenden** abwählen und speichern. Die Integration lädt sich automatisch neu. Die Einstellung gilt pro Installation und ist zunächst eingeschaltet, damit bestehende Installationen ihre Werte behalten.

Ausgeblendet werden reine Trinkwarmwasser-Speicherwerte und Bedienelemente, Sterilisation/Legionellenfunktionen, Warmwasser-COP sowie der reine Warmwasser-Verfügbarkeitsstatus. Heizungs-COP, Pufferspeicher einschließlich seiner Temperaturdifferenz, gemeinsame Wärmepumpenwerte, SG Ready und Zonensteuerung bleiben erhalten. Die Option ist eine Home-Assistant-Anzeigeeinstellung; sie sendet keinen Schaltbefehl und ändert keine Anlagenkonfiguration.

Bereits vorhandene Warmwasserentitäten werden intern deaktiviert und ausgeblendet, damit ihre Kennungen und selbst vergebenen Namen erhalten bleiben. In Home Assistants vollständiger Entitätsverwaltung bleiben sie als deaktivierte Einträge auffindbar. Neue Warmwasserentitäten werden bei abgeschalteter Option nicht angelegt. Die normalen Dashboard- und Steuerungsansichten enthalten sie nicht mehr.

Vorhandene native Dashboard-Karten werden von den passenden Warmwasserreferenzen bereinigt; reine Warmwasserkarten verschwinden. Beim erneuten Einschalten werden zuvor ausgeblendete Entitäten und unverändert gebliebene Dashboards wiederhergestellt. Selbst deaktivierte Entitäten bleiben deaktiviert. Wird ein Dashboard zwischenzeitlich bearbeitet oder neu befüllt, wird es beim Einschalten nicht überschrieben; dann kann das Cascade-Dashboard bei Bedarf erneut über `panasonic_cascade.populate_dashboard` befüllt werden. YAML-Dashboards und individuelle Karten mit eigenen Datenformaten müssen gegebenenfalls manuell angepasst werden.

## Aktualisierung ab 0.3.0: Namen, Zone 1 und Dashboard

In HACS Version **0.5.0** herunterladen (gegebenenfalls Vorabversionen anzeigen) und Home Assistant neu starten. Anzeigenamen enthalten jetzt keine senkrechten Striche mehr. Die eindeutigen Entitäts- und Gerätekennungen bleiben erhalten; bereits verwendete Entitäts-IDs und selbst vergebene Namen ändern sich nicht.

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

Lokal bestanden: **82 Tests**, darunter Protokolltests, Authentifizierungstests gegen einen lokalen aiohttp-Testserver und Tests des echten Home-Assistant-Konfigurationsdialogs (2026.10.0) mit nachgebildetem FIN-Backend. Dazu kommen Zone-1-Tests für alle Kombinationen, frische Abfragen, Übersteuerungen und gleichzeitige Bedienung sowie Dashboard-Tests einschließlich Speichern/Laden im echten Lovelace-Speicher. Weitere Tests prüfen Warmwasserfilterung über alle Plattformen, Optionen, das Ausblenden/Wiederherstellen vorhandener Dashboards und den Erhalt eigener Änderungen. Ergänzend geprüft: optionale Mehrfachabfragen mit einzelnen Fehlern, Detailcache, Alarmverlauf ohne Benutzer-/Auditdaten, Energie-Statistiken, Temperatur-Sentinel und neue Dashboard-Ansichten. Die Push-Tests verwenden einen lokal registrierten Home-Assistant-Testempfänger und prüfen neue Alarmepisoden, Bestätigung ohne Wiederholung, Neustart-Merker, Zielwechsel, Warmwasserfilter, Fehlversuche, parallele Abfragen, Entladen, Testknopf und Optionen. Es wurde dabei keine Nachricht an ein echtes Handy gesendet. Zusätzlich: Import- und Syntaxprüfung aller Integrationsmodule sowie Wiedergabe von 192 Daten-Grids / 308 Zeilen aus den ursprünglichen zwei HAR-Dateien. 54 eindeutige Datenpunkte wurden in den ursprünglichen Aufzeichnungen erfasst. Die neun zusätzlichen HAR-Dateien aus dem Webinterface wurden mit 3.675 Grids / 7.362 Zeilen wiedergegeben; sie enthalten 103 eindeutige Punktdatensätze. Alle 18 neu verwendeten Detailabfragen konnten zu aufgezeichneten Antworten zugeordnet werden. `point-inventory.json` enthält dafür nur generische Modellkennungen, Feldbezeichnungen und Einheiten, keine Anlagenkennungen oder Messwerte. Die umfangreiche Definitionsabfrage `defs()` wurde dabei ausgelassen, da sie keine Betriebsdaten liefert. Die Testdateien und `point-inventory.json` enthalten keine übernommenen Anmelde-Cookies, Tokens oder individuellen Referenz-IDs.

```sh
# Für den vollständigen Testumfang Python 3.14 verwenden.
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
python3 replay_har.py /PFAD/overview.har /PFAD/settings.har
```

Die Authentifizierungstests verwenden echte lokale HTTP-Anfragen mit erfundenen Konten und prüfen vollständigen Login, Cookie/Attestierung, mehrere Projekte, abgelaufene Sitzungen und fehlerhafte Zugangsdaten. Die SCRAM-Berechnung ist zusätzlich mit dem öffentlichen SHA-256-Testvektor aus RFC 7677 geprüft. Sie sind kein erfolgreicher Hardwaretest. Für den vollständigen Testumfang `requirements-dev.txt` installieren. Ohne `aiohttp` werden die lokalen Transporttests, ohne Home Assistant die Einrichtungstests übersprungen. Home Assistant liefert `aiohttp` zur Laufzeit selbst. Ein kompletter laufender Home-Assistant-Eintrag mit angeschlossener Anlage ist noch nicht geprüft.

Bei Änderungen der Anlagenstruktur die Integration neu laden, um neue Punkte zu erkennen. Keine automatische History-Übernahme, kein selbst errechneter COP aus den Leistungswerten, kein Climate-Entity und keine Browsersteuerung. Die Login-HAR enthält den Login-Bildschirm und seinen JavaScript-Code, aber nicht den abgeschickten Challenge-Austausch. Die Implementierung ist daher gegen Testserver geprüft und muss an der tatsächlichen Installation bestätigt werden.

Quellen für die Implementierung: bereitgestellte HAR-Dateien, [Haystack Zinc](https://project-haystack.org/doc/docHaystack/Zinc), [Haystack Auth](https://project-haystack.org/doc/docHaystack/Auth), [SCRAM-SHA-256 / RFC 7677](https://www.rfc-editor.org/rfc/rfc7677), [Home-Assistant-Konfigurationsdialog](https://developers.home-assistant.io/docs/core/integration/config_flow/), [DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/), [HACS-Anforderungen](https://www.hacs.dev/docs/publish/integration/).

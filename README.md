# Panasonic Cascade / Smart Edge für Home Assistant

Experimentelle Custom Integration für die lokale FIN-/Haystack-Schnittstelle der Panasonic Cascade Control Oberfläche (`panCascadeControlExt`). Version 0.1.0 wurde anhand von zwei HAR-Aufzeichnungen entwickelt. Die Home-Assistant-Laufzeit, die Verbindung zur realen Anlage und Schreibzugriffe sind noch nicht live geprüft.

Repository: [rommelfs/home-assistant-panasonic-cascade](https://github.com/rommelfs/home-assistant-panasonic-cascade).

## Installation zum lokalen Testen

1. Den Ordner `custom_components/panasonic_cascade` aus diesem Paket nach `/config/custom_components/panasonic_cascade` auf dem Home-Assistant-System kopieren.
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Panasonic Cascade / Smart Edge** öffnen.
4. HTTPS-Adresse des Controllers eingeben; eine vollständige URL zur Anlagenübersicht wird ebenfalls akzeptiert. Das Projekt ist bei der untersuchten Anlage `pSmartEdge`.
5. Sitzungs-Cookie und gegebenenfalls `SkyArc-Attest-Key` eingeben. Alternativ wird ein FIN-Bearer-Token unterstützt, sofern der Controller solche Tokens bereitstellt. Diese Alternative ist im Client-Code der Weboberfläche vorhanden, wurde aber im HAR nicht als tatsächliche Anmeldung beobachtet.
6. Bei einem selbstsignierten Zertifikat kann **HTTPS-Zertifikat prüfen** ausgeschaltet werden. Die Verbindung bleibt verschlüsselt, aber die Serveridentität wird dann nicht geprüft. Es ist kein individueller Fingerprint fest eingebaut.
7. Die erkannte Anlage auswählen. Zunächst sind nur Messwerte und Statusanzeigen aktiv.

Der Home-Assistant-Rechner muss die Controller-Adresse selbst erreichen können. Die Beispieladresse `172.17.0.1` ist nicht auf jedem Rechner dieselbe Anlage und muss gegebenenfalls durch die LAN-Adresse ersetzt werden.

## Sitzungszugang aus Safari

Diese erste Version automatisiert keinen Benutzername-/Passwort-Login: In den gelieferten HAR-Dateien war nur eine bereits angemeldete Sitzung aufgezeichnet.

1. In Safari am Controller anmelden.
2. Web-Inspektor öffnen und unter **Netzwerk** die Seite neu laden.
3. Einen erfolgreichen Abruf an `/api/pSmartEdge/eval`, `evalAll` oder `watchPoll` auswählen.
4. Unter den **Anfrage-Headern** den vollständigen Wert von `Cookie` in das Feld **Sitzungs-Cookie** in Home Assistant eintragen. Im untersuchten System heißt der Anmelde-Cookie `skyarc-auth-80`; sein Name kann auf anderen Anlagen abweichen.
5. Falls in derselben Anfrage vorhanden, den Wert von `SkyArc-Attest-Key` in das gleichnamige Feld eintragen.

Die Werte direkt in Home Assistant eingeben und nicht in GitHub, Screenshots, Protokolle oder diesen Chat kopieren. Home Assistant speichert sie als Integrationskonfiguration; seine Konfigurationsdateien und Backups enthalten deshalb Zugangsdaten. Läuft die Sitzung ab, fordert die Integration zur erneuten Eingabe auf. Ein automatischer, dauerhafter Login benötigt noch einen dokumentierten FIN-Anmeldeweg oder einen geeigneten dauerhaften API-Zugang.

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

Die Steuerungen verwenden ausschließlich die in den Punktmetadaten beworbene Aktion **`pointSetDef` / Set Default**. Sie zeigen `writeDef`, also den zu bearbeitenden Standardwert. Der separate Sensor zeigt `curVal`, also den wirksamen aktuellen Wert. Zeitprogramme und manuelle Übersteuerungen können dafür sorgen, dass diese beiden Werte voneinander abweichen. Die Integration erzeugt keine manuellen oder Notfall-Übersteuerungen.

Temperaturen sind auf konservative Bereiche beschränkt (Heizen 20–55 °C, Kühlen 5–25 °C, Warmwasser 40–60 °C); engere Servergrenzen haben Vorrang. Nummern werden mit ihrer °C-Einheit übertragen. Sterilisationsauslösung, Notfallaktionen und beliebige FIN-Ausdrücke sind nicht als Steuerungen freigegeben. Ob ein Punkt tatsächlich ein Bedienelement erhält, hängt zusätzlich von den Servermetadaten und Schreibrechten ab.

## HACS / GitHub

In HACS unter **Benutzerdefinierte Repositories** die URL `https://github.com/rommelfs/home-assistant-panasonic-cascade` eintragen und als Kategorie **Integration** auswählen. Danach herunterladen und Home Assistant neu starten. HACS-Katalogaufnahme und Hardware-Kompatibilität sind noch nicht bestätigt.

Bei anderem Repository-Namen:

```sh
python3 prepare_hacs.py OWNER/REPOSITORY --maintainer USERNAME
```

Der Befehl ändert ausschließlich das lokale Manifest. Die Vorlage `validation-workflow.yml` prüft Protokolltests und Home-Assistant-Hassfest. Sie ist noch nicht aktiv: Die beim Veröffentlichen verwendete GitHub-Anmeldung erlaubt keine Workflow-Änderungen. Zur Aktivierung die Datei mit einem berechtigten Zugang nach `.github/workflows/validate.yml` verschieben. Eine Aufnahme in den allgemeinen HACS-Katalog ist ein gesonderter Schritt. Brand-Dateien und Lizenzwahl sind noch offen.

## Prüfung und Grenzen

Lokal bestanden: 15 Protokoll- und Mock-Transporttests, Syntaxprüfung aller Integrationsmodule sowie Wiedergabe von 192 Daten-Grids / 308 Zeilen aus den zwei HAR-Dateien. 54 eindeutige Datenpunkte wurden erfasst. Die umfangreiche Definitionsabfrage `defs()` wurde dabei ausgelassen, da sie keine Betriebsdaten liefert. Die Testdateien und `point-inventory.json` enthalten keine übernommenen Anmelde-Cookies, Tokens oder individuellen Referenz-IDs.

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
python3 replay_har.py /PFAD/overview.har /PFAD/settings.har
```

Die Mock-Tests ersetzen Netzwerkverkehr; sie sind kein erfolgreicher Home-Assistant- oder Hardwaretest. Die Tests können mit der Python-Standardbibliothek laufen; wenn `aiohttp` installiert ist, verwenden sie dessen echte Timeout-/Exception-Typen und weiterhin einen Mock-Transport. Home Assistant liefert `aiohttp` zur Laufzeit selbst.

Bei Änderungen der Anlagenstruktur die Integration neu laden, um neue Punkte zu erkennen. Keine automatische History-Übernahme, kein COP aus den Leistungswerten, kein Climate-Entity, keine Browsersteuerung und kein bisher verifizierter Dauerzugang per Benutzername/Passwort.

Quellen für die Implementierung: bereitgestellte HAR-Dateien, [Haystack Zinc](https://project-haystack.org/doc/docHaystack/Zinc), [Home-Assistant-Konfigurationsdialog](https://developers.home-assistant.io/docs/core/integration/config_flow/), [DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/), [HACS-Anforderungen](https://www.hacs.dev/docs/publish/integration/).

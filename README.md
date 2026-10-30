# Panasonic Cascade / Smart Edge for Home Assistant

Experimental custom integration for the local FIN/Haystack API used by the Panasonic Cascade Control web interface (`panCascadeControlExt`).

The integration provides username/password authentication, project and installation selection, sensors, optional controls, dashboards, and alarm notifications. Version **0.7.1** adds a visible seven-day table of absolute observed start counts per heat pump. Version 0.7.0 introduced the daily sensors, compact default labels, and cleaner control/energy cards. It fixes the heating-curve HTTP 404 when the frontend is not ready at integration startup. Energy/runtime views and non-destructive updates with backups remain available. Hardware writes have not yet been verified on a real installation.

Repository: [rommelfs/home-assistant-panasonic-cascade](https://github.com/rommelfs/home-assistant-panasonic-cascade). See the [changelog](CHANGELOG.md) and [release notes](docs/releases/) for version-specific changes.

## Tested equipment and software

The reference installation uses **two Panasonic WH-WXG09ME8 outdoor units (9 kW each)** with **P-SMART EDGE v5.1**. The controller identifies the main unit's indoor/controller model as **WH-CME8** and the second unit as **Standalone**. Automated tests use **Home Assistant Core 2026.10.0 and Python 3.14**.

See [tested installation and software versions](docs/tested-installations.md) for the evidence, unknown firmware versions, and the distinction between observed operation, automated tests, and outstanding hardware/phone verification. Compatibility with other models or controller versions has not been verified.

## Installation

### HACS

1. In HACS, open **Custom repositories**.
2. Add `https://github.com/rommelfs/home-assistant-panasonic-cascade` with category **Integration**.
3. Download the integration. Enable prereleases in HACS if the desired version is not listed.
4. Restart Home Assistant.

Inclusion in the default HACS catalog and hardware compatibility have not been confirmed.

### Manual installation

1. Copy `custom_components/panasonic_cascade` from this package to `/config/custom_components/panasonic_cascade` on the Home Assistant system.
2. Restart Home Assistant.

### Connect the controller

1. Open **Settings → Devices & services → Add integration → Panasonic Cascade / Smart Edge**.
2. Enter the controller's **HTTPS address, username, and password**. A full URL to the plant overview is also accepted. The password may be empty for accounts configured without a password.
3. For a self-signed certificate, you can turn off **Verify HTTPS certificate**. Transport remains encrypted, but the server's identity is then not verified. No installation-specific certificate fingerprint is embedded in the integration.
4. Select a project from the discovered project list, then select the installation within that project.
5. Add another integration entry to connect another project. Projects have separate entries and entities; the same installation cannot be configured twice.

Home Assistant must be able to reach the controller directly. The example address `172.17.0.1` does not identify the same controller on every computer; replace it with the appropriate LAN address when necessary.

Home Assistant UI labels depend on the selected language. The steps in this guide describe the controls in English; existing generated entity and dashboard names may use another language.

## Authentication and existing installations

Authentication follows the mechanism offered by FIN: SCRAM, legacy HMAC, or server-requested plaintext credentials over HTTPS. Session cookies and `SkyArc-Attest-Key` are retrieved automatically and held only in memory. Explicit session expiry triggers one bounded reauthentication attempt and request retry. Invalid credentials or access-denied responses can prompt reauthentication. Password derivation does not block Home Assistant's event loop.

Existing cookie-based entries from 0.1.0 remain supported. Select **Reconfigure** from the existing integration entry's menu to switch to username/password authentication. **Reauthenticate** is also available after session expiry. The project, installation, and entity IDs are retained. If you replace an entry instead, remove the existing entry for the same installation before setting it up again.

The username and password are stored in Home Assistant's configuration. Automatically issued session cookies and attestation keys are not persisted in that configuration. Protect credentials and Home Assistant backups; do not publish them in GitHub or paste them into chat.

## Updating

If binary entities are missing or the heating curve reports **Custom element doesn't exist**, update to **0.7.0 or later**, restart Home Assistant, and fully reload the browser/app. A 404 at `/panasonic_cascade/heating-curve.js` can result from the old frontend readiness check skipping HTTP registration. Version 0.7.0 registers the file independently of frontend readiness and retries module/resource registration after HA starts. Earlier binary platform setup could fail with `NameError: name 'row' is not defined`; 0.6.2 fixes that error. It also registers the curve before controller/platform setup and persists its module in dashboard resources. Existing entity IDs and dashboard configurations are retained. A dashboard already containing these cards does not need to be replaced.


Download the desired version in HACS and restart Home Assistant. Entity and device unique IDs are retained. Existing entity IDs and user-assigned names are preserved. Reloading the integration discovers new points when the plant structure changes.

After updating, restart Home Assistant. Add new dashboard content with `populate_dashboard` and `update: true`, as described below. This preserves existing views, cards, display settings and custom entity names; it adds missing content. Do not use `overwrite: true` for routine updates.

## Alarm notifications on iPhone and other phones

Available since 0.5.0.

1. Connect the **Home Assistant Companion App** on the phone to the same Home Assistant instance and allow notifications. This creates a phone notification target in Home Assistant.
2. Open **Settings → Devices & services → Panasonic Cascade / Smart Edge → Configure**.
3. Select your phone in the alarm push destination option and save. Selecting the disabled/empty destination turns off notifications and the additional fast alarm checks. Notifications are disabled by default for existing entries.
4. Optionally enable **iPhone/iPad: time-sensitive alarm notifications**. This sets `interruption-level: time-sensitive`; allow time-sensitive notifications for Home Assistant in iOS settings. With this option disabled, iOS receives a normal notification. The integration does not request a critical alert with forced sound.
5. On the integration's device page, press the diagnostic **alarm push test button** and confirm receipt on the phone. The message explicitly identifies itself as a test and does not create a controller alarm. The button is available only when a notification destination is selected.

For iPhone cloud notifications, the Companion App uses push infrastructure including Apple APNs. Home Assistant may prefer local push when it is available.

When enabled, a separate read-only request checks active alarms **approximately every five seconds**. A new alarm is handed to the selected notification target when detected; controller response and push delivery time are additional. Connection failures cause retries with a delay. The normal measurement polling interval is unchanged. Alarms shorter than the interval between checks can be missed.

Each detected active alarm episode is notified once. A local marker prevents ordinary restarts from sending the same still-active alarm again. A new alarm timestamp, or a recurrence after an observed normal state, produces another notification. Enabling notifications also reports already-active alarms that have not been sent. Selecting a different phone reports still-active alarms to that phone once.

Historical and returned-to-normal alarms are not pushed. When domestic hot water is disabled, alarms identified as exclusively related to domestic hot water are excluded. An active alarm with an unknown equipment association is retained rather than silently filtered out.

If the Home Assistant notification action raises an error, the alarm remains pending for retry. A successful action confirms handoff to the notification integration, not display on the phone. Some downstream failures are logged only by the Mobile App integration. Actual delivery depends on connectivity and notification permissions; verify it using the test button on your real phone.

References: [Companion App notifications](https://companion.home-assistant.io/docs/notifications/notifications-basic/), [Mobile App push integration](https://contributors.home-assistant.io/companion/mobile-app-api/notifications/).

## Sensors, energy, and equipment diagnostics

The integration discovers installation, equipment, and point references from the controller. Installation IDs and heat pump counts are not hardcoded.

- **Sensors:** numeric and text values from `curVal`, with units from point metadata, plus equipment mode and cascade counters.
- **Binary sensors:** Boolean points and equipment connection, operation, alarm, and availability states.
- **Power:** generated thermal power and consumed electrical power. The FIN overview endpoints are named `totalGeneratedEnergy` and `totalConsumedEnergy`, but the captures return **kW**. The actual unit is retained; these values are not converted into kWh meters.
- **Per-unit detail values:** electrical and thermal power from the detail view, minimum/maximum working hours, the error code displayed by the controller, operating requests, fault states, capacities, and setpoints. Existing COP, pressure, and temperature points remain available.
- **Energy counters:** the newer captures include real kWh counters for heating, domestic hot water, and cooling/heat recovery. Only energy points explicitly marked `hisTotalized` receive the `total_increasing` state class. W/kW readings remain power. Eligible counters can be used in Home Assistant energy reporting. Daily statistics accumulate after Home Assistant starts recording them; earlier controller energy history is not imported. Raw power readings and the controller's calculated detail-view power can differ; the integration does not combine them into a new total.
- **Read-only diagnostics:** configured zones, maximum setpoints, sensor/control types, tank connections, rated capacity, and model codes. Equipment and plant records also expose available model names, PID/cascade settings, staging delays, and setpoint offsets. Values without a confirmed code-to-label mapping remain identified as codes. These additions do not create new commissioning controls.

Measurements are normally updated every **30 seconds**, configurable from **15–300 seconds**. Optional current detail values share one `evalAll` request per polling cycle. Equipment parameters and alarm history are refreshed within that request only every **five minutes**. Unsupported or unauthorized optional requests do not stop normal point polling. No server-side watch sessions are created.

A point with a status other than `ok` is unavailable. `NA`, `NaN`, and infinite numbers are not exposed as measurements. A temperature value of **−32768** is treated as unavailable. Other readings are retained unchanged: for example, the captured buffer temperature of **−78 °C** comes from the controller and requires investigation at the installation.

## Alarms and history

Available since 0.4.0:

- Current alarm count.
- Number of alarm records in the past year.
- Most recent alarm.
- Up to **20 displayed records** in attributes and the dashboard, including time, equipment, text, and status.

Historical alarms that have returned to normal are not reported as currently active. A numeric raw error code alone is not interpreted as an active alarm. Alarm acknowledgement and deletion actions are not provided. With domestic hot water disabled, exclusively domestic-hot-water alarms are filtered when their target can be identified from installation metadata.

A failed alarm request is reported as unavailable rather than as zero alarms. Weather forecasts, raw historical curves, and full controller histories are not backfilled into Home Assistant's Recorder.

## Hide domestic hot water

Available since 0.3.1; applies independently to each installation.

Open **Settings → Devices & services → Panasonic Cascade / Smart Edge → Configure**, turn off **Use domestic hot water**, and save. The integration reloads automatically. This option defaults to enabled so existing installations retain their data.

The option hides exclusively domestic-hot-water tank values and controls, sterilization/legionella functions, domestic-hot-water COP, availability/operation status, and newly discovered unit-level domestic-hot-water power, energy, and setpoint readings. Heating COP, the heating buffer and its temperature difference, shared heat pump values, SG Ready, and zone controls remain available. This changes Home Assistant visibility only; it does not send a switching command or change the controller configuration.

Existing domestic-hot-water entities are disabled and hidden internally to preserve their IDs and user-assigned names. They remain discoverable as disabled entries in Home Assistant's full entity registry. New domestic-hot-water entities are not created while the option is disabled.

Existing native dashboard cards are cleaned of matching entity references; cards containing only domestic-hot-water entities are removed. Re-enabling the option restores previously hidden entities and dashboards that have remained unchanged. Entities disabled by the user remain disabled. If a dashboard is edited or regenerated in the meantime, it is not overwritten on re-enabling; regenerate the Cascade dashboard if required. YAML dashboards and custom cards with their own data formats may need manual adjustment.

## Optional controls and Zone 1 switching

Open **Configure**, enable the experimental controls option, and save. Controls are disabled by default. Twelve supported point models were identified in the captures:

| Control | FIN model |
| --- | --- |
| Enable SG Ready | `sgReady` |
| Disable domestic hot water | `stopRun` (`true` means disabled) |
| Quiet mode | `quietModeRequest` |
| Buffer operating mode | `bufferMode` |
| Zone 1/2 on/off selection | `zone1Zone2OnOffSetpoint` |
| Zone 1 heating water setpoint | `zone1WaterTemperatureHotSetpoint` |
| Zone 1 cooling water setpoint | `zone1WaterTemperatureColdSetpoint` |
| Domestic-hot-water setpoint | `tankWaterTempSpBeforeSgReady` |
| Zone 1 heating curve: max. water | `compensationCurveHeatZone1MaxTemperature` |
| Zone 1 heating curve: min. water | `compensationCurveHeatZone1MinTemperature` |
| Zone 1 heating curve: max. outdoor | `compensationCurveHeatZone1OutdoorAirMaxTemperature` |
| Zone 1 heating curve: min. outdoor | `compensationCurveHeatZone1OutdoorAirMinTemperature` |

Controls use only the **`pointSetDef` / Set Default** action advertised in point metadata. General switches, selectors, and temperature controls display `writeDef`, the default being edited. Separate point sensors display `curVal`, the currently effective value. Schedules and manual overrides can make these values differ. The integration does not create manual or emergency overrides.

Temperature limits are conservative: **20–55 °C** for heating, **5–25 °C** for cooling, and **40–60 °C** for domestic hot water. The four heating-curve controls use the captured limits: **20–75 °C** for water endpoints and **−20 to +15 °C** for outdoor endpoints. Tighter controller limits take precedence; water-temperature limits do not restrict the outdoor axis. Numeric setpoints are sent with their °C unit. Sterilization triggers, emergency actions, and arbitrary FIN expressions are not exposed as controls. Actual control availability also depends on server metadata and write permissions.

### Zone 1 heating curve and live preview

Available since 0.6.0. Enable experimental controls in **Configure** to create four number entities named **Zone 1 – Heizkurve – … – Standardwert**. They are also editable from the device's entity list and through Home Assistant's `number.set_value` action. Existing point sensors remain available and keep their IDs.

Regenerate the integration dashboard after updating:

```yaml
action: panasonic_cascade.populate_dashboard
data:
  url_path: panasonic-cascade
  update: true
```

Requires 0.6.1 or later. Use the actual URL path of your dashboard. `update: true` preserves existing cards and adds missing content. The generated overview includes a bundled **Zone 1 heating curve** card whenever all four matching entities are enabled. No third-party chart card is required. The JavaScript module is registered automatically by the integration before controller/platform setup. It is also added to storage-mode dashboard resources as `/panasonic_cascade/heating-curve-0.7.0.js?v=0.7.0` (JavaScript module); older/duplicate integration resource entries are updated. The versioned filename avoids reusing an old resource path. The legacy `/panasonic_cascade/heating-curve.js` address continues to serve the same file. HTTP registration no longer waits for the frontend URL manager; missing frontend/resource registration is retried after startup. YAML resource configuration is left unchanged and still uses the global frontend module registration. Restart Home Assistant and fully reload the browser/app after updating. Without controls, the card displays a read-only curve using the sensor values. When the editable curve is present, its four inputs are omitted from the general Controls card; other controls such as zone switching remain.

Editing the card's four inputs updates the plotted curve **immediately as a local preview**, without waiting for controller polling. **Apply** sends only changed values through the existing number controls. **Discard preview** drops local edits; it does not undo commands already sent. Outside the two outdoor endpoints the curve is flat; between them it interpolates linearly. Endpoint coordinates and pointer/touch readout make the configured water temperature readable along the curve. Changes from elsewhere in Home Assistant update the graph when entity states arrive.

The card blocks missing/out-of-range values and requires the minimum outdoor temperature to be below the maximum and the minimum water temperature not to exceed the maximum. It hides the curve when source values are unavailable. Editing the number entities separately bypasses the card's cross-field checks, so keep the four endpoints consistent when using automations or individual entity controls.

**Apply is not an atomic four-value operation:** individual writes run sequentially. If one fails, earlier values may already have reached the controller; the card reports the failure and retains remaining edits for review. Controller-confirmed entity updates clear pending previews. The curve represents configured defaults, not measured water temperature or a guarantee of the effective operating setpoint. Schedules, overrides, and the controller's selected regulation mode can take precedence. Hardware writes still require live verification.

For a manually maintained dashboard, add this card with your actual entity IDs (enable controls first for `number.*` IDs):

```yaml
type: custom:panasonic-cascade-heating-curve
title: Zone 1 – Heating curve
entities:
  water_max: number.your_water_max
  water_min: number.your_water_min
  outdoor_max: number.your_outdoor_max
  outdoor_min: number.your_outdoor_min
```

### Dedicated Zone 1 switch

Available since 0.3.0 when controls are enabled and the controller advertises the shared Zone 1/2 point as writable. The switch displays the currently effective state of Zone 1.

Before switching, the integration rereads the shared value from the selected installation. It changes only the first component, for example `On/On` to `Off/On`, retaining Zone 2 from that fresh read. Integration writes are serialized. Unknown states or effective values that differ from the default prevent the write; check for a schedule or override in the controller interface first.

This switch also uses `pointSetDef`. The protocol cannot atomically exclude a simultaneous change by another operator between the read and write.

## Dashboard

1. Open **Settings → Dashboards → Add dashboard** and create an **empty dashboard**. For example, use title **Panasonic Cascade**, URL path **panasonic-cascade**, and show it in the sidebar.
2. Open **Developer tools → Actions** and select `panasonic_cascade.populate_dashboard`.
3. Enter `panasonic-cascade` as the dashboard URL path, without slashes. This is the URL path, not the title. Optionally select a single integration entry when multiple installations are configured.
4. Run the action and open the dashboard from the sidebar.

Equivalent YAML:

```yaml
action: panasonic_cascade.populate_dashboard
data:
  url_path: panasonic-cascade
```

The generated dashboard provides an overview of controls, setpoints, power, temperatures, operating states, and histories; a device-grouped view of all values; and energy/alarm views when the corresponding entities are available. Histories and statistics fill as Home Assistant records data. Earlier controller history is not imported.

The helper uses actual registered entity IDs, including renamed IDs and numeric suffixes. It requires administrator access and an existing storage-mode dashboard. Populating an already configured dashboard requires either `update: true` (recommended) or explicit replacement.

To add missing cards and entities after enabling controls, discovering new equipment, or updating the integration, use:

```yaml
action: panasonic_cascade.populate_dashboard
data:
  url_path: panasonic-cascade
  update: true
```

Available since 0.6.1. Safe updates retain existing views, cards, graph time ranges, layout settings and custom entity labels. Version 0.7.0 shortens recognizable autogenerated row labels and removes known redundant curve-control rows, legacy Site Info energy placeholders, and repeated plant min/max runtime rows from the relevant integration overview cards. These values remain under All values. Other custom cards and manually assigned entity names are retained; a configuration backup is saved before the update. Missing views/cards and entity rows are added; repeating the update does not duplicate the generated content. Sections layouts are supported. Existing single-card panel views are kept intact, with additions in a separate `-cascade` view. Strategy dashboards require a separate storage dashboard. The domestic-hot-water visibility option applies to generated content.

The **Energy** view omits the legacy unavailable “Site Info” energy placeholders while keeping them under **All values**. Valid zero readings remain zero; missing readings are never replaced with zero. Compact labels such as **WP 1 · Heizen · Stromzähler** distinguish electrical consumption from generated thermal energy. It includes electrical and thermal power history, cumulative energy history, and separate **electricity consumption** bar charts for **hourly, daily, weekly, monthly and yearly** intervals. Electricity charts use changes in cumulative electrical-energy counters with long-term statistics; thermal generation and kW power readings are excluded. Existing energy statistics are reused. The available history determines how far each chart is populated; the integration does not reconstruct missing history or sum potentially overlapping series. If no suitable electrical counter exists, the dashboard explains this instead of drawing a misleading chart. These are native [statistics graph cards](https://www.home-assistant.io/dashboards/statistics-graph/).

The **Runtime & cycling** view includes an **Einschaltungen pro Tag** (starts per day) table with **Today, Yesterday and five earlier dates**, one column per heat pump. Version 0.7.1 inserts this native Markdown table automatically after startup into recognized integration runtime views in storage dashboards, backing up each changed configuration first. Existing cards and settings are retained; repeating startup does not duplicate the table. Custom tables, panel views and other layouts are left intact; use the safe `update: true` action above to add the table to other supported generated layouts. Missing history appears as a dash; an asterisk marks incomplete coverage.

The underlying **Starts today** sensor for each heat pump provides an absolute count of recorded **off → on** transitions since midnight in Home Assistant's configured local timezone. It refreshes approximately once a minute and reconstructs the count from Recorder after integration/HA restarts. Running across midnight, an initial already-on sample, or `unavailable → on` does not create an inferred start. Recorder is required and must include the source running-state entity; without usable history the value is unavailable rather than a fabricated zero. The `partial_day` attribute identifies history starting after midnight, unknown gaps, or a currently unavailable source. Counts are confirmed observed starts, not a guarantee of every physical compressor start: events between controller polls or during gaps may be missed. Calendar boundaries respect local timezone/DST. The `daily_starts` attribute supplies date, count and partial-coverage status for each of the last seven calendar days. One weekly Recorder query per pump refreshes these values approximately once a minute; existing today-sensor IDs remain unchanged.

Actual per-unit compressor-hour counters are preferred over repeated plant minimum/maximum diagnostics in the runtime overview. Full diagnostics remain under **All values**. The view also includes a native **Operation and cycling – 24 hours** history card with a simple horizontal **running/stopped band per heat pump**, updated from actual running-state sensors. It shows running-state timelines for the heat pumps (24 hours), available compressor/working-hour counters and their history, and power history for comparison. It does not invent cycle counts from operating requests or infer past run events from a cumulative hour counter. Recorder retention determines the available on/off timeline.

Before any modification of an existing dashboard, version 0.6.1 or later saves a configuration backup in Home Assistant storage. Up to five previous configurations per dashboard are retained; a failed backup prevents the dashboard write. An identical update does not create another backup. To restore the latest saved configuration:

```yaml
action: panasonic_cascade.restore_dashboard
data:
  url_path: panasonic-cascade
```

The current configuration is backed up before restoring. These are local dashboard-configuration backups, not Recorder/database backups. **They cannot recover cards overwritten by version 0.6.0 or earlier:** those versions did not create these backups. Recover the exact original layout from a Home Assistant backup from before the replacement if available. Safe update can rebuild the integration's generated energy/runtime content, but cannot reconstruct unknown custom cards.

`overwrite: true` remains available for an intentional full replacement, with a backup first. It cannot be combined with `update: true`. Avoid it for routine updates.

## Repository and development

If using a different repository name:

```sh
python3 prepare_hacs.py OWNER/REPOSITORY --maintainer USERNAME
```

This updates only the local manifest. The active [validation workflow](.github/workflows/validate.yml) runs the test suite, Home Assistant Hassfest, and HACS validation without ignored checks. It runs on pushes, pull requests, a weekly schedule, and manual dispatch. Catalog inclusion is subject to review by the HACS maintainers.

The project and original integration artwork are distributed under the [MIT license](LICENSE). Local brand images are included under `custom_components/panasonic_cascade/brand/`; Home Assistant supports these local images from version 2026.3 onward. This is an independent community integration, not an official Panasonic or Home Assistant product. See [CONTRIBUTING.md](CONTRIBUTING.md) for validation commands and the submission process.

English release notes are maintained under [docs/releases](docs/releases/). [CHANGELOG.md](CHANGELOG.md) links to each version. German UI localization remains available; this documentation change does not translate generated entity/dashboard names or change integration behavior.

## Validation and limitations

The functional baseline passed **116 Python tests**, including:

- Protocol parsing and authentication against a real local aiohttp test server.
- The real Home Assistant **2026.10.0** configuration-flow classes with a simulated FIN backend.
- Zone 1 combinations, fresh reads, overrides, concurrent writes, heating-curve boundaries, number discovery, complete binary platform setup with regular Boolean/alarm points and two heat pumps, early frontend/resource registration, actual HTTP delivery before frontend readiness, daily start counting/restart/DST/gap behavior, actual Home Assistant rendering of the seven-day table, safe automatic table insertion, compact labels, and deliberate overview cleanup.
- Dashboard save/load using native Lovelace storage, non-destructive/idempotent updates, preservation of custom graphs and layouts, backup/restore, failed-backup protection, five electricity-consumption periods, and runtime/energy views while current states are absent.
- Domestic-hot-water filtering across entity platforms and reversible visibility.
- Optional batch queries containing individual failures, detail caching, alarm history without user/audit records, energy statistics, missing-temperature handling, and dashboard generation.
- Notifications using a locally registered Home Assistant test receiver: alarm episodes, acknowledgement without repetition, persistent restart markers, destination changes, domestic-hot-water filtering, failures, concurrent checks, unload cleanup, the test button, and setup.

The bundled curve also has five Node.js tests for interpolation, preview/write separation, invalid values, error handling, and pending/read-only states, plus Chromium and WebKit interaction and responsive-layout checks in the [frontend workflow](.github/workflows/frontend.yml).

The notification tests did not send messages to a real phone. A complete running Home Assistant entry connected to the controller and hardware write operations still require live verification.

Import and syntax checks were completed for all integration modules. Replay of the original two HAR files covered **192 grids / 308 rows** and **54 unique points**. The nine additional captures covered **3,675 grids / 7,362 rows** and **103 unique point records**. All **18 supplementary queries** were matched to captured responses. The large `defs()` query was excluded because it does not contain operating data.

`point-inventory.json` contains only generic model identifiers, labels, units, and classification metadata, not installation identifiers or captured measurements. Tests and inventory files contain no captured session cookies, tokens, or installation-specific reference IDs.

To run the checks locally:

```sh
# Use Python 3.14 for the full test suite.
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
node --test tests/frontend/math.test.mjs
python3 replay_har.py /PATH/overview.har /PATH/settings.har
```

Authentication tests use invented accounts and cover login, cookies/attestation, multiple projects, expired sessions, and invalid credentials. SCRAM is also checked against the public SHA-256 test vector from RFC 7677. These are not successful hardware tests. Without `aiohttp`, local transport tests are skipped; without Home Assistant, setup tests are skipped. Home Assistant supplies `aiohttp` at runtime.

The login capture contains the login screen and its JavaScript client, but not the submitted challenge exchange. Authentication was reconstructed from that client and validated against test servers; actual installation compatibility must be confirmed. There is no automatic history backfill, locally calculated COP from power readings, climate entity, or browser control.

Implementation references: supplied HAR captures, [Haystack Zinc](https://project-haystack.org/doc/docHaystack/Zinc), [Haystack authentication](https://project-haystack.org/doc/docHaystack/Auth), [SCRAM-SHA-256 / RFC 7677](https://www.rfc-editor.org/rfc/rfc7677), [Home Assistant config flows](https://developers.home-assistant.io/docs/core/integration/config_flow/), [DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/), and [HACS integration requirements](https://www.hacs.dev/docs/publish/integration/).

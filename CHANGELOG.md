# Changelog

All published versions are experimental prereleases. Full notes are available for each version below.

## [0.17.1](docs/releases/v0.17.1.md)

- Preserve unrelated custom cards with nested entity mappings during visibility filtering, avoiding an integration setup error.

## [0.17.0](docs/releases/v0.17.0.md)

- Group heating-curve fields by water/outdoor temperature; plot current outdoor temperature with x/y guides and persistent readings.
- Add reversible heating/cooling display options while retaining measurements, history and automation IDs.
- Refresh generated cards with installation-specific outdoor sensors and use a new versioned frontend resource.

## [0.16.1](docs/releases/v0.16.1.md)

- Keep source-balance Markdown rows contiguous after template rendering and hide unavailable current-attribution rows until measurements recover.

## [0.16.0](docs/releases/v0.16.0.md)

- Replace the crowded first tab with four at-a-glance cards; group controls, temperatures and diagnostics into their own tabs.
- Consolidate source-energy absolute values and keep five consumption/source-history periods accessible through native subviews.
- Back up before migrating; preserve custom cards, graph options, daily starts, on/off history and adaptive PV controls.

## [0.15.0](docs/releases/v0.15.0.md)

- Add explicitly enabled adaptive automatic PV targets from 45 to 65 °C, bounded to the reference-tested 31-degree buffer offset.
- Prefer lower temperatures with staged PV budgets, hysteresis and timed changes; retain battery/grid/temperature guards and durable pending-write restoration.
- Expose adaptive diagnostics and verify protocol plus real HA reload/restoration.

## [0.14.1](docs/releases/v0.14.1.md)

- Avoid repeated PV-charge interruptions on small grid-meter fluctuations: default tolerance 100 W, with 60-second confirmation up to a hard 500 W limit during existing automatic priority charges.
- Keep starts/manual tests strict, retain immediate battery/temperature/freshness/reserve guards and prevent full-block renewal while import is pending.
- Preserve existing custom tolerances; expose confirmation diagnostics and configuration.

## [0.14.0](docs/releases/v0.14.0.md)

- Add explicitly estimated PV/grid/battery attribution for aggregate heat-pump electrical power, independent of PV-charge permission.
- Persist kWh totals and local-calendar daily/weekly/monthly/yearly counters, with current W values and hourly through yearly charts.
- Reuse configured PV source mappings or configure independent metering sources; omit stale/missing intervals and preserve existing dashboard cards.

## [0.13.0](docs/releases/v0.13.0.md)

- Renew healthy automatic PV charging before its block expires, without restoring and reapplying the offset.
- Add a 30-minute minimum request hold, a two-minute low-margin debounce and a persisted ten-minute automatic restart cooldown.
- Retain immediate temperature, freshness, import, discharge and battery-reserve guards; manual charges/tests retain fixed deadlines.

## [0.12.2](docs/releases/v0.12.2.md)

- Refresh measurements, native temperature report diagnostics, effective offsets and remaining duration during active PV charging.
- Retain the existing hardware-write, restoration and measurement guards.

## [0.12.1](docs/releases/v0.12.1.md)

- Observe genuine ESPHome temperature packets on the existing connection, including identical values suppressed by HA state deduplication.
- Ignore the first possible cached subscription snapshot; retain all age, disconnect, invalid-value and temperature-limit guards.
- Add native temperature packet count and report age to PV charge status diagnostics.

## [0.12.0](docs/releases/v0.12.0.md)

- Add optional heat-pump priority: count current PV battery charging and grid export, subtracting a configurable 1,000 W battery reserve.
- Apply stable start/stop thresholds to available surplus and retain discharge, freshness, temperature, lease and restoration guards.
- Add a priority-only 0–100 W grid measurement tolerance (default 50 W), plus dashboard/status budget and reserve values. Export-only mode is unchanged.
- Keep the limitations explicit: a heating offset does not regulate compressor draw or guarantee a minimum battery charging rate.

## [0.11.1](docs/releases/v0.11.1.md)

- Add an explicitly opted-in sensorless hardware charge test: manual only, maximum five minutes and at most 2 °C additional offset within verified controller bounds.
- Retain grid/battery/PV freshness and surplus guards, durable original-offset restoration and restart recovery. Normal charging still requires actual buffer temperature.
- Clearly label test operation and absent temperature cutoff in status/dashboard; reject automatic starts in test mode.

## [0.11.0](docs/releases/v0.11.0.md)

- Add an opt-in cascade buffer offset, bounded to 0–10 °C and live controller limits; preserve existing point identities.
- Add temporary PV charge actions, guarded optional automatic start and durable compare-before-restore leases with reconnect recovery.
- Add explicit signed PV/grid/battery and actual temperature sources, freshness guards, start/stop hysteresis and a temperature stop limit capped at 75 °C. This is not an absolute 75 °C buffer target.
- Prominently show active charging and restoration faults on the WP overview; add 24-hour/seven-day charge-permission history and associated measurements while preserving existing energy/runtime/custom cards.

## [0.10.1](docs/releases/v0.10.1.md)

- Recover reboot-invalidated sessions automatically using saved credentials; distinguish expired-session 403 responses from actual permission failures.
- Keep temporary login/attestation/network failures retryable instead of stopping polling with manual reauthentication.

## [0.10.0](docs/releases/v0.10.0.md)

- Fix the early extra-module/scoped-registry race; use only awaited resources on storage dashboards and guard fallback registration.
- Add power-based cycling estimates with configurable 200 W per-unit threshold, Recorder-backed absolute daily counts and an on/off band.

## [0.9.1](docs/releases/v0.9.1.md)

- Keep device identity in overview and graph labels while shortening rows within device groups. Repair labels affected by shared row objects in 0.9.0.
- Display alarm counts and error codes as whole numbers.

## [0.9.0](docs/releases/v0.9.0.md)

Use context-aware field labels and display-only rounding, separate additional settings from the overview, and consolidate read-only detail groups. Stop treating equipment operating enable as compressor cycling. Without a verified compressor-running signal, counters are unavailable with an explanation; no power-based estimation is used.

## [0.8.1](docs/releases/v0.8.1.md)

Fix duplicate-power selection with multipart installation IDs found during live verification. Use a fresh per-boot module URL to recover cached early import failures. Attempt dashboard upgrades shortly after Cascade platforms load instead of waiting solely for unrelated integrations to finish starting.

## [0.8.0](docs/releases/v0.8.0.md)

Refresh generated live cards with short labels, dynamic unknown/unavailable filtering and canonical power readings. Add instantaneous COP, a Momentanverbrauch card in Energy, and outdoor temperature to power history. Safely upgrade recognized existing dashboards and use a fresh heating-curve module URL after confirming a cached import failure in the desktop client.

## [0.7.1](docs/releases/v0.7.1.md)

Display absolute observed start counts for today, yesterday and five earlier dates in a native dashboard table. Reconstruct seven local calendar days from Recorder and add the table automatically to recognized existing runtime views, with a backup and without replacing other cards. Missing history stays missing.

## [0.7.0](docs/releases/v0.7.0.md)

Absolute daily observed start counts from Recorder, compact default labels, reduced duplicate curve controls/runtime diagnostics, and removal of legacy unknown Site Info counters from energy overview cards. Fix HTTP delivery when frontend startup is late and use a versioned curve module filename. Added actual HTTP/startup and WebKit checks.

## [0.6.2](docs/releases/v0.6.2.md)

Fix binary sensor platform initialization (`row` NameError) so running-state entities can load for native on/off timelines. Register the heating-curve module early and persist/migrate dashboard resources to address missing custom-element errors. Existing cards and entity IDs are retained.

## [0.6.1](docs/releases/v0.6.1.md)

Repair missing energy and runtime dashboard content. Restore hourly/daily/weekly/monthly/yearly electricity-consumption graphs. Add non-destructive dashboard updates, automatic configuration backups, and a restore action. Fix graph discovery when current states are temporarily unavailable.

## [0.6.0](docs/releases/v0.6.0.md)

Zone 1 heating-curve controls and a bundled responsive curve card with immediate local preview, explicit Apply, and pointer/touch readout. Added control boundaries, frontend, and browser tests.

## [0.5.2](docs/releases/v0.5.2.md)

HACS catalog submission preparation: MIT license, original integration icons, active HACS/Hassfest/test workflow, and contributor guidance.

## [0.5.1](docs/releases/v0.5.1.md)

Complete English release documentation, including the README, changelog, versioned release notes, dashboard action help, and generic point-inventory labels. No application logic changes.

## [0.5.0](docs/releases/v0.5.0.md)

Phone alarm notifications with iPhone support, optional time-sensitive delivery, approximately five-second alarm checks, persistent deduplication, and a test button.

## [0.4.0](docs/releases/v0.4.0.md)

Additional equipment diagnostics, energy counters and statistics, alarm history, and energy/alarm dashboard views. Expanded domestic-hot-water filtering and missing-temperature handling.

## [0.3.1](docs/releases/v0.3.1.md)

Optional domestic-hot-water visibility with reversible entity and native dashboard filtering.

## [0.3.0](docs/releases/v0.3.0.md)

Clean display names, a dedicated Zone 1 on/off switch, and a dashboard helper that uses registered entity IDs.

## [0.2.0](docs/releases/v0.2.0.md)

FIN username/password authentication, automatic session renewal, project selection, and reconfiguration of existing cookie-based entries.

## [0.1.0](docs/releases/v0.1.0.md)

Initial local FIN/Haystack integration with sensors, equipment status, cookie authentication, and optional Set Default controls.

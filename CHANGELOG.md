# Changelog

All published versions are experimental prereleases. Full notes are available for each version below.

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

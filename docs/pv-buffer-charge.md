# Temporary PV buffer charging

Available in **0.11.0**, disabled by default. This is a temporary controller offset with a persisted restoration record, not a separate thermostat or an immersion-heater controller.

## Supported temperature control

The verified cascade buffer point is `_equip:buffer_point:tBufferTank`. Captured metadata advertises **0–10 °C**. This is an offset relative to the zone demand. A 31 °C zone demand and a 10 °C offset cannot command a 75 °C buffer target. The integration does not edit the heating curve, zone setpoint, SG Ready, or similarly named heat-pump feedback points to work around that limit.

The configurable **buffer temperature stop limit** is capped at **75 °C**. It is an early-stop guard, not an absolute target and not evidence that an installation can operate at that temperature. Use a lower limit wherever the heat pump, buffer, heating circuit or mixing controls require one. A separate writable absolute buffer target has not been verified. In particular, `−78 °C` is invalid buffer feedback and blocks charging.

## Configure

1. Update through HACS and restart Home Assistant.
2. Open **Settings → Devices & services → Panasonic Cascade / Smart Edge → Configure**. Enable experimental controls, select **Configure temporary PV buffer charging**, and submit.
3. Select four actual measurement sources: signed grid export/import, signed battery discharge/charge, PV production, and the buffer temperature at the hottest monitored point. Power sources must provide W or kW; the temperature source must provide °C.
4. Set the sign conventions explicitly. Positive grid values can mean either export or import depending on the source. Similarly, configure whether positive battery values mean discharge. Do not infer PV surplus from an unverified power sensor or from battery-supported inverter output.
5. Set start/stop export thresholds, stable-export time, maximum measurement age, temporary offset, maximum duration, and temperature stop limit. Defaults: start 1500 W, stop below 500 W, stable export 120 s, age 60 s, offset 5 °C, duration 30 minutes, temperature stop limit 75 °C. A raised offset must be greater than the current offset and remain within the live controller bounds.
6. Confirm that the source signs, hottest-point temperature feedback, permitted temperature and mixing circuit have been checked. Enable temporary charging only after this verification. **Automatic start is a separate option and defaults to off.**

Sources must actually update often enough. Increasing the maximum age does not make a slow integration fast feedback. Missing, stale, non-finite or incorrectly dimensioned measurements block charging; they are never replaced with zero. No PV production, grid import, battery discharge above 100 W, leaving the cascade heating mode, or reaching the temperature limit ends a charge. Export falling below the stop threshold ends it as well. The conditions are checked on source state changes and at least every 15 seconds; a dedicated deadline callback also requests restoration at expiry. Physical device/network delays remain possible.

## Start and stop

The cascade must already be in heating mode. A charge raises the buffer offset; it does not enable a disabled heating zone or force a compressor to run.

Use **PV-Pufferladung starten** / **PV-Pufferladung beenden** on the device or dashboard. The start action still requires stable verified PV export. With automatic start enabled, a fresh stable-export interval starts a charge; after stopping, a new stable interval is required before another charge can start. Concurrent starts cannot replace or extend a lease.

Actions are also available for HA automations:

```yaml
action: panasonic_cascade.start_buffer_charge
data:
  entry_id: YOUR_CASCADE_CONFIG_ENTRY_ID
  offset: 7
  duration_minutes: 30
```

`offset` is the temporary absolute offset default, not an increment added to the original value. Both fields are optional and use the configured defaults when omitted. Duration is limited to 1–120 minutes and offset to 1–10 °C. To stop:

```yaml
action: panasonic_cascade.stop_buffer_charge
data:
  entry_id: YOUR_CASCADE_CONFIG_ENTRY_ID
```

**Puffer · Zonenversatz (dauerhaft)** remains an advanced, persistent default control. Use the temporary charge actions for PV charging. Manual offset writes through this integration are blocked while a charge or unresolved restoration exists.

## Dashboard and history

The WP overview shows a prominent **PV-Pufferladung aktiv** card during a confirmed charge, including remaining time and requested offset. A separate prominent warning appears for pending restoration or an external-change conflict. An on/off history band shows the confirmed charge permission for 24 hours. A **PV-Pufferladung** view adds seven-day permission history, buffer temperature and PV/grid/battery histories when configured.

This band records the integration's charge permission, not physical compressor activity. It becomes unknown when restoration or controller feedback is uncertain. Actual compressor/cycling graphs stay in **Laufzeiten & Taktung**. History begins after installation and requires Recorder to include the charge binary sensor. Previous controller operation cannot be reconstructed as PV charge history.

Recognized integration-generated dashboards are upgraded with a backup and retain existing energy/runtime/custom cards. For other storage dashboards, use `panasonic_cascade.populate_dashboard` with `url_path` and `update: true`; do not enable replacement. Status, start/stop buttons and detailed values are also available under **Einstellungen**. The status exposes baseline/requested/effective offset, zone target, buffer target, actual buffer temperature, configured limit, expiry, remaining minutes and restoration faults.

## Restoration and external changes

Before the first device write, the integration stores the point identity, original nonzero-or-zero default, temporary default, absolute expiry and an applying state in HA storage. It confirms the effective temporary offset after writing. An ambiguous write is not blindly replayed; the integration reads the point and requests restoration instead.

Stopping, expiry, loss of surplus/feedback, or disabling charging requests restoration of the recorded original default. Restart/reload restores any stored lease before considering a new charge, even if its original deadline has not expired. Failed restoration stays pending and is retried when communication returns. Turning off the experimental-controls option does not discard an already-owned restoration obligation.

Restoration compares the fresh default against the value owned by the lease. If an operator changed the default independently, the integration preserves that change, records a conflict and creates a persistent HA notification. After checking the controller, use `panasonic_cascade.acknowledge_buffer_charge_conflict` with `entry_id` to clear the conflict without writing to the controller. If a higher-priority schedule/override is active, restoring only the original **default** leaves that higher-priority setting untouched and prevents a latent raised default from activating later.

A software deadline **cannot guarantee rollback while HA is stopped or the controller is unreachable**. The offset is a persistent controller default. Do not disable/remove the integration while a restoration is pending. Controller-side limits, reliable temperature feedback and verified hydraulic operation remain necessary before unattended use.

## Verification scope

Protocol, HA entity/configuration/service tests and fault-injection tests simulate writes. They cover persisted baselines, expiry, reload/restart, nonzero restoration, ambiguous transport failures, retries, external changes, overrides, stale/invalid measurements, stable-export hysteresis, 75 °C stop protection, history semantics and preservation of existing dashboards. No physical heating command or commissioning test is performed by the release process.

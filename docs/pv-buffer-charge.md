# Temporary PV buffer charging

Available in **0.11.0**, disabled by default. This is a temporary controller offset with a persisted restoration record, not a separate thermostat or an immersion-heater controller.

## Continuous automatic charging and cycling protection (0.13.0)

Automatic starts create a renewable charge request. Five minutes before the current block ends, fresh valid measurements and surplus at or above the stop threshold allow another block to be added. The default block is 30 minutes; automatic blocks cannot be shorter than the configured minimum hold. The original offset stays applied throughout: renewal only saves the new recovery deadline, with no restore/reapply commands. Repeated renewals can continue while conditions remain suitable; this is reactive control, not a weather forecast or a guarantee of the next 30 minutes of PV production.

Defaults, configurable in the PV charge options:

- **Minimum request hold: 30 minutes.** During this period, a small nonnegative surplus margin below the stop threshold does not by itself end automatic charging.
- **Low-margin delay: 120 seconds.** After the hold, a continuous low margin must last this long to end charging. Recovery resets the timer. A brief dip at a block boundary receives only the remaining debounce time, not a fresh full block.
- **Automatic restart cooldown: 10 minutes.** After restoration completes, another automatic start must wait for the persisted cooldown and then a new full stable-surplus interval. Reloading/restarting HA does not bypass it. Explicit manual starts remain available and use their fixed deadline.

**The hold is subordinate to all existing guards.** Temperature limit, missing/stale/invalid feedback, PV loss, grid import above the hard limit or confirmed sustained import, battery discharge, a negative available budget (battery reserve no longer covered), loss of heating mode/controller feedback, external offset changes, disabling charging or manual stop still request immediate restoration. No additional battery-discharge allowance is introduced. Version 0.14.1 adds only the bounded grid-import handling described below; it never forces a minimum compressor runtime. This can shorten a charge during a real power deficit.

The hold starts when the integration raises the request; it is **not a measured or guaranteed 30-minute compressor runtime**. Panasonic retains control of its compressors and may stop them earlier. Both units' existing power-based cycling estimates remain estimates, separate from the charge request. The dashboard shows the current renewable block, remaining request hold and automatic restart cooldown. Manual charge actions (even with automatic mode enabled) and sensorless hardware tests are never automatically extended. Switching automatic mode off prevents further renewals; the current charge keeps its already stored deadline and the normal guards.

## Supported temperature control

The verified cascade buffer point is `_equip:buffer_point:tBufferTank`. Captured metadata advertises **0–10 °C**. This is an offset relative to the zone demand. A 31 °C zone demand and a 10 °C offset cannot command a 75 °C buffer target. The integration does not edit the heating curve, zone setpoint, SG Ready, or similarly named heat-pump feedback points. Fixed/manual mode respects the advertised range; opt-in adaptive automatic mode uses the separately bounded extension described below.

The configurable **buffer temperature stop limit** is capped at **75 °C** in fixed mode and **65 °C** in adaptive mode. It is an early-stop guard, not an absolute target and not evidence that an installation can operate at that temperature. Use a lower limit wherever the heat pump, buffer, heating circuit or mixing controls require one. A separate writable absolute buffer target has not been verified. In particular, `−78 °C` is invalid buffer feedback and blocks charging.

## Configure

1. Update through HACS and restart Home Assistant.
2. Open **Settings → Devices & services → Panasonic Cascade / Smart Edge → Configure**. Enable experimental controls, select **Configure temporary PV buffer charging**, and submit.
3. Select four actual measurement sources: signed grid export/import, signed battery discharge/charge, PV production, and the buffer temperature at the hottest monitored point. Power sources must provide W or kW; the temperature source must provide °C.
4. Set the sign conventions explicitly. Positive grid values can mean either export or import depending on the source. Similarly, configure whether positive battery values mean discharge. Do not infer PV surplus from an unverified power sensor or from battery-supported inverter output.
5. Set start/stop export thresholds, stable-export time, maximum measurement age, temporary offset, manual duration/automatic charge-block length, and temperature stop limit. Defaults: start 1500 W, stop below 500 W, stable export 120 s, age 60 s, offset 5 °C, duration 30 minutes, temperature stop limit 75 °C. In fixed/manual mode a raised offset must be greater than the current offset and remain within the live controller bounds. Adaptive mode requires an explicit additional opt-in and a 40–65 °C stop ceiling.
6. Confirm that the source signs, hottest-point temperature feedback, permitted temperature and mixing circuit have been checked. Enable temporary charging only after this verification. **Automatic start is a separate option and defaults to off.**

Sources must actually update often enough. Increasing the maximum age does not make a slow integration fast feedback. Missing, stale, non-finite or incorrectly dimensioned measurements block charging; they are never replaced with zero. No PV production, disallowed grid import (see below), battery discharge above 100 W, leaving the cascade heating mode, or reaching the temperature limit ends a charge. Manual charging also ends immediately when surplus falls below its stop threshold; automatic charging uses the hold/debounce policy above. The conditions are checked on source state changes and at least every 15 seconds; a dedicated deadline callback also checks whether restoration or an automatic renewal is required at expiry. Physical device/network delays remain possible.

## Heat-pump priority over battery charging (0.12.0)

By default the controller still uses actual grid export only. To let the heat pump use PV power currently absorbed by the battery, opt into **Heat-pump priority**. Set **PV power reserved for battery charging**; the default is **1,000 W**. Existing EMMA source/sign mappings are retained.

With normalized positive export and positive battery discharge:

`available = min(PV production, grid export − battery discharge) − battery reserve`

Battery charging has a negative discharge value, so it contributes to available surplus. A small discharge is deducted and discharge above 100 W still blocks/stops charging. With 9,255 W PV, 7,468 W battery charging and 7 W grid import, available surplus is **6,461 W** after a 1,000 W reserve. If the battery is full, sufficient grid export can supply the budget instead. The budget never exceeds measured PV production before the reserve.

The existing 1,500 W start and 500 W stop thresholds now apply to this available surplus, after the reserve. Start requires the full stable interval. Loss of available surplus requests original-offset restoration. No battery settings, charge limits, operating modes or grid export limits are changed.

### Grid-meter fluctuations and repeated charging interruptions (0.14.1)

The installation audit found eight charge interruptions on just **53–67 W** import while the battery was still charging at several kW. A strict 50 W stop could withdraw the raised demand minutes after starting. The charging-permission band and the separate power-based WP bands showed closely timed starts/stops; permission itself is not compressor status.

The priority-only **small grid-import tolerance** now defaults to **100 W**, configurable 0–100 W. Existing saved tolerances remain unchanged; reference installations previously using 50 W should explicitly set 100 W if desired.

Only an **already confirmed automatic charge**, with heat-pump priority enabled and valid temperature monitoring, receives bounded confirmation above that tolerance:

- Import above the small tolerance and **up to 500 W** (configurable hard threshold 100–500 W) must remain continuously present for **60 seconds** (configurable 15–120 seconds) before restoration is requested. Returning to or below the small tolerance resets this timer.
- Import **above the hard threshold** requests immediate restoration. Battery discharge above 100 W, an exhausted battery reserve, lost/invalid/stale measurements, PV loss, temperature limit, controller/mode faults and manual stop still override the hold immediately.
- No additional full charge block is renewed while grid import is under confirmation. At a block boundary, only the remaining confirmation time may be granted. Normal uninterrupted renewal resumes after recovery.
- New starts, explicit manual charges and sensorless hardware tests remain strict at the configured small tolerance. Export-only mode retains its strict no-import behavior.

This deliberately allows a small amount of short-lived grid energy. At the default hard limit, one 60-second confirmation window is at most about **8.3 Wh** before measurement/scheduling/network delays. It is not an unlimited cloud bridge, a controller-side timeout, or a guarantee of a 30-minute compressor run. The ten-minute restart cooldown and subsequent stable-surplus interval remain in force after a real stop. HA restart restores the previous offset and does not resume an unexpired confirmation window.

Status attributes expose the configured tolerance/hard limit and remaining confirmation seconds. Meter readings remain visible during a bounded confirmation; they are not replaced with zero or falsified as export. Source-energy accounting continues to record any actual attributable grid consumption independently.

**This is a reactive heating-offset controller, not a power allocator.** It cannot modulate compressor electrical demand, guarantee exactly 1,000 W of battery charging, or prevent every brief import/discharge transient. It withdraws its offset when measurements fail the conditions; the original heating demand may still keep the heat pump running. It does not change battery priority in the inverter itself. Status/dashboard expose the calculated available surplus and configured battery reserve. Begin with a modest offset and verify actual power flows before relying on this priority policy.

## Explicit sensorless hardware charge test (0.11.1)

For a supervised commissioning test before a buffer sensor is installed, explicitly select **Charge test WITHOUT buffer sensor** in the PV options. This is a real heat-pump command, not a simulation. Leave the temperature source empty; no artificial temperature is generated. The temperature cutoff is unavailable in this mode, even if a temperature source remains selected. Normal charging still requires a valid actual buffer temperature.

- Enable experimental controls and temporary PV charging, select the test checkbox and confirm the available power readings, signs and mixing circuit. Keep **automatic start off**; the form rejects automatic operation with this test.
- Start manually with the ordinary charge button or action, only while supervising the installation. Stable PV export, fresh signed grid/battery/PV measurements, no grid import or significant battery discharge, heating mode and writable controller feedback remain required.
- A test raises the original offset by **at most 2 °C**, respecting the live upper bound and the overall 10 °C limit. The ordinary offset setting/action argument is not applied in this mode. The duration is the requested/configured duration capped at **five minutes**. Repeated/overlapping starts cannot extend a running test.
- The original default is stored before writing and restored on stop, guard failure, expiry or restart/reload. Restoration failures remain pending and retry on reconnect. HA/network downtime can delay restoration beyond five minutes; this is not a controller-side timeout.
- Status explicitly reads **Ladetest ohne Temperaturüberwachung**; the overview warns that temperature protection is absent. The status stores `temperature_unmonitored_test` during the lease and Recorder retains it with the on/off band. No inferred temperature or claimed active temperature limit is displayed.
- Once the real sensor is installed, select and verify it, **clear the sensorless test checkbox**, then use normal temperature-monitored charging. The test checkbox defaults to off on new installations.

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

### ESPHome temperature report freshness

Since 0.12.1, matching real packets from the configured ESPHome temperature sensor count even when HA suppresses identical sensor states. The existing connection is observed without reading/replaying its cache or modifying the source entity. The first possible subscription snapshot is ignored. Silence, missing/invalid measurements and disconnection still block charging; no freshness limit is increased. Status attributes show the native packet count and report age. Other source platforms continue to use HA `last_reported`. Firmware that does not publish regular temperature samples still needs its own reporting configuration corrected.


## Adaptive automatic PV targets (0.15.0)

Enable **Use adaptive PV targets up to 65 °C** in the PV options, with automatic charging, verified source mappings and a real buffer probe. This setting is disabled by default. Manual actions and sensorless tests retain their original fixed-offset limits. Set a suitable temperature stop ceiling no higher than 65 °C; never treat the buffer vessel rating as the limit for the connected heating circuit.

The controller advertises a 10-degree maximum offset. An authorized brief reference-installation probe nevertheless confirmed offsets up to 31 degrees, with a 34 °C zone demand and calculated buffer targets up to 65 °C. Adaptive mode deliberately exceeds that metadata, only for this isolated buffer point and the verified metadata profile. This is experimental and does not constitute manufacturer approval or a sustained high-temperature operating test.

| Buffer target | Required PV budget after battery reserve, including existing WP consumption |
| --- | --- |
| 45 °C | 3,000 W |
| 50 °C | 4,500 W |
| 55 °C | 6,000 W |
| 60 °C | 8,000 W |
| 65 °C | 10,000 W |

The configured start threshold and stable-start dwell still apply. Start at the **lowest** eligible stage. Raise at most one stage after five minutes above the next budget plus 500 W. Lower at most one stage after two minutes below the current budget minus 750 W. Allow at least ten minutes between temperature-stage changes. These thresholds favour lower temperatures; they do not measure or mathematically optimise COP. The original immediate grid/battery/reserve/temperature/freshness guards take priority over these stage timers.

In priority mode, stage budget is `min(PV minus battery reserve, available surplus plus total WP electrical power)`. Existing WP draw is included so its own consumption does not masquerade as disappearing PV. Source accounting is unchanged. Missing, stale or invalid WP electrical feedback blocks adaptive charging rather than assuming zero.

The offset equals selected target minus fresh zone demand, at most **31 degrees**. Consequently, 65 °C is available only where that demand makes it reachable within the tested envelope; lower zone demand can limit charging to a lower stage. Feedback must confirm both effective offset and actual calculated buffer target after every write. A zone-demand change is compensated without changing the selected PV temperature stage. Unexpected feedback, overshooting targets or leaving the verified envelope ends the boost.

Original defaults and pending adjustments are saved before writes. Stops and restart/reload restore the original offset; ambiguous writes are not repeated and independent changes are preserved. The normal permanent-offset number remains limited to 10 degrees. This feature does not bypass the device's physical safety controls or alter zone demand, heating curves, SG Ready or mode selectors.

Diagnostics include `adaptive_active`, `adaptive_target`, `adaptive_next_target` and `adaptive_budget_w`. Regenerate the dashboard only if you want these extra diagnostic rows; existing cards are retained. Existing charge history continues to record the request. A software temperature ceiling uses the selected sensor (for example buffer middle), normal sampling and device/network response time; it cannot guarantee an exact hottest-tank temperature or prevent every overshoot.

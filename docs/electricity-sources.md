# Heat-pump electricity-source accounting (0.14.0)

The Energy dashboard adds **WP · Stromherkunft**, with three explicitly **estimated** categories: PV, grid and battery. The scope is the **sum of all heat pumps in the installation**, including their reported standby consumption. No direct electrical-source submeter exists at the heat pumps: electricity provenance cannot be uniquely measured from whole-house grid/PV/battery sensors. This feature performs an allocation, not billing-grade source measurement.

## Measurements and allocation rule

Use the controller's explicit total consumed electrical power (W/kW). If it is absent, use the sum of complete per-unit consumed-power summaries; never add the total and per-unit readings together, use thermal output, or mix heating/cooling energy registers. All household inputs must be finite, fresh W/kW readings. A materially inconsistent balance (WP demand exceeds household supply by more than 100 W or 10% of WP draw) creates a gap, not fabricated data.

Normalize grid power to positive export and battery power to positive discharge. The explicit PV-first allocation rule is:

```
PV available to household = max(0, PV production - grid export - battery charging)
grid supply = max(0, grid import)
battery supply = max(0, battery discharge)
WP share of each source = WP electrical power * source supply / sum(source supplies)
```

Export and battery charging are subtracted only when positive in their respective direction. The remaining source pool is allocated proportionally to WP demand. This is one transparent allocation convention; it cannot prove which source physically supplied a particular load. Simultaneous grid charging, DC/inverter losses, differently sampled meters and control delays increase uncertainty. **Battery discharge remains battery**, even if much of the stored energy was originally solar; no PV origin is claimed without provenance tracking.

## Configuration

When the installation already has PV/grid/battery source mappings in the PV-charge options, accounting reuses these mappings and sign conventions automatically. It does not require PV charging, experimental controls, a temperature sensor, sunlight, a battery reserve or a heating permission. It runs at night and while the charging automation is disabled.

Under **Settings → Devices & services → Panasonic Cascade / Smart Edge → Configure**, use **Record WP electricity attribution to PV/grid/battery** to enable/disable it. Select **Configure electricity-source measurements** to choose independent PV, signed grid and signed battery power sensors, signs and measurement age (default 90 seconds). Independent `energy_*` settings take precedence over inherited `pv_charge_*` mappings and never change the charge automation. With no battery, an explicit valid zero-discharge/charge source is needed; a missing measurement is never assumed zero.

## Absolute values and charts

- Current attributed source power in W, with a 24-hour history.
- Separate kWh counters for today, this calendar week (Monday start), this calendar month and this calendar year, plus totals since setup.
- Hourly, daily, weekly, monthly and yearly bar charts based exclusively on the three cumulative kWh totals and Recorder long-term statistics. Calendar counters are not added to totals, avoiding double counting.
- Compact PV/Netz/Batterie labels; existing energy/runtime/custom dashboard cards are retained. Recognized generated dashboards upgrade with a backup. Other storage dashboards can run `panasonic_cascade.populate_dashboard` with `update: true`.

Counters begin with actual valid observations after installation; historical power is not reconstructed or backfilled. Initially there may be no chart bars until Recorder has collected statistics. Week/month/year values are partial if recording began during that period. Measurements are integrated as left-held W over seconds into kWh. Source events, controller updates and a 15-second timer refresh the allocation. Intervals over 90 seconds, invalid/stale data and HA downtime are omitted. A valid zero remains zero; a calendar period with no integrated observations is unavailable rather than displayed as a measured zero.

Totals and calendar counters are saved periodically and flushed on clean unload/shutdown; abrupt power loss can lose the most recent unsaved interval. Restart restores counts but never extrapolates over downtime. Midnight/calendar boundaries and DST use the HA time zone. Sensor attributes identify the method, source entities, start timestamp, measurement problems and observed seconds per calendar period. **Observed seconds are coverage, not compressor running time.** The calculation is read-only and sends no heat-pump, battery or inverter commands.

## Metering cascades (0.18.0)

Select the measurement boundary in the electricity-source options. **Shared** means the signed grid meter includes household and WP loads. **Cascade** means EMMA measures an inner house/PV branch and the WP is upstream of it, behind the outer/main meter. In cascade mode, WP receives at most `min(WP power, positive inner-branch export)` from that branch; the remaining WP power is grid supplied. An inner-branch import must not be used as a limit on WP demand. Mixed export provenance is proportional to PV net of charging and battery discharge; this is an allocation assumption, not separate source metering.

Counter-based consumption sensors sum reset-aware Recorder statistic changes for the installation's electrical-energy registers, normalized to kWh. Missing statistical sources remain unavailable. They do not depend on PV/battery data. Statistics cover completed intervals; the dashboard's unmatched difference is a reconciliation value, not an additional physical meter. It includes time before corrected attribution began, data gaps and differences in counter/integration resolution.

Corrected attribution starts new entity IDs and ledger files keyed by measurement topology, sensors and signs. Legacy attribution remains archived and is excluded from generated current/history cards. Personal automations using legacy source IDs require migration. Previous incorrect shares are not backfilled or relabelled. Source attributes include the method, accounting revision, topology, recording start, measurement issue and observed seconds.

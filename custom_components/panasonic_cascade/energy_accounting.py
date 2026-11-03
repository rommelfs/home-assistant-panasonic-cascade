"""Estimated source allocation and gap-aware local-calendar energy accounting."""
from datetime import datetime, timedelta
from copy import deepcopy
import math

SOURCES = ('pv', 'grid', 'battery')
PERIODS = ('day', 'week', 'month', 'year')


def allocate(wp, pv, export, battery, topology="shared"):
    """PV-first house balance, then proportional WP attribution; not a submeter.

    export is positive toward grid; battery is positive when discharging.
    Battery provenance is deliberately never relabelled as PV or grid.
    """
    if any(isinstance(v, bool) or not math.isfinite(v) for v in (wp, pv, export, battery)) or min(wp, pv) < 0:
        raise ValueError('Invalid power measurement')
    if topology not in ('shared', 'cascade'):
        raise ValueError('Unknown metering topology')
    if topology == 'cascade':
        # EMMA measures the inner house/PV branch; WP is on the outer branch.
        # Only net export from the inner branch reaches the WP bus.
        available_pv = max(0, pv - max(0, -battery))
        available_battery = max(0, battery)
        supply = available_pv + available_battery
        exported = max(0, export)
        if exported > supply + max(100, exported * .1):
            raise ValueError('House-branch export exceeds measured PV/battery supply')
        used = min(wp, exported)
        if used and supply <= 0:
            raise ValueError('Export provenance unavailable')
        # Provenance of mixed export is an explicit proportional estimate.
        pv_share = used * available_pv / supply if supply else 0.0
        battery_share = used * available_battery / supply if supply else 0.0
        return {'pv': pv_share, 'grid': wp - used, 'battery': battery_share}
    supply = {'pv': max(0, pv - max(0, export) - max(0, -battery)),
              'grid': max(0, -export), 'battery': max(0, battery)}
    total = sum(supply.values())
    if wp > total + max(100, wp * .1):
        raise ValueError('WP demand exceeds measured household supply; check timing and sources')
    if wp == 0:
        return dict.fromkeys(SOURCES, 0.0)
    if total <= 0:
        raise ValueError('No attributable household supply')
    return {key: wp * raw / total for key, raw in supply.items()}


def period_keys(stamp, tz):
    date = datetime.fromtimestamp(stamp, tz).date()
    week = date.isocalendar()
    return {'day': date.isoformat(), 'week': f'{week.year}-W{week.week:02}',
            'month': date.strftime('%Y-%m'), 'year': str(date.year)}


class Ledger:
    """Integrate valid left-held W into kWh; never bridge restart/invalid gaps."""
    def __init__(self, tz, saved=None):
        saved = saved or {}
        self.tz = tz
        self.total = {key: float(saved.get('total', {}).get(key, 0)) for key in SOURCES}
        self.periods = saved.get('periods', {})
        self.started = saved.get('started')
        self.last = None

    def roll(self, stamp):
        for period, key in period_keys(stamp, self.tz).items():
            if self.periods.get(period, {}).get('key') != key:
                self.periods[period] = {'key': key, 'energy': dict.fromkeys(SOURCES, 0.0), 'observed_seconds': 0.0}

    def update(self, stamp, powers):
        if self.started is None and powers is not None:
            self.started = stamp
        if self.last and powers is not None:
            previous, watts = self.last
            # Bounded timer interval; a missed callback is a data gap, not a forecast.
            if 0 < stamp - previous <= 90:
                cursor = previous
                while cursor < stamp:
                    local = datetime.fromtimestamp(cursor, self.tz)
                    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), self.tz).timestamp()
                    end = min(stamp, midnight)
                    self.roll(cursor)
                    seconds = end - cursor
                    for source in SOURCES:
                        delta = watts[source] * seconds / 3_600_000
                        self.total[source] += delta
                        for record in self.periods.values():
                            record['energy'][source] += delta
                    for record in self.periods.values():
                        record['observed_seconds'] += seconds
                    cursor = end
        self.roll(stamp)
        self.last = (stamp, powers) if powers is not None else None

    def dump(self):
        return deepcopy({'total': self.total, 'periods': self.periods, 'started': self.started})

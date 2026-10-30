"""Instantaneous COP from same-snapshot, explicitly unit-tagged power pairs."""
import math
from .diagnostics import synthetic
from .model import model_key, name, unit
from .zinc import Number, reference


def watts(row):
    if not row or row.get('curStatus') not in (None, 'ok'):
        return None
    raw = row.get('curVal')
    units = unit(row)
    if not isinstance(raw, Number) or units not in ('W', 'kW') or not math.isfinite(raw.value) or raw.value < 0:
        return None
    return raw.value * (1000 if units == 'kW' else 1)


def add_calculated_cop(rows, site_id):
    """Keep stable unknown placeholders; never divide by zero or mix operating modes."""
    targets = [(None, 'Anlage')]
    targets += [(ident, name(row)) for ident,row in list(rows.items()) if model_key(row) == 'heatPump']
    for parent,label in targets:
        prefix = f'summary:unit:{parent}:' if parent else 'summary:'
        sources = [prefix+'generatedPower', prefix+'consumedPower']
        output, consumed = [watts(rows.get(key)) for key in sources]
        # A complete heating-only pair is an alternative when optional unit summaries fail.
        if parent and (output is None or consumed is None):
            points = {model_key(row):ident for ident,row in rows.items()
                      if reference(row.get('heatPumpRef')) == parent or reference(row.get('equipRef')) == parent}
            pair = [points.get('heatModeEnergyGeneration'), points.get('heatModeEnergyConsumption')]
            output, consumed = [watts(rows.get(key)) for key in pair]
            sources = pair
        ratio = round(output/consumed, 2) if output is not None and consumed is not None and consumed > 0 else None
        ident = prefix+'calculatedCop'
        rows[ident] = synthetic(ident, label+' – COP aktuell', Number(ratio) if ratio is not None else None, site_id, parent)
        rows[ident]['attributes'] = {'calculation':'thermal power / electrical power (same snapshot)',
                                     'source_points': [key for key in sources if key]}

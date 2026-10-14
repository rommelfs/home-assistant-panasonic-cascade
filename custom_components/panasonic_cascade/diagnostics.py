"""Read-only FIN summaries and alarm presentation observed in the web interface."""
from datetime import datetime
import math

from .model import is_dhw, model_key, name
from .zinc import MARKER, Number, Ref, reference, value

PARAMETERS = {
    'zone1MaxSetpointTemperature': 'Zone 1 – Maximale Solltemperatur',
    'zone2MaxSetpointTemperature': 'Zone 2 – Maximale Solltemperatur',
    'zone1Sensors': 'Zone 1 – Sensortyp (Code)', 'zone2Sensors': 'Zone 2 – Sensortyp (Code)',
    'heatModeWaterTemperatureSensor': 'Heizen – Regelungstyp (Code)',
    'coolModeWaterTemperatureSensor': 'Kühlen – Regelungstyp (Code)',
    'numberZones': 'Konfigurierte Zonen', 'tankConnection': 'Warmwasserspeicher angeschlossen',
    'bufferTankConnection': 'Heizpuffer angeschlossen',
    'oduModel': 'Außengeräte-Modellcode', 'iduModel': 'Innengeräte-Modellcode',
    'modelSeriesSelection': 'Modellserie (Code)', 'outdoorType': 'Außengerätetyp (Code)',
    'capacityRank': 'Nennleistung',
}


def synthetic(ident, label, raw, site_id, parent=None, kind='Number', unit='', diagnostic=False):
    valid = (isinstance(raw, Number) and math.isfinite(raw.value)) if kind == 'Number' else (
        type(raw) is bool if kind == 'Bool' else isinstance(raw, str))
    row = {'id': Ref(ident, label), 'point':MARKER, 'kind':kind, 'curVal':raw if valid else None,
           'curStatus':'ok' if valid else 'fault', 'siteRef':Ref(site_id), 'unit':unit}
    if isinstance(raw, Number): row['unit'] = raw.unit or unit
    if parent: row['equipRef'] = Ref(parent)
    if diagnostic: row['diagnostic'] = MARKER
    return row


def queries(site_id, rows, include_details):
    """Descriptors keep each returned grid associated with its exact request."""
    specs = []
    for key, label, path, kind in (
        ('connectedUnits','Verbundene Wärmepumpen','/plantOverview/units/overview/connectedUnits','Number'),
        ('quietModeEnabled','Leisemodus aktiv','/plantOverview/units/advanced/quietModeEnabled','Bool'),
    ):
        specs.append((key, label, None, kind, '', f'panEval(`{path}`, {{siteId:@{site_id}}})', 'scalar'))
    specs.append(('activeAlarms','Aktive Alarme',None,'Number','',
                  f'panEval(`/alarmList/table/alarms`, {{target:@{site_id}}})','alarms'))
    if include_details:
        specs.append(('alarmHistory','Alarmverlauf – Letzte 12 Monate',None,'Number','',
                      f'panEval(`/alarmHistory/table/alarms`, {{target:@{site_id},dateSpan:"pastYear"}})','history'))
    for ident, row in rows.items():
        if model_key(row) != 'heatPump' or row.get('equip') is not MARKER:
            continue
        label = name(row)
        for key, title, path, kind, unit in (
            ('generatedPower','Thermische Leistung','powerGeneration','Number','kW'),
            ('consumedPower','Elektrische Leistung','powerConsumption','Number','kW'),
            ('minWorkingHours','Betriebsstunden – Minimum','plantMinWorkingHours','Number','h'),
            ('maxWorkingHours','Betriebsstunden – Maximum','plantMaxWorkingHours','Number','h'),
            ('errorCodeText','Fehlercode (Regleranzeige)','errorCode','Str',''),
        ):
            area = 'alarm' if key == 'errorCodeText' else 'power'
            specs.append((f'unit:{ident}:{key}', f'{label} – {title}', ident, kind, unit,
                          f'panEval(`/unitsView/heatPump/{area}/{path}`, {{heatPumpId:@{ident}}})', 'scalar'))
        if include_details:
            for area in ('parameters','properties'):
                specs.append((f'unit:{ident}:{area}',label,ident,None,'',
                              f'panEval(`/unitsView/heatPump/control/{area}`, {{heatPumpId:@{ident}}})','details'))
    return specs


def timestamp(raw):
    if not isinstance(raw, str): return None
    try:
        parsed = datetime.fromisoformat(raw.split(' ', 1)[0])
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def alarm_rows(grid, rows, use_dhw):
    result = []
    for row in grid:
        target = reference(row.get('equipRef')) or reference(row.get('targetRef'))
        if not use_dhw and is_dhw(rows.get(target, {}), rows=rows):
            continue
        text = row.get('alarmText')
        status = row.get('alarmStatus')
        result.append({'time': timestamp(row.get('lastTimeOn') or row.get('ts')),
                       'text': text[:200] if isinstance(text,str) else '',
                       'status': status[:50] if isinstance(status,str) else '',
                       'equipment': name(rows[target]) if target in rows else 'Anlage'})
    return sorted(result, key=lambda row: datetime.fromisoformat(row['time']).timestamp() if row['time'] else float('-inf'), reverse=True)


def convert(spec, grid, site_id, rows, use_dhw=True):
    key, label, parent, kind, unit, _, mode = spec
    ident = 'summary:' + key
    if mode == 'details':
        result = {}
        incoming = {item.get('dis'):item.get('curVal') for item in grid or []}
        fields = list(PARAMETERS)[9:] if key.endswith(':properties') else list(PARAMETERS)[:9]
        # Stable placeholders recover after an initially unavailable optional view.
        for field in fields:
            current = incoming.get(field)
            point_id = ident + ':' + field
            point_kind = 'Bool' if field in ('tankConnection','bufferTankConnection') else 'Number'
            point_unit = '°C' if 'Temperature' in field else 'kW' if field == 'capacityRank' else ''
            result[point_id] = synthetic(point_id, f'{label} – {PARAMETERS[field]}', current,
                                         site_id, parent, point_kind, point_unit, diagnostic=True)
            if field == 'tankConnection': result[point_id]['tankModelId'] = '_equip:tank:connection'
        return result
    if mode in ('alarms', 'history'):
        alarms = alarm_rows(grid, rows, use_dhw) if grid is not None else None
        point = synthetic(ident, label, Number(len(alarms)) if alarms is not None else None, site_id)
        point['attributes'] = {'alarms':alarms[:20], 'listed_alarms_limit':20} if alarms is not None else {}
        result = {ident:point}
        if mode == 'history':
            latest = alarms[0] if alarms else None
            last_id = 'summary:lastAlarm'
            text = (latest['text'] + ' (' + latest['status'] + ')') if latest else ('Keine' if alarms is not None else None)
            point = synthetic(last_id, 'Letzter Alarm', text, site_id, kind='Str')
            point['attributes'] = latest or {}
            result[last_id] = point
        return result
    raw = grid[0].get('val') if grid else None
    if key.endswith(':errorCodeText') and raw == '':
        raw = 'Keiner'
    return {ident: synthetic(ident, label, raw, site_id, parent, kind, unit)}

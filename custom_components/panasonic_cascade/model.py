"""Point classification kept independent of Home Assistant for fixture testing."""
from .const import BOOL_CONTROLS, ENUM_CONTROLS, NUMBER_CONTROLS
from .zinc import MARKER, Number, Ref, value


POINT_LABELS = {
 'compensationCurveHeatZone1MaxTemperature': 'Zone 1 – Heizkurve – Max. Wassertemperatur',
 'compensationCurveHeatZone1MinTemperature': 'Zone 1 – Heizkurve – Min. Wassertemperatur',
 'compensationCurveHeatZone1OutdoorAirMaxTemperature': 'Zone 1 – Heizkurve – Max. Außentemperatur',
 'compensationCurveHeatZone1OutdoorAirMinTemperature': 'Zone 1 – Heizkurve – Min. Außentemperatur',
'operation': 'Betriebsanforderung',
 'errorCodeConnected': 'Fehlercode (Rohwert)',
 'errorStatus': 'Fehlerstatus',
 'heatModeEnergyConsumption': 'Heizen – Elektrische Leistung',
 'heatModeEnergyGeneration': 'Heizen – Thermische Leistung',
 'heatModeEnergyConsumptionTotalMsb': 'Heizen – Aufgenommene Energie',
 'heatModeEnergyGenerationTotalMsb': 'Heizen – Erzeugte Energie',
 'tankModeEnergyConsumption': 'Warmwasser – Elektrische Leistung',
 'tankModeEnergyGeneration': 'Warmwasser – Thermische Leistung',
 'tankModeEnergyConsumptionMsb': 'Warmwasser – Aufgenommene Energie',
 'tankModeEnergyGenerationMsb': 'Warmwasser – Erzeugte Energie',
 'coolModeHeatRecoveryModeEnergyConsumption': 'Kühlen/Wärmerückgewinnung – Elektrische Leistung',
 'coolModeHeatRecoveryModeEnergyGeneration': 'Kühlen/Wärmerückgewinnung – Thermische Leistung',
 'coolModeHeatRecoveryModeEnergyConsumptionTotalMsb': 'Kühlen/Wärmerückgewinnung – Aufgenommene Energie',
 'coolModeHeatRecoveryModeEnergyGenerationTotalMsb': 'Kühlen/Wärmerückgewinnung – Erzeugte Energie',
 'zone1WaterShiftRoomPoolSetpointTemperature': 'Zone 1 – Solltemperatur (Gerät)',
 'zone2WaterShiftRoomPoolSetpointTemperature': 'Zone 2 – Solltemperatur (Gerät)',
 'zone1Zone2OnOff': 'Zone 1/2 – Zustand (Gerät)',
 'tankWaterSetTemperature': 'Warmwasser – Solltemperatur (Gerät)',
 'heatCapacity1': 'Heizkapazität 1',
 'heatCapacity2': 'Heizkapazität 2',
 'coolCapacity1': 'Kühlkapazität 1',
 'coolCapacity2': 'Kühlkapazität 2',
 'quietRequest': 'Leisemodus (Gerät)',
 'direction': 'Betriebsrichtung',
 'mode': 'Betriebsart (Gerät)',
 'externalCompressorSw': 'Externer Kompressorschalter'}

def model_key(row):
    for tag in ("bufferModelId", "tankModelId", "siteModelId", "heatPumpModelId", "heatPumpAquareaModelId"):
        model = row.get(tag)
        if isinstance(model, str):
            return model.rsplit(":", 1)[-1]
    return ""


def name(row):
    ident = row.get("id")
    raw = row.get("dis") or (ident.display if isinstance(ident, Ref) else "") or row.get("navName") or "Cascade point"
    key = model_key(row)
    if key in POINT_LABELS:
        raw = POINT_LABELS[key]
    # FIN display strings can contain empty hierarchy levels (leading pipes).
    return " – ".join(part.strip() for part in str(raw).split("|") if part.strip()) or "Cascade point"


def control_kind(row):
    if row.get("writable") is not MARKER or row.get("bacnetServerReadOnly") is MARKER:
        return None
    # The captured records advertise this exact action; do not infer writable APIs.
    if "pointSetDef(" not in str(row.get("actions", "")):
        return None
    key = model_key(row)
    if row.get("kind") == "Bool" and key in BOOL_CONTROLS:
        return "switch"
    if row.get("kind") == "Str" and key in ENUM_CONTROLS and enum_options(row):
        return "select"
    if row.get("kind") == "Number" and key in NUMBER_CONTROLS and unit(row) == "°C":
        low, high = bounds(row)
        if low < high:
            return "number"
    return None


def enum_options(row):
    return [s.strip() for s in str(row.get("enum", "")).split(",") if s.strip()]


def unit(row):
    raw = row.get("curVal")
    return row.get("unit") or (raw.unit if isinstance(raw, Number) else "")


def bounds(row):
    low, high = NUMBER_CONTROLS[model_key(row)]
    outdoor = "OutdoorAir" in model_key(row)
    min_tags = ("minVal",) if outdoor else ("minVal", "hotSpMin" if "Cold" not in model_key(row) else "coldSpMin")
    max_tags = ("maxVal",) if outdoor else ("maxVal", "hotSpMax" if "Cold" not in model_key(row) else "coldSpMax")
    for tag in min_tags:
        raw = row.get(tag)
        if isinstance(raw, Number) and raw.unit in ("", "°C"):
            low = max(low, raw.value)
    for tag in max_tags:
        raw = row.get(tag)
        if isinstance(raw, Number) and raw.unit in ("", "°C"):
            high = min(high, raw.value)
    return low, high


def state(row):
    if row.get("curStatus") not in (None, "ok"):
        return None
    raw = row.get("curVal")
    if invalid_temperature(row):
        return None
    result = value(raw)
    return result if isinstance(result, (str, int, float, bool)) else None


def zone_states(raw):
    if raw not in ("Off/Off", "On/Off", "Off/On", "On/On"):
        raise ValueError("Unknown zone status; no change sent")
    return raw.split("/")


def zone1_value(row, enabled):
    if type(enabled) is not bool or model_key(row) != "zone1Zone2OnOffSetpoint" or control_kind(row) != "select":
        raise ValueError("Zone control is not supported")
    if row.get("curStatus") != "ok":
        raise ValueError("Current zone status is unavailable")
    current = zone_states(row.get("curVal"))
    default = zone_states(row.get("writeDef"))
    if current != default:
        raise ValueError("A schedule or override is active; remove it in the controller before switching Zone 1")
    current[0] = "On" if enabled else "Off"
    target = "/".join(current)
    if target not in enum_options(row):
        raise ValueError("Requested zone combination is not supported")
    return target


def is_dhw(row, field="curVal", rows=None):
    """Pure domestic hot water; a heating buffer tank is deliberately retained."""
    if field in ("isAvailableTank", "isRunningTank", "runRequestTank", "orderTank"):
        return True
    seen = set()
    while row:
        key = model_key(row).casefold()
        if row.get("tankModelId") or key.startswith(("dhw", "bivalentdhw", "tankmode", "tankwater")) or "sterilization" in key:
            return True
        parent = row.get("equipRef")
        ident = parent.id if isinstance(parent, Ref) else None
        if not rows or not ident or ident in seen:
            break
        seen.add(ident)
        row = rows.get(ident, {})
    return False


def visible_data(rows, use_dhw=True):
    if use_dhw:
        return rows
    return {ident: {key: val for key, val in row.items() if key not in ("isAvailableTank", "isRunningTank", "runRequestTank", "orderTank")}
            for ident, row in rows.items() if not is_dhw(row, rows=rows)}


def invalid_temperature(row):
    raw = row.get("curVal")
    return isinstance(raw, Number) and unit(row) in ("°C", "°F") and raw.value == -32768

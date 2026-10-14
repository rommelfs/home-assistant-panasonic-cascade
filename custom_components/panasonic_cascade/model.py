"""Point classification kept independent of Home Assistant for fixture testing."""
from .const import BOOL_CONTROLS, ENUM_CONTROLS, NUMBER_CONTROLS
from .zinc import MARKER, Number, Ref, value


def model_key(row):
    for tag in ("bufferModelId", "tankModelId", "siteModelId", "heatPumpModelId", "heatPumpAquareaModelId"):
        model = row.get(tag)
        if isinstance(model, str):
            return model.rsplit(":", 1)[-1]
    return ""


def name(row):
    ident = row.get("id")
    raw = row.get("dis") or (ident.display if isinstance(ident, Ref) else "") or row.get("navName") or "Cascade point"
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
    for tag in ("minVal", "hotSpMin" if "Cold" not in model_key(row) else "coldSpMin"):
        raw = row.get(tag)
        if isinstance(raw, Number) and raw.unit in ("", "°C"):
            low = max(low, raw.value)
    for tag in ("maxVal", "hotSpMax" if "Cold" not in model_key(row) else "coldSpMax"):
        raw = row.get(tag)
        if isinstance(raw, Number) and raw.unit in ("", "°C"):
            high = min(high, raw.value)
    return low, high


def state(row):
    if row.get("curStatus") not in (None, "ok"):
        return None
    raw = row.get("curVal")
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
    if field == "isAvailableTank":
        return True
    seen = set()
    while row:
        key = model_key(row).casefold()
        if row.get("tankModelId") or key.startswith(("dhw", "bivalentdhw")) or "sterilization" in key:
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
    return {ident: {key: val for key, val in row.items() if key != "isAvailableTank"}
            for ident, row in rows.items() if not is_dhw(row, rows=rows)}

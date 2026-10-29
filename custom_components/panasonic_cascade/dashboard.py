"""Build a native dashboard using the installed entity registry IDs."""
import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import voluptuous as vol

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .model import name, model_key
from .zinc import reference

SERVICE = "populate_dashboard"


CURVE_KEYS = {
    "compensationCurveHeatZone1MaxTemperature": "water_max",
    "compensationCurveHeatZone1MinTemperature": "water_min",
    "compensationCurveHeatZone1OutdoorAirMaxTemperature": "outdoor_max",
    "compensationCurveHeatZone1OutdoorAirMinTemperature": "outdoor_min",
}


def heating_curve_cards(entries, entities):
    """Match actual IDs by point identity, independently for each installation/equipment."""
    cards = []
    for entry in entries:
        data = getattr(getattr(entry, "runtime_data", None), "data", {})
        if not isinstance(data, dict):
            continue
        points = {ident: (CURVE_KEYS[model_key(row)], reference(row.get("equipRef")))
                  for ident, row in data.items() if model_key(row) in CURVE_KEYS}
        if not points:
            continue
        groups = {}
        # Prefer editable defaults; retain a read-only curve when controls are off.
        for entity in sorted(entities, key=lambda e: e.domain == "number"):
            if entity.config_entry_id != entry.entry_id or entity.domain not in ("sensor", "number"):
                continue
            prefix = entry.unique_id + "|"
            if not entity.unique_id.startswith(prefix):
                continue
            ident, _, field = entity.unique_id[len(prefix):].partition("|")
            if ident not in points or field != ("curVal|control" if entity.domain == "number" else "curVal"):
                continue
            key, equipment = points[ident]
            groups.setdefault(equipment, {})[key] = entity.entity_id
        for values in groups.values():
            if len(values) == 4:
                cards.append({"type": "custom:panasonic-cascade-heating-curve",
                              "title": "Zone 1 – Heizkurve", "entities": values})
    return cards


def build_dashboard(hass, entry_id=None):
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    entries = hass.config_entries.async_entries(DOMAIN)
    allowed = {entry.entry_id for entry in entries if entry_id is None or entry.entry_id == entry_id}
    if not allowed:
        raise HomeAssistantError("No matching Panasonic Cascade installation")
    entities = sorted((entity for entity in registry.entities.values()
                       if entity.platform == DOMAIN and entity.config_entry_id in allowed
                       and not entity.disabled and not entity.hidden), key=lambda entity: entity.entity_id)
    if not entities:
        raise HomeAssistantError("No enabled Cascade entities found; load the integration first")
    groups, controls, overview, temperatures, power, energy, alarms, efficiency, statistical_energy = {}, [], [], [], [], [], [], [], []
    operating, hours, electrical_energy = [], [], []
    point_models = {}
    for entry in entries:
        data = getattr(getattr(entry, "runtime_data", None), "data", {})
        if isinstance(data, dict) and getattr(entry, "unique_id", None):
            point_models.update({f"{entry.unique_id}|{ident}|curVal":model_key(row) for ident,row in data.items()})
    for entity in entities:
        label = entity.name or name({"dis": entity.original_name or entity.entity_id})
        row = {"entity": entity.entity_id, "name": label}
        device = devices.devices.get(entity.device_id)
        group = device.name_by_user or device.name if device else "Anlage"
        group = name({"dis": group or "Anlage"})
        groups.setdefault((entity.config_entry_id, entity.device_id, group), []).append(row)
        if entity.domain in ("switch", "select", "number"):
            controls.append(row)
        state = hass.states.get(entity.entity_id)
        unit = state.attributes.get("unit_of_measurement") if state else entity.unit_of_measurement
        diagnostic = getattr(entity, "entity_category", None) == "diagnostic"
        if entity.domain == "sensor" and unit in ("Wh", "kWh"):
            energy.append(row)
            capabilities = getattr(entity, "capabilities", None) or {}
            state_class = (state.attributes.get("state_class") if state else None) or capabilities.get("state_class")
            if state_class == "total_increasing":
                statistical_energy.append(row)
                key = point_models.get(entity.unique_id, "").casefold()
                original = (entity.original_name or "").casefold()
                if "energyconsumption" in key or any(word in original for word in (
                        "aufgenommene energie", "consumed energy", "energy consumption", "electricity consumption", "stromverbrauch")):
                    electrical_energy.append(row)
        if entity.domain == "sensor" and 'cop' in (entity.original_name or label).casefold():
            efficiency.append(row)
        if any(f"|summary:{key}|" in entity.unique_id for key in ("activeAlarms", "alarmHistory", "lastAlarm")):
            alarms.append(row)
        if entity.domain == "sensor" and not diagnostic and unit in ("W", "kW"):
            power.append(row)
        if entity.domain == "sensor" and not diagnostic and unit in ("°C", "°F") and not any(
            word in label.casefold() for word in ("setpoint", "soll", "curve", "max", "min")):
            temperatures.append(row)
        if entity.domain == "binary_sensor" and any(
            entity.unique_id.endswith("|" + field) for field in ("isConnected", "isRunning", "isInAlarm")):
            overview.append(row)
        if entity.domain == "binary_sensor" and entity.unique_id.endswith("|isRunning"):
            operating.append(row)
        if entity.domain == "sensor" and unit in ("h", "min", "s") and any(
                word in (entity.original_name or label).casefold() for word in ("compressor", "betriebsstunden", "working hours", "laufzeit")):
            hours.append(row)
    cards = heating_curve_cards([entry for entry in entries if entry.entry_id in allowed], entities)
    if controls:
        cards.append({"type": "entities", "title": "Steuerung", "show_header_toggle": False, "entities": controls})
    else:
        cards.append({"type": "markdown", "content": "**Steuerung aktivieren:** Einstellungen → Geräte & Dienste → Panasonic Cascade / Smart Edge → Konfigurieren → Steuerungen aktivieren. Anschließend dieses Dashboard erneut befüllen."})
    for title, rows in (("Leistung", power), ("Aktuelle Temperaturen", temperatures), ("Betriebszustand", overview), ("Alarme", alarms), ("COP", efficiency)):
        if rows:
            cards.append({"type": "entities", "title": title, "show_header_toggle": False, "entities": rows})
    if temperatures:
        cards.append({"type": "history-graph", "title": "Temperaturverlauf", "hours_to_show": 12, "entities": temperatures})
    if power:
        cards.append({"type": "history-graph", "title": "Leistungsverlauf", "hours_to_show": 12, "entities": power})
    if not (power or temperatures or overview):
        cards.append({"type": "entities", "title": "Aktuelle Werte", "show_header_toggle": False,
                      "entities": [row for rows in groups.values() for row in rows if row not in controls]})
    details = [{"type": "entities", "title": group, "show_header_toggle": False, "entities": rows}
               for (_, _, group), rows in sorted(groups.items(), key=lambda item: str(item[0]))]
    views = [
        {"title": "Übersicht", "path": "overview", "icon": "mdi:heat-pump", "cards": cards},
        {"title": "Alle Werte", "path": "details", "icon": "mdi:format-list-bulleted", "cards": details},
    ]
    if operating or hours:
        runtime_cards = []
        if operating:
            runtime_cards.extend([
                {"type":"entities", "title":"Wärmepumpen – Betriebszustand", "show_header_toggle":False, "entities":operating},
                {"type":"history-graph", "title":"Betrieb und Taktung – 24 Stunden", "hours_to_show":24, "entities":operating},
            ])
        if hours:
            runtime_cards.extend([
                {"type":"entities", "title":"Verdichter – Betriebsstunden", "show_header_toggle":False, "entities":hours},
                {"type":"history-graph", "title":"Betriebsstunden – Verlauf", "hours_to_show":168, "entities":hours},
            ])
        if power:
            runtime_cards.append({"type":"history-graph", "title":"Leistung während des Betriebs", "hours_to_show":24, "entities":power})
        views.append({"title":"Laufzeiten & Taktung", "path":"runtime", "icon":"mdi:chart-timeline-variant", "cards":runtime_cards})
    if energy:
        energy_cards = [{"type":"entities", "title":"Energiezähler", "show_header_toggle":False, "entities":energy}]
        energy_cards.append({"type":"history-graph", "title":"Energiezähler – Verlauf", "hours_to_show":168, "entities":energy})
        if power:
            energy_cards.append({"type":"history-graph", "title":"Elektrische und thermische Leistung", "hours_to_show":24, "entities":power})
        if statistical_energy:
            energy_cards.append({"type":"statistics-graph", "title":"Energie pro Tag", "chart_type":"bar", "period":"day",
                                 "days_to_show":7, "stat_types":["change"], "entities":[row["entity"] for row in statistical_energy]})
        for period, title, days in (("hour", "Stündlich", 2), ("day", "Täglich", 30),
                                    ("week", "Wöchentlich", 182), ("month", "Monatlich", 730),
                                    ("year", "Jährlich", 3650)):
            if electrical_energy:
                energy_cards.append({"type":"statistics-graph", "title":f"Verbrauch von Elektrizität – {title}",
                                     "chart_type":"bar", "period":period, "days_to_show":days,
                                     "stat_types":["change"], "entities":deepcopy(electrical_energy)})
        if not electrical_energy:
            energy_cards.append({"type":"markdown", "content":"**Verbrauch von Elektrizität:** Kein geeigneter kumulativer Stromzähler mit Langzeitstatistik gefunden. Thermische Energie und kW-Leistungswerte werden nicht als Stromverbrauch verwendet."})
        views.append({"title":"Energie", "path":"energy", "icon":"mdi:lightning-bolt", "cards":energy_cards})
    if alarms:
        cards = [{"type":"entities", "title":"Alarme und Verlauf", "show_header_toggle":False, "entities":alarms}]
        for row in alarms:
            entity_id = row["entity"]
            registry_entry = registry.entities[entity_id]
            if not any(f"|summary:{key}|" in registry_entry.unique_id for key in ("activeAlarms", "alarmHistory")):
                continue
            content = "{% set alarms = state_attr('" + entity_id + "', 'alarms') %}\n" + (
                "{% if alarms is none %}Daten nicht verfügbar."
                "{% elif not alarms %}Keine Einträge."
                "{% else %}{% for alarm in alarms %}\n"
                "- {{ alarm.time or 'Zeit unbekannt' }} · {{ alarm.equipment }}: {{ alarm.text }} ({{ alarm.status }})\n"
                "{% endfor %}{% endif %}")
            cards.append({"type":"markdown", "title":row["name"], "content":content})
        views.append({"title":"Alarme", "path":"alarms", "icon":"mdi:alert-circle-outline", "cards":cards})
    return {"title":"Panasonic Cascade", "views":views}


def merge_dashboard(existing, generated):
    """Add missing views, cards and entity rows; retain all existing user configuration."""
    if existing.get("strategy"):
        raise HomeAssistantError("Use a separate storage dashboard; strategy dashboards cannot be updated safely")
    result = deepcopy(existing)

    def walk(container):
        for key in ("cards", "sections"):
            for card in container.get(key, []):
                if isinstance(card, dict):
                    yield card
                    yield from walk(card)
        if isinstance(container.get("card"), dict):
            yield container["card"]
            yield from walk(container["card"])

    def identity(card):
        if card.get("type") == "custom:panasonic-cascade-heating-curve":
            return (card["type"], tuple(sorted(card.get("entities", {}).items())))
        return (card.get("type"), card.get("title"), card.get("entity"))

    def entity_id(row):
        return row if isinstance(row, str) else row.get("entity") if isinstance(row, dict) else None

    for new_view in generated.get("views", []):
        view = next((v for v in result.setdefault("views", []) if v.get("path") == new_view.get("path")), None)
        if view is None:
            result["views"].append(deepcopy(new_view))
            continue
        if view.get("type") == "panel" or view.get("panel"):
            # A panel permits a single card: keep it intact and use a separate view.
            path = str(new_view.get("path", "cascade")) + "-cascade"
            extra = next((v for v in result["views"] if v.get("path") == path), None)
            if extra is None:
                extra = {**deepcopy(new_view), "path":path, "cards":[]}
                result["views"].append(extra)
            view = extra
        for new_card in new_view.get("cards", []):
            card = next((c for c in walk(view) if identity(c) == identity(new_card)), None)
            if card is not None:
                if card.get("type") in ("entities", "history-graph", "statistics-graph"):
                    present = {entity_id(r) for r in card.get("entities", [])}
                    for row in new_card.get("entities", []):
                        ident = entity_id(row)
                        if ident and ident not in present:
                            card.setdefault("entities", []).append(deepcopy(row))
                            present.add(ident)
                continue
            if view.get("type") == "sections":
                view.setdefault("sections", []).append({"type":"grid", "cards":[deepcopy(new_card)]})
            else:
                view.setdefault("cards", []).append(deepcopy(new_card))
    return result


async def save_dashboard_backup(hass, url_path, config):
    """Persist the previous configuration before any change; fail closed on storage errors."""
    store = Store(hass, 1, f"{DOMAIN}.dashboard_backups")
    saved = await store.async_load() or {}
    backups = saved.setdefault(url_path, [])
    backups.append({"created_at":datetime.now(UTC).isoformat(), "config":deepcopy(config)})
    saved[url_path] = backups[-5:]
    await store.async_save(saved)


async def restore_dashboard(hass, url_path):
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    lovelace = hass.data.get(LOVELACE_DATA)
    target = lovelace.dashboards.get(url_path) if lovelace else None
    if target is None or target.mode != "storage":
        raise HomeAssistantError("No matching storage dashboard")
    saved = await Store(hass, 1, f"{DOMAIN}.dashboard_backups").async_load() or {}
    backups = saved.get(url_path, [])
    if not backups:
        raise HomeAssistantError("No dashboard backup available; backups start with integration 0.6.1")
    config = deepcopy(backups[-1]["config"])
    current = await target.async_load(False)
    await save_dashboard_backup(hass, url_path, current)
    await target.async_save(config)


async def populate_dashboard(hass, url_path, entry_id=None, overwrite=False, update=False):
    # Work through Lovelace's existing live dashboard, never edit .storage directly.
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.dashboard import ConfigNotFound

    lovelace = hass.data.get(LOVELACE_DATA)
    target = lovelace.dashboards.get(url_path) if lovelace else None
    if target is None or target.mode != "storage":
        raise HomeAssistantError("Create an empty dashboard with this URL first (Settings → Dashboards)")
    if update and overwrite:
        raise HomeAssistantError("Choose update or overwrite, not both")
    config = build_dashboard(hass, entry_id)
    try:
        existing = await target.async_load(False)
    except ConfigNotFound:
        existing = {}
    empty = not existing or (
        not existing.get("strategy") and set(existing) <= {"title", "views"}
        and all(set(view) <= {"title", "path", "icon", "cards", "badges", "sections"}
                and not any(view.get(key) for key in ("cards", "badges", "sections"))
                for view in existing.get("views", []))
    )
    if not empty and not overwrite and not update:
        raise HomeAssistantError("Dashboard already contains a configuration; use update: true to preserve existing cards")
    if update and not empty:
        config = merge_dashboard(existing, config)
    if config == existing:
        return
    if existing:
        await save_dashboard_backup(hass, url_path, existing)
    await target.async_save(config)


def async_register_dashboard_service(hass):
    if hass.services.has_service(DOMAIN, SERVICE):
        return
    lock = asyncio.Lock()

    async def handle(call):
        async with lock:
            await populate_dashboard(hass, **call.data)

    async_register_admin_service(hass, DOMAIN, SERVICE, handle, schema=vol.Schema({
        vol.Required("url_path"): vol.All(str, vol.Length(min=1)),
        vol.Optional("entry_id"): str,
        vol.Optional("overwrite", default=False): bool,
        vol.Optional("update", default=False): bool,
    }))

    async def handle_restore(call):
        async with lock:
            await restore_dashboard(hass, call.data["url_path"])

    async_register_admin_service(hass, DOMAIN, "restore_dashboard", handle_restore, schema=vol.Schema({
        vol.Required("url_path"): vol.All(str, vol.Length(min=1)),
    }))

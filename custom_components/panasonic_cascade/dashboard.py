"""Build a native dashboard using the installed entity registry IDs."""
import asyncio
import logging
from copy import deepcopy
from datetime import UTC, datetime

import voluptuous as vol

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .model import name, model_key
from .labels import compact_label, display_label
from .zinc import reference

SERVICE = "populate_dashboard"
LOGGER = logging.getLogger(__name__)
TABLE_MARKER = "{# Panasonic Cascade daily-start table #}"


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


def starts_table(entities):
    """Native Markdown table: explicit absolute counts for today and the past six days."""
    sources = [row['entity'] for row in entities]
    headers = ["{{ state_attr('" + source + "', 'friendly_name') | default('WP', true) | replace(' · Starts heute','') | replace(' · Verdichterstarts heute','') | replace('|','/') | replace('\\n',' ') }}" for source in sources]
    content = TABLE_MARKER + "\n{% set pumps = " + repr(sources) + " %}\n"
    content += "{% set ns = namespace(usable=false) %}{% for source in pumps %}{% for day in state_attr(source, 'daily_starts') or [] %}{% if day.starts is not none %}{% set ns.usable = true %}{% endif %}{% endfor %}{% endfor %}\n{% if ns.usable %}\n"
    content += "| Tag | " + " | ".join(headers) + " |\n|---|" + "---:|" * len(sources) + "\n"
    content += """{% for offset in range(7) -%}
{% set date = (now().date() - timedelta(days=offset)) | string -%}
| {{ 'Heute' if offset == 0 else 'Gestern' if offset == 1 else (now() - timedelta(days=offset)).strftime('%d.%m.%Y') }} |{% for source in pumps %}{% set item = (state_attr(source, 'daily_starts') or []) | selectattr('date', 'eq', date) | first | default(none) %} {{ item.starts if item and item.starts is not none else '—' }}{{ '*' if item and item.starts is not none and item.partial else '' }} |{% endfor %}
{% endfor %}

Verdichterstarts = bestätigte Aus→Ein-Wechsel. **—**: keine auswertbaren Daten. Sternchen: Erfassung unvollständig; Wert ist eine Mindestzahl.
{% else %}
**Verdichtertaktung nicht verfügbar.** Der Regler liefert keinen bestätigten Verdichterstatus. „In Betrieb“/„Betriebsfreigabe“ wird nicht als Verdichterlauf gezählt. Keine Schätzung aus der Leistung.
{% endif %}
"""
    return {"type":"markdown", "title":"Einschaltungen pro Tag", "content":content}


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
    operating, hours, electrical_energy, starts = [], [], [], []
    point_models = {}
    for entry in entries:
        data = getattr(getattr(entry, "runtime_data", None), "data", {})
        if isinstance(data, dict) and getattr(entry, "unique_id", None):
            point_models.update({f"{entry.unique_id}|{ident}|curVal":model_key(row) for ident,row in data.items()})
    for entity in entities:
        label = entity.name or compact_label(name({"dis": entity.original_name or entity.entity_id}))
        if entity.unique_id.endswith("|isRunning") and not entity.name:
            label = label.replace(" · In Betrieb", " · Betriebsfreigabe").replace(" – In Betrieb", " · Betriebsfreigabe")
        row = {"entity": entity.entity_id, "name": label}
        device = devices.devices.get(entity.device_id)
        group = device.name_by_user or device.name if device else "Anlage"
        group = name({"dis": group or "Anlage"})
        groups.setdefault((entity.config_entry_id, entity.device_id, group), []).append(row)
        if entity.domain in ("switch", "select", "number"):
            controls.append(row)
        state = hass.states.get(entity.entity_id)
        unit = (state.attributes.get("unit_of_measurement") if state else None) or entity.unit_of_measurement
        diagnostic = getattr(entity, "entity_category", None) == "diagnostic"
        site_placeholder = 'site info' in (entity.original_name or '').casefold() or 'site_info' in entity.entity_id
        if entity.domain == "sensor" and unit in ("Wh", "kWh") and not site_placeholder:
            energy.append(row)
            capabilities = getattr(entity, "capabilities", None) or {}
            state_class = (state.attributes.get("state_class") if state else None) or capabilities.get("state_class")
            if state_class == "total_increasing":
                statistical_energy.append(row)
                key = point_models.get(entity.unique_id, "").casefold()
                original = (entity.original_name or "").casefold()
                if "energyconsumption" in key or any(word in original for word in (
                        "aufgenommene energie", "consumed energy", "energy consumption", "electricity consumption", "stromverbrauch", "stromzähler")):
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
        if entity.domain == "sensor" and entity.unique_id.endswith("|starts_today"):
            starts.append(row)
        if entity.domain == "binary_sensor" and entity.unique_id.endswith("|isRunning"):
            operating.append(row)
        if entity.domain == "sensor" and unit in ("h", "min", "s") and any(
                word in (entity.original_name or label).casefold() for word in ("compressor", "betriebsstunden", "working hours", "laufzeit", "verdichterstunden")):
            hours.append(row)
    cards = heating_curve_cards([entry for entry in entries if entry.entry_id in allowed], entities)
    curve_entities = {ident for card in cards for ident in card.get("entities", {}).values()}
    controls = [row for row in controls if row["entity"] not in curve_entities]
    if controls:
        cards.append({"type": "entities", "title": "Steuerung", "show_header_toggle": False, "entities": controls})
    elif not cards:
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
    # Prefer actual per-unit compressor counters over repeated plant min/max diagnostics.
    entity_models = {e.entity_id:point_models.get(e.unique_id,'') for e in entities}
    actual_hours = [row for row in hours if entity_models.get(row['entity']) == 'compressorTotalOnTimeMsb']
    if actual_hours:
        hours = actual_hours
    if operating or hours or starts:
        runtime_cards = []
        if starts:
            runtime_cards.append(starts_table(starts))
            runtime_cards.append({"type":"entities", "title":"Einschaltungen heute", "show_header_toggle":False, "entities":starts})
        if operating:
            runtime_cards.extend([
                {"type":"entities", "title":"Wärmepumpen – Betriebszustand", "show_header_toggle":False, "entities":operating},
                {"type":"history-graph", "title":"Betriebsfreigabe – 24 Stunden", "hours_to_show":24, "entities":operating},
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
                                 "days_to_show":7, "stat_types":["change"], "entities":deepcopy(statistical_energy)})
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
    return polish_dashboard(hass, {"title":"Panasonic Cascade", "views":views}, registry)


def polish_dashboard(hass, config, registry=None):
    """Compact generated rows, choose canonical power, and dynamically hide missing readings."""
    registry = registry or er.async_get(hass)
    records = registry.entities
    def uid(row):
        entry = records.get(row.get('entity') if isinstance(row,dict) else row)
        return entry.unique_id if entry else ''
    def canonical(rows):
        summaries = [r for r in rows if '|summary:' in uid(r) and any(':'+key+'|curVal' in uid(r) for key in ('consumedPower','generatedPower'))]
        # Per-unit summaries and the explicit plant totals replace duplicated mode registers.
        if summaries:
            covered = {records[r['entity']].config_entry_id for r in summaries}
            return [r for r in rows if r in summaries or records[r['entity']].config_entry_id not in covered]
        return rows
    for view in config.get('views',[]):
        for card in view.get('cards',[]):
            if isinstance(card.get('entities'),list):
                for row in card['entities']:
                    if isinstance(row,dict):
                        entity = records.get(row.get('entity'))
                        if entity and not entity.name:
                            row['name'] = compact_label(row.get('name') or entity.original_name or entity.entity_id)
                if view.get('path') != 'details' and card.get('title') in ('Leistung','Leistungsverlauf','Leistung während des Betriebs','Elektrische und thermische Leistung'):
                    card['entities'] = canonical(card['entities'])
                if card.get('title') == 'COP':
                    calculated = [r for r in card['entities'] if ':calculatedCop|curVal' in uid(r)]
                    if calculated:card['entities'] = calculated
        if view.get('path') in ('runtime','energy'):
            overview = next((v for v in config['views'] if v.get('path')=='overview'),{})
            powers = next((c['entities'] for c in overview.get('cards',[]) if c.get('title')=='Leistung'),[])
            if powers and view['path']=='energy':
                view['cards'].insert(0,{'type':'entities','title':'Momentanverbrauch','show_header_toggle':False,'entities':deepcopy(powers)})
        for card in view.get('cards',[]):
            if card.get('title') in ('Leistung während des Betriebs','Leistungsverlauf'):
                overview = next((v for v in config['views'] if v.get('path')=='overview'),{})
                temperatures = next((c['entities'] for c in overview.get('cards',[]) if c.get('title')=='Aktuelle Temperaturen'),[])
                outside = [r for r in temperatures if any(t in r.get('name','').casefold() for t in ('aussen','outdoor air temperature'))]
                card['entities'] += [deepcopy(r) for r in outside if r not in card['entities']]
    overview = next((v for v in config['views'] if v.get('path')=='overview'),{})
    control_card = next((c for c in overview.get('cards',[]) if c.get('title')=='Steuerung'),None)
    if control_card:
        basic,advanced=[],[]
        for row in control_card['entities']:
            entity=records[row['entity']]
            label=row.get('name','').casefold()
            (basic if entity.unique_id.endswith('|zone1_control') or
                (entity.domain=='select' and any(t in label for t in ('betriebsart','mode','leisemodus'))) else advanced).append(row)
        control_card['entities']=basic
        if advanced:
            config['views'].append({'title':'Einstellungen','path':'settings','icon':'mdi:tune','cards':[
                {'type':'entities','title':'Weitere Vorgaben','show_header_toggle':False,'entities':advanced}]})
    for view in config['views']:
        for card in view.get('cards',[]):
            if view.get('path')=='details' and isinstance(card.get('entities'),list):
                card['entities']=[r for r in card['entities'] if records[r['entity']].domain not in ('number','select','switch')]
                card['title']=display_label(card.get('title',''))
            if isinstance(card.get('entities'),list):
                for row in card['entities']:
                    if isinstance(row,dict):
                        row['name']=display_label(row.get('name',row['entity']),card.get('title',''))
        view['cards']=[c for c in view.get('cards',[]) if c.get('entities') != []]
    # Native filtering updates on state changes, so recovering sensors reappear automatically.
    for view in config.get('views',[]):
        for index,card in enumerate(view.get('cards',[])):
            if card.get('type') == 'entities':
                view['cards'][index] = {'type':'entity-filter','title':card.get('title'),
                    'entities':card['entities'], 'conditions':[{'condition':'state','state_not':['unknown','unavailable']}],
                    'show_empty':False,'card':{k:v for k,v in card.items() if k!='entities'}}
    for view in config['views']:
        if view.get('path')=='details':compact_details_view(view,registry)
    return config


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
        return ("entities" if card.get("type") == "entity-filter" else card.get("type"), card.get("title"), card.get("entity"))

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
            if card is not None and isinstance(card.get('entities'),list) and isinstance(new_card.get('entities'),list):
                old_ids = {entity_id(r) for r in card['entities']}
                new_ids = {entity_id(r) for r in new_card['entities']}
                if old_ids and new_ids and not old_ids.intersection(new_ids):
                    card = None  # Same title alone does not make a custom graph integration-owned.
            if card is not None:
                if new_card.get('type') == 'entity-filter' and card.get('type') in ('entities','entity-filter'):
                    # Preserve manually named rows and user options while refreshing the generated selection.
                    old_rows = {r.get('entity'):r for r in card.get('entities',[]) if isinstance(r,dict)}
                    replacement = deepcopy(new_card)
                    present = {r['entity'] for r in replacement['entities']}
                    replacement['entities'].extend(deepcopy(r) for r in card.get('entities',[]) if (r if isinstance(r,str) else r.get('entity')) not in present)
                    for row in replacement['entities']:
                        if not isinstance(row,dict):continue
                        old = old_rows.get(row['entity'])
                        if old and old.get('name') and compact_label(old['name']) != row.get('name'):
                            # Old controller labels may have changed to localized names; compare registry below.
                            if not any(token in old['name'] for token in ('HP 0','Point Group','Site Info','Zone Group','Heizkurve',' · In Betrieb',' – In Betrieb','Standardwert','Vorgabe')):
                                row.update(old)
                    if card.get('type') == 'entities':
                        replacement['card'].update({k:v for k,v in card.items() if k not in ('type','title','entities')})
                    else:
                        replacement['card'].update({k:v for k,v in card.get('card',{}).items() if k not in ('type','title','entities')})
                    card.clear();card.update(replacement)
                    continue
                if card.get('type') == 'markdown' and card.get('content','').startswith(TABLE_MARKER) and new_card.get('content','').startswith(TABLE_MARKER):
                    card['content'] = new_card['content']
                if card.get("type") in ("entities", "entity-filter", "history-graph", "statistics-graph"):
                    defaults = {entity_id(r):r.get('name') for r in new_card.get('entities', []) if isinstance(r,dict)}
                    for old_row in card.get('entities', []):
                        if isinstance(old_row, dict) and old_row.get('name') and defaults.get(entity_id(old_row)):
                            if compact_label(old_row['name']) == defaults[entity_id(old_row)]:
                                old_row['name'] = defaults[entity_id(old_row)]
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


def clean_generated_overview(config, hass):
    """Clean recognized integration rows only; retain custom cards and the full detail view."""
    def walk(container):
        yield container
        for key in ('cards','sections'):
            for child in container.get(key,[]):
                if isinstance(child,dict):yield from walk(child)
    managed = ('Steuerung','Energiezähler','Verdichter – Betriebsstunden','Betriebsstunden – Verlauf','Energiezähler – Verlauf','Energie pro Tag')
    def owned(card):
        return card.get('title') in managed or card.get('title','').startswith('Verbrauch von Elektrizität – ')
    if not any(owned(c) for v in config.get('views',[]) for c in walk(v)):
        return config
    registry = er.async_get(hass)
    has_hours = any(not e.disabled and not e.hidden and any(word in (e.original_name or '').casefold() for word in ('compressor total on time','verdichterstunden')) for e in registry.entities.values())
    for view in config.get('views',[]):
        if view.get('path') == 'details':continue
        all_cards = list(walk(view))
        curve_ids = {ident for card in all_cards if card.get('type') == 'custom:panasonic-cascade-heating-curve'
                     for ident in card.get('entities',{}).values()}
        for card in all_cards:
            if not owned(card):
                continue
            if not isinstance(card.get('entities'),list):continue
            kept=[]
            for row in card['entities']:
                ident=row if isinstance(row,str) else row.get('entity') if isinstance(row,dict) else None
                entity=registry.entities.get(ident)
                if not entity or entity.platform != DOMAIN:
                    kept.append(row);continue
                original=(entity.original_name or '').casefold()
                if card.get('title') == 'Steuerung' and ident in curve_ids:continue
                if view.get('path') == 'energy' and ('site info' in original or 'site_info' in ident):continue
                if has_hours and card.get('title') in ('Verdichter – Betriebsstunden','Betriebsstunden – Verlauf') and '|summary:unit:' in entity.unique_id and any(x in entity.unique_id for x in ('minWorkingHours','maxWorkingHours')):continue
                kept.append(row)
            card['entities']=kept
        for container in all_cards:
            if isinstance(container.get('cards'),list):
                container['cards'] = [c for c in container['cards'] if not (owned(c) and c.get('entities') == [])]
    return config


def compact_details_view(view, registry):
    """Consolidate generated equipment groups; controls belong to their own views."""
    grouped, cards = {}, []
    for card in view.get('cards',[]):
        rows=card.get('entities')
        ids=[r if isinstance(r,str) else r.get('entity') for r in rows] if isinstance(rows,list) else []
        if card.get('type') not in ('entities','entity-filter') or not ids or not all(i in registry.entities and registry.entities[i].platform==DOMAIN for i in ids):
            cards.append(card);continue
        title=display_label(card.get('title','Anlage'))
        rows=[r for r in rows if registry.entities[r if isinstance(r,str) else r['entity']].domain not in ('switch','select','number')]
        if not rows:continue
        for row in rows:
            if isinstance(row,dict):row['name']=display_label(row.get('name',row['entity']),title)
        if title not in grouped:
            owned=deepcopy(card)
            owned.update({'type':'entity-filter','title':title,'entities':[],
                'conditions':[{'condition':'state','state_not':['unknown','unavailable']}],
                'show_empty':False,'card':{'type':'entities','title':title,'show_header_toggle':False}})
            grouped[title]=owned;cards.append(owned)
        present={r if isinstance(r,str) else r['entity'] for r in grouped[title]['entities']}
        grouped[title]['entities'] += [r for r in rows if (r if isinstance(r,str) else r['entity']) not in present]
    view['cards']=cards
    return view


def refresh_generated_cards(config, generated, registry):
    """Refresh recognized default cards only; preserve layout, custom cards and graph ranges."""
    def walk(container):
        yield container
        for key in ('cards','sections'):
            for child in container.get(key,[]):
                if isinstance(child,dict):yield from walk(child)
    for view in config.get('views',[]):
        if view.get('path')=='details':compact_details_view(view,registry)
        source = next((v for v in generated.get('views',[]) if v.get('path')==view.get('path')),None)
        if not source:continue
        defaults = {c.get('title'):c for c in source.get('cards',[]) if c.get('title')}
        for card in walk(view):
            rows = card.get('entities')
            if not isinstance(rows,list):continue
            ids = [r if isinstance(r,str) else r.get('entity') for r in rows if isinstance(r,(str,dict))]
            if not ids or not all(registry.entities.get(i) and registry.entities[i].platform==DOMAIN for i in ids):continue
            if card.get('type')=='history-graph' and card.get('title')=='Betrieb und Taktung – 24 Stunden' and all(registry.entities[i].unique_id.endswith('|isRunning') for i in ids):
                card['title']='Betriebsfreigabe – 24 Stunden'
            new = defaults.get(card.get('title'))
            if new and isinstance(new.get('entities'),list):
                new_owners = {registry.entities[i].config_entry_id for r in new['entities'] if (i := r if isinstance(r,str) else r.get('entity')) in registry.entities}
                if new_owners and any(registry.entities[i].config_entry_id not in new_owners for i in ids):continue
            if view.get('path') != 'details' and new and isinstance(new.get('entities'),list) and card.get('type') in ('entities','entity-filter','history-graph','statistics-graph'):
                if card.get('type') in ('history-graph','statistics-graph'):
                    card['entities'] = deepcopy(new['entities'])
                else:
                    # Original controller-path labels are defaults, personal labels are retained.
                    old = {r['entity']:r for r in rows if isinstance(r,dict)}
                    options = {k:v for k,v in card.items() if k not in ('type','entities','title','card','conditions','show_empty')}
                    card.clear();card.update(deepcopy(new))
                    card.setdefault('card',{}).update(options)
                    for row in card['entities']:
                        prior=old.get(row['entity'],{})
                        original=registry.entities[row['entity']].original_name or ''
                        if prior.get('name') and display_label(prior['name'],card.get('title','')) != display_label(original,card.get('title','')) and not any(t in prior['name'] for t in ('HP 0','Point Group','Site Info','Zone Group','Heizkurve',' · In Betrieb',' – In Betrieb','Standardwert','Vorgabe')):
                            row.update(prior)
            else:
                for row in rows:
                    if isinstance(row,dict):
                        entry=registry.entities[row['entity']]
                        if not entry.name and (not row.get('name') or compact_label(row['name'])==compact_label(entry.original_name or '')):
                            row['name']=display_label(entry.original_name or row['entity'],card.get('title',''))
    return config


async def save_dashboard_backup(hass, url_path, config):
    """Persist the previous configuration before any change; fail closed on storage errors."""
    store = Store(hass, 1, f"{DOMAIN}.dashboard_backups")
    saved = await store.async_load() or {}
    backups = saved.setdefault(url_path, [])
    backups.append({"created_at":datetime.now(UTC).isoformat(), "config":deepcopy(config)})
    saved[url_path] = backups[-5:]
    await store.async_save(saved)


async def async_refresh_starts_tables(hass):
    """Upgrade recognized generated views after startup, backing up before any save."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.dashboard import ConfigNotFound
    lovelace = hass.data.get(LOVELACE_DATA)
    if not lovelace:
        return
    registry = er.async_get(hass)
    records = [e for e in registry.entities.values() if e.platform == DOMAIN]
    running = {(e.config_entry_id,e.unique_id):e.entity_id for e in records if e.domain == 'binary_sensor' and e.unique_id.endswith('|isRunning')}
    counters = [e for e in records if e.domain == 'sensor' and e.unique_id.endswith('|starts_today') and not e.disabled and not e.hidden]
    if not counters:
        return
    def walk(container):
        yield container
        for key in ('cards','sections'):
            for child in container.get(key,[]):
                if isinstance(child,dict):yield from walk(child)
    async with hass.data.setdefault(f'{DOMAIN}.dashboard_lock', asyncio.Lock()):
        for url_path, target in lovelace.dashboards.items():
            if target.mode != 'storage':continue
            try:
                existing = await target.async_load(False)
                config = deepcopy(existing)
                for view in config.get('views',[]):
                    if view.get('path') != 'runtime' or view.get('type') == 'panel' or view.get('panel'):continue
                    cards = list(walk(view))
                    sources = {r if isinstance(r,str) else r.get('entity') for c in cards
                               if c.get('type') == 'history-graph' and c.get('title') in ('Betrieb und Taktung – 24 Stunden','Betriebsfreigabe – 24 Stunden')
                               for r in c.get('entities',[]) if isinstance(r,(str,dict))}
                    selected = [e for e in counters if running.get((e.config_entry_id,e.unique_id[:-len('starts_today')]+'isRunning')) in sources]
                    if not selected:continue
                    table = starts_table([{'entity':e.entity_id} for e in sorted(selected,key=lambda e:e.entity_id)])
                    owned = next((c for c in cards if c.get('type') == 'markdown' and c.get('content','').startswith(TABLE_MARKER)), None)
                    if owned is not None:
                        owned['content'] = table['content']
                    elif any(c.get('title') == table['title'] for c in cards):
                        continue  # A user-maintained table with this title remains unchanged.
                    elif view.get('type') == 'sections':
                        view.setdefault('sections',[]).insert(0,{'type':'grid','cards':[table]})
                    else:
                        view.setdefault('cards',[]).insert(0,table)
                recognized = any(c.get('type')=='custom:panasonic-cascade-heating-curve' and
                    all(i in registry.entities and registry.entities[i].platform==DOMAIN for i in c.get('entities',{}).values()) and len(c.get('entities',{}))==4
                    for v in config.get('views',[]) for c in walk(v))
                owners = {registry.entities[i].config_entry_id for v in config.get('views',[]) for c in walk(v)
                          if c.get('type')=='custom:panasonic-cascade-heating-curve'
                          for i in c.get('entities',{}).values() if i in registry.entities}
                if recognized and len(owners)==1:
                    generated = build_dashboard(hass,entry_id=next(iter(owners)))
                    config = refresh_generated_cards(config,generated,registry)
                    config = merge_dashboard(config,generated)
                    config = clean_generated_overview(config,hass)
                if config != existing:
                    await save_dashboard_backup(hass,url_path,existing)
                    await target.async_save(config)
            except ConfigNotFound:
                continue
            except (HomeAssistantError,OSError) as err:
                LOGGER.warning('Could not update daily start table in %s: %s',url_path,err)


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
        config = merge_dashboard(refresh_generated_cards(deepcopy(existing),config,er.async_get(hass)), config)
    config = clean_generated_overview(config, hass)
    if config == existing:
        return
    if existing:
        await save_dashboard_backup(hass, url_path, existing)
    await target.async_save(config)


def async_register_dashboard_service(hass):
    if hass.services.has_service(DOMAIN, SERVICE):
        return
    lock = hass.data.setdefault(f"{DOMAIN}.dashboard_lock", asyncio.Lock())

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

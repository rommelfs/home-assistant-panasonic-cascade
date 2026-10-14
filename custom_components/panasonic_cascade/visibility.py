"""Reversible DHW visibility for registered entities and native dashboards."""
from copy import deepcopy
import logging

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .model import is_dhw

LOGGER = logging.getLogger(__name__)


def dhw_entity_ids(registry, entry, rows):
    prefix = entry.unique_id + "|"
    result = set()
    for entity in registry.entities.values():
        if entity.platform != DOMAIN or entity.config_entry_id != entry.entry_id or not entity.unique_id.startswith(prefix):
            continue
        parts = entity.unique_id[len(prefix):].split("|")
        if len(parts) >= 2 and is_dhw(rows.get(parts[0], {}), parts[1], rows):
            result.add(entity.entity_id)
    return result


def without_dhw(config, hidden):
    """Remove only matching entity references from native dashboard cards."""
    result = deepcopy(config)

    def prune(container):
        if container.get("entity") in hidden:
            return False
        # Native conditional cards can wrap a single child instead of a stack.
        if isinstance(container.get("card"), dict) and not prune(container["card"]):
            return False
        if isinstance(container.get("entities"), list):
            container["entities"] = [row for row in container["entities"]
                                     if (row if isinstance(row, str) else row.get("entity") if isinstance(row, dict) else None) not in hidden]
            if not container["entities"]:
                return False
        for key in ("cards", "sections", "elements"):
            if isinstance(container.get(key), list):
                prior = container[key]
                container[key] = [child for child in prior if not isinstance(child, dict) or prune(child)]
                if prior and not container[key]:
                    return False
        return True

    for view in result.get("views", []):
        for key in ("cards", "sections", "elements"):
            if isinstance(view.get(key), list):
                view[key] = [card for card in view[key] if not isinstance(card, dict) or prune(card)]
        if isinstance(view.get("badges"), list):
            view["badges"] = [badge for badge in view["badges"]
                              if (badge if isinstance(badge, str) else badge.get("entity") if isinstance(badge, dict) else None) not in hidden]
    return result


async def async_apply_dhw_visibility(hass, entry, rows):
    """Keep customized registry IDs; restore only changes still owned by us."""
    registry = er.async_get(hass)
    store = Store(hass, 1, f"{DOMAIN}.dhw_visibility.{entry.entry_id}")
    saved = await store.async_load() or {"entities": {}, "dashboards": {}}
    use_dhw = entry.options.get("use_dhw", True)
    if use_dhw and not saved["entities"] and not saved["dashboards"]:
        return
    hidden = dhw_entity_ids(registry, entry, rows)
    if use_dhw:
        for entity_id, flags in saved["entities"].items():
            entity = registry.entities.get(entity_id)
            if not entity or entity.config_entry_id != entry.entry_id:
                continue
            changes = {}
            if flags.get("disabled") and entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                changes["disabled_by"] = None
            if flags.get("hidden") and entity.hidden_by == er.RegistryEntryHider.INTEGRATION:
                changes["hidden_by"] = None
            if changes:
                registry.async_update_entity(entity_id, **changes)
        saved["entities"] = {}
    else:
        # The saved set also covers points temporarily absent from the controller.
        hidden.update(saved["entities"])
        for entity_id in hidden:
            entity = registry.entities.get(entity_id)
            if not entity:
                continue
            flags = saved["entities"].setdefault(entity_id, {})
            changes = {}
            if entity.disabled_by is None:
                changes["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
                flags["disabled"] = True
            if entity.hidden_by is None:
                changes["hidden_by"] = er.RegistryEntryHider.INTEGRATION
                flags["hidden"] = True
            if changes:
                registry.async_update_entity(entity_id, **changes)

    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.dashboard import ConfigNotFound
    lovelace = hass.data.get(LOVELACE_DATA)
    for path, target in (lovelace.dashboards.items() if lovelace else []):
        if target.mode != "storage":
            continue
        path_key = path if path is not None else "@default"
        try:
            current = await target.async_load(False)
            backup = saved["dashboards"].get(path_key)
            if use_dhw:
                if backup and current == backup["after"]:
                    # Other installations may still have their DHW disabled.
                    still_hidden = {e.entity_id for e in registry.entities.values()
                                    if e.platform == DOMAIN and e.hidden_by == er.RegistryEntryHider.INTEGRATION}
                    await target.async_save(without_dhw(backup["before"], still_hidden))
                saved["dashboards"].pop(path_key, None)
            else:
                filtered = without_dhw(current, hidden)
                if filtered != current:
                    # Only restore an unchanged dashboard; preserve later user edits.
                    original = backup["before"] if backup and current == backup["after"] else current
                    saved["dashboards"][path_key] = {"before": original, "after": filtered}
                    await target.async_save(filtered)
        except ConfigNotFound:
            continue
        except HomeAssistantError:
            LOGGER.warning("Could not update DHW visibility for dashboard %s", path)
    await store.async_save(saved)

"""Shared point entity."""
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .model import name
from .zinc import reference


class CascadeEntity(CoordinatorEntity):
    def __init__(self, coordinator, ident, field="curVal"):
        super().__init__(coordinator)
        self.ident = ident
        self.field = field
        row = coordinator.data[ident]
        self._attr_unique_id = f"{coordinator.entry.unique_id}|{ident}|{field}"
        self._attr_name = name(row) + (f" | {field}" if field != "curVal" else "")
        self._attr_has_entity_name = False
        site = coordinator.entry.data["site_id"]
        parent = reference(row.get("equipRef")) or (ident if row.get("heatPumpModelId") or row.get("equip") else site)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.unique_id}|{parent}")},
            name=name(coordinator.data.get(parent, {})) if parent in coordinator.data else coordinator.entry.title,
            manufacturer="Panasonic", model="Cascade Control / Smart Edge",
            configuration_url=coordinator.client.url + f"/pod/panCascadeControlExt/index.html#/proj/{coordinator.client.project}/plantOverview",
        )

    @property
    def row(self):
        return self.coordinator.data.get(self.ident, {})

    @property
    def available(self):
        return super().available and self.ident in self.coordinator.data and self.row.get("curStatus") in (None, "ok")

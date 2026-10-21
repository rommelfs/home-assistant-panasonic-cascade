"""A test push without raising or acknowledging a controller alarm."""
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .notifications import async_test_push


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get('alarm_notify_service'):
        async_add_entities([CascadePushTestButton(entry.runtime_data)])


class CascadePushTestButton(CoordinatorEntity, ButtonEntity):
    _attr_name = 'Alarm-Push testen'
    _attr_has_entity_name = True
    _attr_icon = 'mdi:bell-check-outline'
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_unique_id = entry.unique_id + '|alarm_push_test'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id + '|' + entry.data['site_id'])},
                                           name=entry.title, manufacturer='Panasonic', model='Cascade Control / Smart Edge')

    @property
    def available(self):
        return self.hass.services.has_service('notify', self.coordinator.entry.options.get('alarm_notify_service', ''))

    async def async_press(self):
        await async_test_push(self.hass, self.coordinator.entry)

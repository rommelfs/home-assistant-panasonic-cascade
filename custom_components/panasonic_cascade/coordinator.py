"""Coordinated polling and explicit control operations."""
import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, AuthError

LOGGER = logging.getLogger(__name__)


class CascadeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(hass, LOGGER, name="Panasonic Cascade", config_entry=entry,
                         update_interval=timedelta(seconds=entry.options.get("scan_interval", 30)))
        self.client = client
        self.entry = entry

    async def _async_update_data(self):
        try:
            return await self.client.snapshot(self.entry.data["site_id"])
        except AuthError as err:
            raise ConfigEntryAuthFailed("FIN session must be renewed") from err
        except ApiError as err:
            raise UpdateFailed(str(err)) from err

    async def write(self, ident, new_value):
        if not self.entry.options.get("enable_controls", False):
            raise HomeAssistantError("Controls must be enabled in integration options")
        if not self.last_update_success or ident not in self.data:
            raise HomeAssistantError("Controller data is unavailable")
        try:
            await self.client.set_default(self.data[ident], new_value)
        except AuthError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("FIN session must be renewed") from err
        except (ApiError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()

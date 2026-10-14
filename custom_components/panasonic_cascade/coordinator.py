"""Coordinated polling and explicit control operations."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, AuthError
from .model import zone1_value, visible_data

LOGGER = logging.getLogger(__name__)


class CascadeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(hass, LOGGER, name="Panasonic Cascade", config_entry=entry,
                         update_interval=timedelta(seconds=entry.options.get("scan_interval", 30)))
        self.client = client
        self.entry = entry
        self._write_lock = asyncio.Lock()

    async def _async_update_data(self):
        try:
            self.all_data = await self.client.snapshot(self.entry.data["site_id"])
            return visible_data(self.all_data, self.entry.options.get("use_dhw", True))
        except AuthError as err:
            raise ConfigEntryAuthFailed("FIN session must be renewed") from err
        except ApiError as err:
            raise UpdateFailed(str(err)) from err

    async def write(self, ident, new_value):
        async with self._write_lock:
            await self._write(ident, new_value)

    async def write_zone1(self, ident, enabled):
        async with self._write_lock:
            await self._write(ident, enabled, zone1=True)

    async def _write(self, ident, new_value, zone1=False):
        if not self.entry.options.get("enable_controls", False):
            raise HomeAssistantError("Controls must be enabled in integration options")
        if not self.last_update_success or ident not in self.data:
            raise HomeAssistantError("Controller data is unavailable")
        try:
            row = self.data[ident]
            if zone1:
                row = await self.client.read_point(ident, self.entry.data["site_id"])
                new_value = zone1_value(row, new_value)
            await self.client.set_default(row, new_value)
        except AuthError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("FIN session must be renewed") from err
        except (ApiError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()

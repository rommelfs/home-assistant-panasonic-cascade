"""Serve the bundled, dependency-free heating curve card."""
import asyncio
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

CARD_URL = '/panasonic_cascade/heating-curve.js'
CARD_VERSION = '0.6.0'


async def async_setup_frontend(hass):
    if frontend.DATA_EXTRA_MODULE_URL not in hass.data:
        return
    lock = hass.data.setdefault(f'{DOMAIN}_frontend_lock', asyncio.Lock())
    async with lock:
        if hass.data.get(f'{DOMAIN}_frontend_ready'):
            return
        await hass.http.async_register_static_paths([
            StaticPathConfig(CARD_URL, str(Path(__file__).parent / 'www' / 'heating-curve.js'), False)
        ])
        frontend.add_extra_js_url(hass, f'{CARD_URL}?v={CARD_VERSION}')
        hass.data[f'{DOMAIN}_frontend_ready'] = True

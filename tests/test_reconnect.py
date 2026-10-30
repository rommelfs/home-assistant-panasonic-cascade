"""Temporary reboot errors must not stop automatic coordinator polling."""
import unittest
from unittest.mock import AsyncMock
import test_controls_dashboard as controls
from custom_components.panasonic_cascade.api import ApiError, AuthError
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed


class ReconnectCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def test_temporary_boot_error_is_retried_without_reauth(self):
        coordinator=controls.coordinator()
        coordinator.client.snapshot=AsyncMock(side_effect=[ApiError('FIN session not ready'),{}])
        with self.assertRaises(UpdateFailed):await coordinator._async_update_data()
        self.assertEqual(await coordinator._async_update_data(),{})
        coordinator.entry.async_start_reauth.assert_not_called()

    async def test_rejected_credentials_still_require_correction(self):
        coordinator=controls.coordinator()
        coordinator.client.snapshot=AsyncMock(side_effect=AuthError('Username/password authentication failed'))
        with self.assertRaises(ConfigEntryAuthFailed):await coordinator._async_update_data()

    async def test_control_connection_error_does_not_replay_or_start_reauth(self):
        coordinator=controls.coordinator()
        coordinator.client.set_default=AsyncMock(side_effect=ApiError('Controller connection failed'))
        with self.assertRaises(HomeAssistantError):await coordinator.write('point','On/Off')
        coordinator.client.set_default.assert_awaited_once()
        coordinator.entry.async_start_reauth.assert_not_called()
        coordinator.async_request_refresh.assert_not_awaited()

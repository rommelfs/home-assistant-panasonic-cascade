"""Seasonal display changes preserve measurement and control behavior."""
import tempfile
from unittest.mock import patch
import unittest
import test_dhw
from test_dhw import visibility, er
from test_protocol import model, zinc


class SeasonalDisplayTest(unittest.IsolatedAsyncioTestCase):
    fixture = test_dhw.DhwTest.fixture
    # Reuse the HA/storage fixture, without duplicating the inherited tests.
    async def test_seasonal_modes_restore_and_never_disable_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            hass, entry, registry, target, _ = await self.fixture(directory)
            entry.options = {'display_mode': 'heat'}
            points = {'dhw': {'bufferModelId': 'x:zone1WaterTemperatureColdSetpoint'},
                      'buffer': {'bufferModelId': 'x:compensationCurveHeatZone1MaxTemperature'}}
            original = {'views': [{'cards': [
                {'type': 'entities', 'entities': ['sensor.dhw_curVal', 'sensor.buffer_curVal']},
                {'type': 'custom:panasonic-cascade-heating-curve', 'entities': {'water_max': 'sensor.buffer_curVal'}}]}]}
            await target.async_save(original)
            with patch.object(visibility.er, 'async_get', return_value=registry):
                await visibility.async_apply_mode_visibility(hass, entry, points)
                self.assertEqual(registry.entities['sensor.dhw_curVal'].hidden_by, er.RegistryEntryHider.INTEGRATION)
                self.assertIsNone(registry.entities['sensor.dhw_curVal'].disabled_by)
                self.assertNotIn('sensor.dhw_curVal', str(await target.async_load(False)))
                # Repeat/reload, then switch to cooling: heating curve must disappear.
                await visibility.async_apply_mode_visibility(hass, entry, points)
                entry.options['display_mode'] = 'cool'
                await visibility.async_apply_mode_visibility(hass, entry, points)
                self.assertIsNone(registry.entities['sensor.dhw_curVal'].hidden_by)
                self.assertNotIn('sensor.buffer_curVal', str(await target.async_load(False)))
                self.assertIn('sensor.dhw_curVal', str(await target.async_load(False)))
                entry.options['display_mode'] = 'both'
                await visibility.async_apply_mode_visibility(hass, entry, points)
                self.assertEqual(await target.async_load(False), original)
                self.assertIsNone(registry.entities['sensor.buffer_curVal'].hidden_by)
            await hass.async_stop()

    async def test_personal_hiding_and_dashboard_edits_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            hass, entry, registry, target, _ = await self.fixture(directory)
            entry.options = {'display_mode': 'heat'}
            registry.entities['sensor.dhw_curVal'].hidden_by = er.RegistryEntryHider.USER
            points = {'dhw': {'bufferModelId': 'x:coolModeEnergyConsumption'}}
            with patch.object(visibility.er, 'async_get', return_value=registry):
                await visibility.async_apply_mode_visibility(hass, entry, points)
                custom = {'views': [{'cards': [{'type': 'markdown', 'content': 'personal'}]}]}
                await target.async_save(custom)
                entry.options['display_mode'] = 'both'
                await visibility.async_apply_mode_visibility(hass, entry, points)
                self.assertEqual(await target.async_load(False), custom)
                self.assertEqual(registry.entities['sensor.dhw_curVal'].hidden_by, er.RegistryEntryHider.USER)
            await hass.async_stop()

    def test_specific_modes_and_shared_or_dhw_points(self):
        for key in ('coolModeHeatRecoveryModeEnergyConsumption', 'zone1WaterTemperatureColdSetpoint', 'waterTempSpOffsetCool', 'targetTimeCold'):
            self.assertEqual(model.operating_mode({'bufferModelId': 'x:' + key}), 'cool')
        for key in ('heatModeEnergyConsumption', 'compensationCurveHeatZone1MaxTemperature', 'waterTempSpOffsetHeat'):
            self.assertEqual(model.operating_mode({'bufferModelId': 'x:' + key}), 'heat')
        for key in ('heatPump', 'outdoorAirTemperature', 'bufferMode', 'tBufferTank', 'generatedPower'):
            self.assertIsNone(model.operating_mode({'bufferModelId': 'x:' + key}))
        self.assertIsNone(model.operating_mode({'tankModelId': 'x:hotWater'}))
        self.assertEqual(model.operating_mode({'dis': 'WP 1 | Energy | Cold Water | COP'}), 'cool')
        self.assertEqual(model.operating_mode({}, 'runningUnitsAmountHot'), 'heat')

    def test_unrelated_custom_card_nested_entity_map_is_preserved(self):
        config = {"views": [{"cards": [{"type": "grid", "cards": [
            {"type": "custom:other-card", "entities": {"first": {"entity": "sensor.other"}, "options": [1, 2]}},
            {"type": "custom:panasonic-cascade-heating-curve", "entities": {"water_max": "sensor.heat"}}
        ]}]}]}
        filtered = visibility.without_dhw(config, {"sensor.heat"})
        self.assertEqual(len(filtered["views"][0]["cards"][0]["cards"]), 1)
        self.assertEqual(filtered["views"][0]["cards"][0]["cards"][0], config["views"][0]["cards"][0]["cards"][0])

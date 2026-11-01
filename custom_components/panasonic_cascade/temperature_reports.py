"""Observe genuine ESPHome temperature packets without changing HA or firmware.

HA's ESPHome integration can suppress identical sensor states before last_reported
is updated. Observe the existing connection; never poll/replay its cached state.
All private ESPHome access is confined here and unsupported shapes fail closed.
"""
import time

from homeassistant.core import callback


class TemperatureReports:
    def __init__(self, hass, changed, clock=time.time):
        self.hass, self.changed, self.clock = hass, changed, clock
        self.binding = None
        self.remove = None
        self.latest = None
        self.closed = False
        self.packet_count = 0

    def close(self):
        if self.remove:
            try:
                self.remove()
            except (KeyError, ValueError):
                # A disconnected API connection may already have cleared handlers.
                pass
        self.remove = self.binding = self.latest = None
        self.packet_count = 0

    def shutdown(self):
        self.closed = True
        self.close()

    def sample(self, entity_id):
        """Return a real native sample, or None to retain ordinary HA checks."""
        if self.closed:
            return None
        component = getattr(self.hass, 'data', {}).get('sensor')
        entity = component.get_entity(entity_id) if component and hasattr(component, 'get_entity') else None
        if entity is None or not type(entity).__module__.startswith('homeassistant.components.esphome.'):
            self.close()
            return None
        try:
            runtime = entity._entry_data
            info = entity._static_info
            connection = runtime.client._connection
            if not runtime.available or connection is None or not connection.is_connected:
                raise ValueError('Buffer temperature sensor disconnected')
            if info.unit_of_measurement != '°C':
                raise ValueError('ESPHome buffer temperature must report °C')
            identity = (entity_id, id(entity), id(connection), info.device_id, info.key)
            if self.binding != identity:
                self.close()
                from aioesphomeapi.api_pb2 import SensorStateResponse
                self.binding = identity
                first = True

                @callback
                def received(message):
                    nonlocal first
                    if self.closed or self.binding != identity:
                        return
                    if (getattr(message, 'device_id', 0), message.key) != (info.device_id, info.key):
                        return
                    self.packet_count += 1
                    # The first packet on a new connection may be its cached
                    # subscription snapshot. Require a subsequent real report.
                    if first:
                        first = False
                        return
                    self.latest = (float('nan') if message.missing_state else message.state,
                                   self.clock(), '°C')
                    self.changed()

                self.remove = connection.add_message_callback(received, (SensorStateResponse,))
            return self.latest
        except (AttributeError, ImportError, TypeError) as err:
            self.close()
            raise ValueError('ESPHome buffer temperature reporting is unsupported') from err
        except ValueError:
            self.close()
            raise

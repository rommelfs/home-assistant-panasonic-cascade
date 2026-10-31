"""Login, project selection and site selection through Home Assistant."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ApiError, AuthError, CascadeClient, normalize_url
from .const import DOMAIN
from .model import name
from .notifications import mobile_targets, TARGET
from .zinc import reference
from .buffer_charge import DEFAULTS as CHARGE_DEFAULTS, SOURCE_KEYS


def secret_field():
    return selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def login_schema(defaults=None, reauth=False):
    d = defaults or {}
    fields = {}
    if not reauth:
        fields[vol.Required('url', default=d.get('url', 'https://172.17.0.1'))] = str
    fields[vol.Required('username', default=d.get('username', ''))] = str
    # An empty password is permitted for FIN accounts configured without one.
    fields[vol.Optional('password', default='')] = secret_field()
    if not reauth:
        fields[vol.Required('verify_ssl', default=d.get('verify_ssl', True))] = bool
    return vol.Schema(fields)


def project_choices(rows):
    choices = {}
    for row in rows:
        project = row.get('name')
        if not isinstance(project, str):
            ident = reference(row.get('id'))
            project = ident[2:] if ident and ident.startswith('p:') else None
        if not project or project == 'sys' or row.get('routeStatus') not in (None, 'ok'):
            continue
        try:
            CascadeClient._validate_project(project)
        except ValueError:
            continue
        label = row.get('dis') or project
        choices[project] = f'{label} ({project})'
    return choices


class CascadeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                user_input['url'] = normalize_url(user_input['url'])
                self._client = CascadeClient(async_get_clientsession(self.hass, verify_ssl=user_input['verify_ssl']), user_input)
                self._projects = project_choices(await self._client.projects())
                if not self._projects:
                    errors['base'] = 'no_projects'
                else:
                    self._pending = user_input
                    return await self.async_step_project()
            except AuthError:
                errors['base'] = 'invalid_auth'
            except ApiError:
                errors['base'] = 'cannot_connect'
            except ValueError:
                errors['base'] = 'invalid_config'
        return self.async_show_form(step_id='user', data_schema=login_schema(user_input), errors=errors)

    async def async_step_project(self, user_input=None):
        errors = {}
        if user_input is not None:
            project = user_input['project']
            if project not in self._projects:
                errors['base'] = 'invalid_config'
            else:
                try:
                    self._client.project = project
                    self._sites = {reference(s.get('id')): name(s) for s in await self._client.sites() if reference(s.get('id'))}
                    if not self._sites:
                        errors['base'] = 'no_sites'
                    else:
                        self._pending['project'] = project
                        return await self.async_step_site()
                except AuthError:
                    errors['base'] = 'invalid_auth'
                except ApiError:
                    errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='project', data_schema=vol.Schema({vol.Required('project'): vol.In(self._projects)}), errors=errors)

    async def async_step_site(self, user_input=None):
        errors = {}
        if user_input is not None:
            site_id = user_input['site_id']
            if site_id not in self._sites:
                errors['base'] = 'invalid_config'
            else:
                unique = f'{self._pending["url"]}|{self._pending["project"]}|{site_id}'
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f'{self._sites[site_id]} ({self._pending["project"]})',
                                               data={**self._pending, 'site_id': site_id})
        return self.async_show_form(step_id='site', data_schema=vol.Schema({vol.Required('site_id'): vol.In(self._sites)}), errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._async_credentials(self._get_reauth_entry(), user_input, 'reauth_confirm')

    async def async_step_reconfigure(self, user_input=None):
        return await self._async_credentials(self._get_reconfigure_entry(), user_input, 'reconfigure')

    async def _async_credentials(self, entry, user_input, step_id):
        errors = {}
        if user_input is not None:
            try:
                # Existing cookie-based entries can switch to password login here.
                credentials = {'username': user_input['username'], 'password': user_input.get('password', ''),
                               'session_cookie': '', 'bearer_token': '', 'attest_key': ''}
                data = {**entry.data, **entry.options, **credentials}
                client = CascadeClient(async_get_clientsession(self.hass, verify_ssl=data.get('verify_ssl', True)), data)
                if entry.data['project'] not in project_choices(await client.projects()):
                    errors['base'] = 'no_projects'
                elif entry.data['site_id'] not in {reference(s.get('id')) for s in await client.sites()}:
                    errors['base'] = 'no_sites'
                else:
                    return self.async_update_reload_and_abort(entry, data_updates=credentials,
                                                             reason='reconfigure_successful' if step_id == 'reconfigure' else 'reauth_successful')
            except AuthError:
                errors['base'] = 'invalid_auth'
            except ApiError:
                errors['base'] = 'cannot_connect'
            except ValueError:
                errors['base'] = 'invalid_config'
        return self.async_show_form(step_id=step_id, data_schema=login_schema(entry.data, reauth=True), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CascadeOptionsFlow()


class CascadeOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            target = user_input.get('alarm_notify_service', '')
            if target and (not TARGET.fullmatch(target) or not self.hass.services.has_service('notify', target)):
                errors['base'] = 'notification_target_unavailable'
            else:
                data = {**self.config_entry.options, **user_input}
                configure = data.pop('configure_pv_charge', False)
                if configure:
                    self._pending_options = data
                    return await self.async_step_pv_charge()
                return self.async_create_entry(title='', data=data)
        d = {**self.config_entry.options, **(user_input or {})}
        targets = [{'value':'', 'label':'Ausgeschaltet'}]
        available = mobile_targets(self.hass)
        current = d.get('alarm_notify_service', '')
        if current and current not in available:
            available[current] = current + ' (nicht verfügbar)'
        targets.extend({'value':key, 'label':label} for key, label in available.items())
        return self.async_show_form(step_id='init', data_schema=vol.Schema({
            vol.Required('scan_interval', default=d.get('scan_interval', 30)): vol.All(vol.Coerce(int), vol.Range(min=15, max=300)),
            vol.Required('enable_controls', default=d.get('enable_controls', False)): bool,
            vol.Required('configure_pv_charge', default=False): bool,
            vol.Required('use_dhw', default=d.get('use_dhw', True)): bool,
            vol.Required('power_threshold_w', default=d.get('power_threshold_w', 200)): vol.All(vol.Coerce(int), vol.Range(min=50, max=5000)),
            vol.Required('alarm_notify_service', default=d.get('alarm_notify_service', '')): selector.SelectSelector(selector.SelectSelectorConfig(options=targets)),
            vol.Required('alarm_time_sensitive', default=d.get('alarm_time_sensitive', True)): bool,
            vol.Required('verify_ssl', default=d.get('verify_ssl', self.config_entry.data.get('verify_ssl', True))): bool,
        }), errors=errors)


    async def async_step_pv_charge(self, user_input=None):
        errors = {}
        previous = getattr(self, '_pending_options', dict(self.config_entry.options))
        if user_input is not None:
            # Clearing a selector must remove its previous source mapping.
            sources = {f'pv_charge_{key}_sensor': '' for key in SOURCE_KEYS}
            data = {**previous, **sources, **user_input}
            if data.get('pv_charge_enabled') and (not data.get('enable_controls') or not data.get('pv_charge_confirmed')):
                errors['base'] = 'pv_charge_not_confirmed'
            elif data.get('pv_charge_test_without_temperature') and data.get('pv_charge_auto'):
                errors['base'] = 'pv_charge_test_manual_only'
            elif data.get('pv_charge_enabled') and not all(data.get(key) for key in sources
                    if key != 'pv_charge_temperature_sensor' or not data.get('pv_charge_test_without_temperature')):
                errors['base'] = 'pv_charge_missing_sources'
            elif data['pv_charge_stop_w'] >= data['pv_charge_start_w']:
                errors['base'] = 'pv_charge_thresholds'
            else:
                return self.async_create_entry(title='', data=data)
        d = {**CHARGE_DEFAULTS, **previous, **(user_input or {})}
        fields = {}
        for key in ('pv_charge_enabled', 'pv_charge_auto', 'pv_charge_test_without_temperature', 'pv_charge_confirmed',
                    'pv_charge_export_positive', 'pv_charge_discharge_positive'):
            fields[vol.Required(key, default=d[key])] = bool
        for key in SOURCE_KEYS:
            field = f'pv_charge_{key}_sensor'
            marker = vol.Optional(field, description={'suggested_value':d[field]}) if d.get(field) else vol.Optional(field)
            fields[marker] = selector.EntitySelector(selector.EntitySelectorConfig(domain='sensor'))
        for key, low, high, step, unit in (
            ('pv_charge_start_w', 100, 30000, 100, 'W'), ('pv_charge_stop_w', 0, 29900, 100, 'W'),
            ('pv_charge_dwell_s', 15, 600, 15, 's'), ('pv_charge_offset', 1, 10, 1, '°C'),
            ('pv_charge_duration_min', 1, 120, 1, 'min'), ('pv_charge_max_c', 20, 75, 1, '°C'),
            ('pv_charge_max_age_s', 15, 300, 15, 's')):
            fields[vol.Required(key, default=d[key])] = selector.NumberSelector(selector.NumberSelectorConfig(
                min=low, max=high, step=step, unit_of_measurement=unit, mode='box'))
        return self.async_show_form(step_id='pv_charge', data_schema=vol.Schema(fields), errors=errors)

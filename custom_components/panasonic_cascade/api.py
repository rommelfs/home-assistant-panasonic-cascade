"""Asynchronous FIN client using the wire format observed in the HAR files."""
import asyncio
import math
import re
import time
from urllib.parse import urlsplit, urlunsplit
from http.cookies import SimpleCookie

import aiohttp

from .auth import AuthProtocolError, Scram, add_handshake, challenge, encode, hash_name, hmac_header, params
from .diagnostics import queries, convert
from .calculated import add_calculated_cop
from .model import bounds, control_kind, enum_options
from .zinc import MARKER, Number, Ref, REFERENCE, ZincError, parse_grids, quote, reference


class AuthError(Exception):
    """Expired/invalid session or insufficient permissions."""


class ApiError(Exception):
    """Connection or protocol error."""


def normalize_url(raw):
    parsed = urlsplit(raw.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("An HTTPS controller address without credentials is required")
    _ = parsed.port  # Validate the port before saving configuration.
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), "", "", ""))


class CascadeClient:
    def __init__(self, session, config):
        self.session = session
        self.url = normalize_url(config["url"])
        self.project = config.get("project", "sys")
        self._validate_project(self.project)
        self.verify_ssl = config.get("verify_ssl", True)
        self.username = config.get("username", "").strip()
        self.password = config.get("password", "")
        self.headers = {"Content-Type": "text/zinc", "Accept": "text/zinc", "Origin": self.url}
        cookie = config.get("session_cookie", "").strip()
        bearer = config.get("bearer_token", "").strip()
        attest = config.get("attest_key", "").strip()
        if not self.username and not cookie and not bearer:
            raise ValueError("Username or legacy session credential required")
        if any("\r" in v or "\n" in v for v in (cookie, bearer, attest, self.username)):
            raise ValueError("Invalid credential format")
        if cookie:
            self.headers["Cookie"] = cookie
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"
        if attest:
            self.headers["SkyArc-Attest-Key"] = attest
        self.cookies = SimpleCookie()
        self.authenticated = not bool(self.username)
        self.lock = asyncio.Lock()
        self.use_dhw = config.get("use_dhw", True)
        self._detail_cache = {}
        self._details_at = {}

    @staticmethod
    def _validate_project(project):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project):
            raise ValueError("Invalid project")

    async def _request(self, method, path, headers=None, data=None):
        request_headers = dict(self.headers if headers is None else headers)
        if self.cookies:
            request_headers['Cookie'] = '; '.join(f'{key}={morsel.coded_value}' for key, morsel in self.cookies.items())
        try:
            request = self.session.get if method == 'GET' else self.session.post
            kwargs = dict(headers=request_headers, ssl=self.verify_ssl, allow_redirects=False,
                          timeout=aiohttp.ClientTimeout(total=30))
            if data is not None:
                kwargs['data'] = data
            async with request(self.url + path, **kwargs) as response:
                # Keep per-client cookies in memory, including for literal IP hosts.
                # Never rely on Home Assistant's shared cookie jar.
                response_headers = {k.lower(): v for k, v in getattr(response, 'headers', {}).items()}
                raw_headers = getattr(response, 'headers', {})
                cookie_headers = raw_headers.getall('Set-Cookie', []) if hasattr(raw_headers, 'getall') else ([raw_headers['Set-Cookie']] if 'Set-Cookie' in raw_headers else [])
                for raw in cookie_headers:
                    incoming = SimpleCookie(); incoming.load(raw)
                    for key, morsel in incoming.items():
                        if morsel['max-age'] == '0':
                            self.cookies.pop(key, None)
                        else:
                            self.cookies[key] = morsel.value
                return response.status, response_headers, await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ApiError("Controller connection failed") from err

    async def login(self):
        async with self.lock:
            await self._login()

    async def _login(self):
        if not self.username:
            raise AuthError('No username configured for session renewal')
        self.authenticated = False
        self.cookies.clear()
        for key in ('Cookie', 'Authorization', 'SkyArc-Attest-Key'):
            self.headers.pop(key, None)
        try:
            status, headers, _ = await self._request('GET', '/user/auth', {'Authorization': 'HELLO username=' + encode(self.username)})
            scram = None
            if status == 401:
                scheme, info = challenge(headers.get('www-authenticate', ''))
                if scheme == 'scram':
                    algorithm = hash_name(info.get('hash', ''))
                    scram = Scram(self.username, self.password, algorithm)
                    first = add_handshake('SCRAM data=' + scram.first(), info)
                    status, headers, _ = await self._request('GET', '/user/auth', {'Authorization': first})
                    if status != 401:
                        raise AuthError('SCRAM challenge failed')
                    next_scheme, next_info = challenge(headers.get('www-authenticate', ''))
                    if next_scheme != 'scram' or hash_name(next_info.get('hash', info['hash'])) != algorithm:
                        raise AuthError('SCRAM scheme changed')
                    # PBKDF2 may be costly; keep it off HA's event loop.
                    final = await asyncio.to_thread(scram.final, next_info.get('data', ''))
                    auth_header = add_handshake('SCRAM data=' + final, next_info)
                elif scheme == 'hmac':
                    auth_header = hmac_header(self.username, self.password, info)
                elif scheme in ('x-plaintext', 'plaintext'):
                    auth_header = add_handshake(f'{scheme} username={encode(self.username)}, password={encode(self.password)}', info)
                else:
                    raise AuthError('Unsupported FIN authentication scheme')
                status, headers, _ = await self._request('GET', '/user/auth', {'Authorization': auth_header})
            if status != 200:
                raise AuthError('Username/password authentication failed')
            auth_info = params(headers['authentication-info']) if headers.get('authentication-info') else {}
            if scram is not None and auth_info.get('data'):
                scram.verify(auth_info['data'])
            if auth_info.get('authtoken'):
                self.headers['Authorization'] = 'BEARER authToken=' + auth_info['authtoken']
            if not self.cookies and 'Authorization' not in self.headers:
                raise AuthError('FIN did not issue a usable session')
            # finstack.GetAttestKey() uses this response header, not a fixed key.
            status, headers, text = await self._request('GET', '/finStackAuth')
            if status != 200 or text.lstrip().lower().startswith(('<html', '<!doctype')):
                raise AuthError('FIN session validation failed')
            if headers.get('fin-stack-auth'):
                self.headers['SkyArc-Attest-Key'] = headers['fin-stack-auth']
            self.authenticated = True
        except AuthProtocolError as err:
            raise AuthError('FIN authentication protocol failed') from err
        finally:
            if not self.authenticated:
                self.cookies.clear()
                for key in ('Cookie', 'Authorization', 'SkyArc-Attest-Key'):
                    self.headers.pop(key, None)

    async def eval(self, expression, project=None):
        return (await self._eval_request([expression], "eval", project))[0]

    async def eval_all(self, expressions):
        if not expressions:
            return []
        return await self._eval_request(expressions, "evalAll")

    async def _eval_request(self, expressions, operation, project=None):
        project = project or self.project
        self._validate_project(project)
        payload = ('ver:"3.0"\nexpr\n' + ''.join(quote(expr) + '\n' for expr in expressions)).encode()
        async with self.lock:
            if not self.authenticated:
                await self._login()
            # Retry only an explicit expired/rejected session, at most once.
            for attempt in range(2):
                status, headers, text = await self._request('POST', f'/api/{project}/{operation}', data=payload)
                auth_failure = (status in (301, 302, 303, 307, 308, 401) or
                                text.lstrip().lower().startswith(('<!doctype', '<html')) or
                                bool(re.search(r'errType:"[^"\n]*(?:AuthErr|AuthenticationErr)', text)))
                if auth_failure and self.username and attempt == 0:
                    await self._login()
                    continue
                if auth_failure or status == 403:
                    raise AuthError('Session expired or access denied')
                if status != 200:
                    raise ApiError(f'FIN HTTP status {status}')
                try:
                    grids = parse_grids(text, allow_errors=operation == "evalAll")
                except ZincError as err:
                    raise ApiError('FIN response could not be decoded') from err
                if len(grids) != len(expressions):
                    raise ApiError('Unexpected number of response grids')
                return grids
        raise AuthError('Session renewal failed')

    async def projects(self):
        return await self.eval('secureEval(projs())', project='sys')

    async def read(self, filter_text):
        # Matches parseFilter(...).readAll() in the captured application.
        return await self.eval(f"parseFilter({quote(filter_text)}).readAll()")

    async def active_alarms(self, site_id):
        if not REFERENCE.fullmatch(site_id):
            raise ValueError("Invalid site reference")
        return await self.eval(f'panEval(`/alarmList/table/alarms`, {{target:@{site_id}}})')

    async def read_point(self, ident, site_id):
        if not REFERENCE.fullmatch(ident) or not REFERENCE.fullmatch(site_id):
            raise ValueError("Invalid point reference")
        rows = await self.read(f"id==@{ident} and siteRef==@{site_id}")
        if len(rows) != 1 or reference(rows[0].get("id")) != ident:
            raise ApiError("Zone point could not be read")
        return rows[0]

    async def sites(self):
        return await self.read('siteModelId=="_site:site"')

    async def snapshot(self, site_id):
        if not REFERENCE.fullmatch(site_id):
            raise ValueError("Invalid site reference")
        rows = await self.read(f"panCascadeControl and (point or equip) and siteRef==@{site_id}")
        result = {reference(row["id"]): row for row in rows if reference(row.get("id"))}
        for key, label, path in (
            ("generatedPower", "Generated thermal power", "totalGeneratedEnergy"),
            ("consumedPower", "Consumed electrical power", "totalConsumedEnergy"),
        ):
            # Despite the endpoint names, the captured values are kW, not kWh.
            try:
                summary = await self.eval(f"panEval(`/plantOverview/units/energy/{path}`, {{siteId:@{site_id}}})")
                raw = summary[0].get("val") if summary else None
            except (ApiError, AuthError):
                raw = None
            ident = f"summary:{key}"
            result[ident] = {"id": Ref(ident, label), "point": MARKER,
                             "kind": "Number", "curVal": raw,
                             "curStatus": "ok" if isinstance(raw, Number) else "fault",
                             "siteRef": Ref(site_id), "unit": raw.unit if isinstance(raw, Number) else "kW"}
        await self._enrich(result, site_id)
        add_calculated_cop(result, site_id)
        return result

    async def _enrich(self, result, site_id):
        now = time.monotonic()
        details = site_id not in self._details_at or now - self._details_at[site_id] >= 300
        specs = queries(site_id, result, details)
        try:
            grids = await self.eval_all([spec[5] for spec in specs])
        except (ApiError, AuthError):
            # Missing optional views/permissions never turn off core point polling.
            grids = [None] * len(specs)
        cached = self._detail_cache.setdefault(site_id, {})
        if details:
            cached.clear()
            self._details_at[site_id] = now
        for spec, grid in zip(specs, grids):
            converted = convert(spec, grid, site_id, result, self.use_dhw)
            if spec[6] in ("details", "history"):
                cached.update(converted)
            else:
                result.update(converted)
        result.update({ident: row for ident, row in cached.items()
                       if not row.get("equipRef") or reference(row["equipRef"]) in result})

    async def set_default(self, row, new_value):
        kind = control_kind(row)
        ident = reference(row.get("id"))
        if not kind or not ident or not REFERENCE.fullmatch(ident):
            raise ValueError("Control is not supported")
        if kind == "switch":
            if type(new_value) is not bool:
                raise ValueError("Expected boolean")
            literal = "true" if new_value else "false"
        elif kind == "select":
            if new_value not in enum_options(row):
                raise ValueError("Invalid option")
            literal = quote(new_value)
        else:
            low, high = bounds(row)
            if type(new_value) not in (int, float) or not math.isfinite(new_value) or not low <= new_value <= high:
                raise ValueError("Setpoint outside supported range")
            literal = f"{new_value:g}°C"
        # Advertised Set Default action. No priority override, no emergency action.
        await self.eval(f"pointSetDef(@{ident}, {literal})")

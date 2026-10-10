"""Asynchronous FIN client using the wire format observed in the HAR files."""
import asyncio
import math
import re
from urllib.parse import urlsplit, urlunsplit

import aiohttp

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
        self.project = config["project"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.project):
            raise ValueError("Invalid project")
        self.verify_ssl = config.get("verify_ssl", True)
        self.headers = {"Content-Type": "text/zinc", "Accept": "text/zinc", "Origin": self.url}
        # Credentials are supplied through HA configuration, never copied from HAR.
        cookie = config.get("session_cookie", "").strip()
        bearer = config.get("bearer_token", "").strip()
        attest = config.get("attest_key", "").strip()
        if not cookie and not bearer:
            raise ValueError("A session cookie or bearer token is required")
        if any("\r" in s or "\n" in s for s in (cookie, bearer, attest)):
            raise ValueError("Invalid credential format")
        if cookie:
            self.headers["Cookie"] = cookie
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"
        if attest:
            self.headers["SkyArc-Attest-Key"] = attest
        self.lock = asyncio.Lock()

    async def eval(self, expression):
        payload = 'ver:"3.0"\nexpr\n' + quote(expression) + '\n'
        try:
            async with self.lock:
                async with self.session.post(
                    f"{self.url}/api/{self.project}/eval", data=payload.encode(),
                    headers=self.headers, ssl=self.verify_ssl, allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status in (301, 302, 303, 307, 308, 401, 403):
                        raise AuthError("Session expired or access denied")
                    if response.status != 200:
                        raise ApiError(f"FIN HTTP status {response.status}")
                    text = await response.text()
            if text.lstrip().lower().startswith(("<!doctype", "<html")):
                raise AuthError("Login required")
            grids = parse_grids(text)
            if len(grids) != 1:
                raise ApiError("Unexpected number of response grids")
            return grids[0]
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ApiError("Controller connection failed") from err
        except ZincError as err:
            raise ApiError("FIN response could not be decoded") from err

    async def read(self, filter_text):
        # Matches parseFilter(...).readAll() in the captured application.
        return await self.eval(f"parseFilter({quote(filter_text)}).readAll()")

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
            except ApiError:
                raw = None
            ident = f"summary:{key}"
            result[ident] = {"id": Ref(ident, label), "point": MARKER,
                             "kind": "Number", "curVal": raw,
                             "curStatus": "ok" if isinstance(raw, Number) else "fault",
                             "siteRef": Ref(site_id), "unit": raw.unit if isinstance(raw, Number) else "kW"}
        return result

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

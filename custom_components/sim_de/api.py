"""API client for the sim.de Servicewelt.

sim.de (a Drillisch Online brand) publishes no API, so this client drives the
same session-cookie login the browser uses:

1. ``GET /start`` renders the login form and a per-session Symfony CSRF token.
2. ``POST /public/login_check`` exchanges the credentials for a session cookie.
3. The tariff and usage pages are then plain authenticated ``GET`` requests.

Every request is read-only.  Nothing here changes a tariff, books an option or
sends money.  Cookies and tokens are session-specific and never persisted.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from .const import (
    BASE_URL,
    PATH_DATA_USAGE,
    PATH_LOGIN,
    PATH_OVERVIEW,
    PATH_START,
    PATH_TARIFF_INFO,
    REQUEST_TIMEOUT,
)
from .models import Plan, Usage, build_data, find_csrf_token, parse_plan, parse_usage_page

_LOGGER = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
}

# Present on the login page and gone once the session is authenticated.
_LOGIN_MARKERS = ("UserLoginType[password]", 'name="UserLoginType')


class SimDeError(Exception):
    """Base error for the sim.de client."""


class SimDeAuthError(SimDeError):
    """The credentials were rejected, or the session is no longer valid."""


class SimDeConnectionError(SimDeError):
    """The Servicewelt could not be reached."""


class SimDeParseError(SimDeError):
    """A page loaded but did not contain what the integration expects."""


class SimDeAPI:
    """Read the tariff and data usage of one sim.de account."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize.

        ``session`` must be a *dedicated* client session: the login is carried
        by a cookie, so its cookie jar cannot be shared with the rest of Home
        Assistant.
        """
        self._username = username
        self._password = password
        self._session = session
        self._authenticated = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _url(path: str) -> str:
        return BASE_URL + path

    @staticmethod
    def _is_login_page(html: str) -> bool:
        """Return True when a page is the login form rather than content."""
        return any(marker in html for marker in _LOGIN_MARKERS)

    async def _request(self, method: str, path: str, **kwargs) -> str:
        """Perform one request and return its body."""
        try:
            async with self._session.request(
                method,
                self._url(path),
                headers=_HEADERS,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                **kwargs,
            ) as response:
                if response.status == 401:
                    raise SimDeAuthError("Servicewelt rejected the session")

                if response.status >= 400:
                    raise SimDeConnectionError(
                        f"{path} answered with HTTP {response.status}"
                    )

                return await response.text()
        except asyncio.TimeoutError as err:
            raise SimDeConnectionError(f"Timeout while loading {path}") from err
        except aiohttp.ClientError as err:
            raise SimDeConnectionError(f"Cannot reach {path}: {err}") from err

    async def async_login(self) -> None:
        """Sign in and keep the session cookie.

        The CSRF token is generated per session, so it is read from the login
        page immediately before the POST.
        """
        async with self._lock:
            self._authenticated = False

            login_page = await self._request("GET", PATH_START)
            token = find_csrf_token(login_page)

            if not token:
                raise SimDeParseError(
                    "No CSRF token on the login page - the Servicewelt layout "
                    "may have changed"
                )

            await self._request(
                "POST",
                PATH_LOGIN,
                data={
                    "UserLoginType[alias]": self._username,
                    "UserLoginType[password]": self._password,
                    "UserLoginType[logindata]": "",
                    "UserLoginType[_token]": token,
                },
                allow_redirects=True,
            )

            # A failed login lands back on the form instead of raising.
            check = await self._request("GET", PATH_DATA_USAGE)

            if self._is_login_page(check):
                raise SimDeAuthError("Invalid username or password")

            self._authenticated = True

    async def _async_get_page(self, path: str) -> str:
        """Load an authenticated page, signing in again if the session died."""
        if not self._authenticated:
            await self.async_login()

        html = await self._request("GET", path)

        if not self._is_login_page(html):
            return html

        _LOGGER.debug("Session expired while loading %s, signing in again", path)
        self._authenticated = False
        await self.async_login()

        html = await self._request("GET", path)

        if self._is_login_page(html):
            raise SimDeAuthError("Could not keep an authenticated session")

        return html

    async def _async_get_pages(self) -> dict[str, str]:
        """Load the three pages one poll needs, each exactly once."""
        return {
            "tariff_info": await self._async_get_page(PATH_TARIFF_INFO),
            "overview": await self._async_get_page(PATH_OVERVIEW),
            "usage": await self._async_get_page(PATH_DATA_USAGE),
        }

    @staticmethod
    def _usage_from(html: str) -> tuple[Usage, Usage]:
        """Parse both months, insisting that at least one carries figures."""
        current, previous = parse_usage_page(html)

        if current.used_gb is None and previous.used_gb is None:
            raise SimDeParseError(
                "No usage figures on the data-usage page - the Servicewelt "
                "layout may have changed"
            )

        return current, previous

    async def async_get_plan(self) -> Plan:
        """Return the tariff behind the SIM."""
        return parse_plan(await self._async_get_pages())

    async def async_get_usage(self) -> tuple[Usage, Usage]:
        """Return the current and previous month's data usage."""
        return self._usage_from(await self._async_get_page(PATH_DATA_USAGE))

    async def async_get_status(self) -> dict:
        """Return plan and usage in the shape the entities read.

        One poll is three GETs: the two tariff pages and the usage page.
        """
        pages = await self._async_get_pages()
        current, previous = self._usage_from(pages["usage"])

        return build_data(parse_plan(pages), current, previous)

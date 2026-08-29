"""Tests for the sim.de client: request shape, session handling, errors."""
from __future__ import annotations

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from sim_de.api import (
    SimDeAPI,
    SimDeAuthError,
    SimDeConnectionError,
    SimDeParseError,
)

from fixtures import (
    CSRF_TOKEN,
    LOGIN_PAGE,
    MSISDN,
    OVERVIEW_PAGE,
    PASSWORD,
    TARIFF_INFO_PAGE,
    TARIFF_NAME,
    USAGE_PAGE,
    USERNAME,
    usage_page,
)

SESSION_COOKIE = "SIMDESESSION"


class FakeServicewelt:
    """A stand-in for service.sim.de that only accepts a real login."""

    def __init__(self, login_page: str = LOGIN_PAGE, **overrides) -> None:
        self.requests: list[tuple[str, str]] = []
        self.logins = 0
        self.expire_after: int | None = None
        self.login_page = login_page
        self.pages = {
            "/mytariff/tariff/showTariffInfo": TARIFF_INFO_PAGE,
            "/mytariff/overview": OVERVIEW_PAGE,
            "/mytariff/invoice/showGprsDataUsage": USAGE_PAGE,
            **overrides,
        }

    def _authenticated(self, request: web.Request) -> bool:
        """A session is valid until ``expire_after`` further page loads."""
        if request.cookies.get(SESSION_COOKIE) != "valid":
            return False

        if self.expire_after is None:
            return True

        self.expire_after -= 1
        return self.expire_after >= 0

    async def start(self, request: web.Request) -> web.Response:
        self.requests.append(("GET", request.path))
        return web.Response(text=self.login_page, content_type="text/html")

    async def login_check(self, request: web.Request) -> web.Response:
        self.requests.append(("POST", request.path))
        self.logins += 1

        form = await request.post()
        response = web.Response(text="", content_type="text/html")

        if (
            form.get("UserLoginType[alias]") == USERNAME
            and form.get("UserLoginType[password]") == PASSWORD
            and form.get("UserLoginType[_token]") == CSRF_TOKEN
        ):
            # A fresh login starts a session that does not expire again.
            self.expire_after = None
            response.set_cookie(SESSION_COOKIE, "valid")

        return response

    async def page(self, request: web.Request) -> web.Response:
        self.requests.append(("GET", request.path))

        if not self._authenticated(request):
            # The Servicewelt answers with the login form, not a 401.
            return web.Response(text=LOGIN_PAGE, content_type="text/html")

        return web.Response(
            text=self.pages[request.path],
            content_type="text/html",
        )

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/start", self.start)
        app.router.add_post("/public/login_check", self.login_check)

        for path in self.pages:
            app.router.add_get(path, self.page)

        return app


@pytest.fixture
async def servicewelt(monkeypatch):
    """Run the fake Servicewelt and point the client's base URL at it."""

    async def _start(**overrides):
        fake = FakeServicewelt(**overrides)
        server = TestServer(fake.app())
        await server.start_server()

        base = str(server.make_url("")).rstrip("/")
        monkeypatch.setattr("sim_de.api.BASE_URL", base)

        fake.server = server
        return fake

    started: list[FakeServicewelt] = []

    async def _factory(**overrides):
        fake = await _start(**overrides)
        started.append(fake)
        return fake

    yield _factory

    for fake in started:
        await fake.server.close()


async def _client(username: str = USERNAME, password: str = PASSWORD):
    """Build a client with its own cookie jar.

    The jar has to be ``unsafe`` because the test server is reached by IP;
    aiohttp drops cookies from IP hosts otherwise.
    """
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    return SimDeAPI(username, password, session=session), session


async def test_login_and_read_status(servicewelt):
    """A successful login reads the plan and both months in three GETs."""
    fake = await servicewelt()
    api, session = await _client()

    try:
        data = await api.async_get_status()
    finally:
        await session.close()

    assert data["plan"].name == TARIFF_NAME
    assert data["plan"].msisdn == MSISDN
    assert data["current_month"].used_gb == 15.58
    assert data["previous_month"].used_gb == 16.97

    # One login, then exactly one GET per page.
    assert fake.logins == 1
    page_loads = [path for method, path in fake.requests if method == "GET"]
    assert page_loads.count("/mytariff/invoice/showGprsDataUsage") == 2  # login check + poll
    assert page_loads.count("/mytariff/overview") == 1
    assert page_loads.count("/mytariff/tariff/showTariffInfo") == 1


async def test_wrong_password_raises_auth_error(servicewelt):
    """The Servicewelt returns the login form again; that is an auth failure."""
    await servicewelt()
    api, session = await _client(password="wrong")

    try:
        with pytest.raises(SimDeAuthError):
            await api.async_login()
    finally:
        await session.close()


async def test_expired_session_is_renewed(servicewelt):
    """A session that dies mid-poll is re-established once, transparently."""
    fake = await servicewelt()
    api, session = await _client()

    try:
        await api.async_login()
        fake.expire_after = 0  # the next page load lands on the login form

        data = await api.async_get_status()
    finally:
        await session.close()

    assert data["plan"].name == TARIFF_NAME
    assert fake.logins == 2


async def test_missing_csrf_token_raises_parse_error(servicewelt):
    """A login page without a token means the layout changed."""
    await servicewelt(login_page="<html><body>Wartungsarbeiten</body></html>")
    api, session = await _client()

    try:
        with pytest.raises(SimDeParseError):
            await api.async_login()
    finally:
        await session.close()


async def test_usage_page_without_figures_raises_parse_error(servicewelt):
    """An empty usage page is reported rather than published as None."""
    await servicewelt(
        **{
            "/mytariff/invoice/showGprsDataUsage": usage_page(
                current="keine Daten",
                current_allowance="keine Daten",
                previous="keine Daten",
                previous_allowance="keine Daten",
                previous_extra="",
            )
        }
    )
    api, session = await _client()

    try:
        with pytest.raises(SimDeParseError):
            await api.async_get_status()
    finally:
        await session.close()


async def test_unreachable_host_raises_connection_error(monkeypatch):
    """A dead host surfaces as a connection error, not a bare aiohttp one."""
    monkeypatch.setattr("sim_de.api.BASE_URL", "http://127.0.0.1:1")
    api, session = await _client()

    try:
        with pytest.raises(SimDeConnectionError):
            await api.async_login()
    finally:
        await session.close()


async def test_password_is_not_logged(servicewelt, caplog):
    """The password never reaches the log, even at debug level."""
    import logging

    await servicewelt()
    api, session = await _client()

    try:
        with caplog.at_level(logging.DEBUG):
            await api.async_get_status()
    finally:
        await session.close()

    assert PASSWORD not in caplog.text

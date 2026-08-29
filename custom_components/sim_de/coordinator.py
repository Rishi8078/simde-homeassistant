"""DataUpdateCoordinator for sim.de."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SimDeAPI, SimDeAuthError, SimDeError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SimDeDataUpdateCoordinator(DataUpdateCoordinator):
    """Fetch the tariff and both months of data usage.

    One update loads three pages for the whole integration; entities only read
    the result.  The Servicewelt updates its counters a few times a day, so the
    default interval is deliberately long.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: SimDeAPI,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the Servicewelt pages and parse them."""
        try:
            return await self.api.async_get_status()
        except SimDeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SimDeError as err:
            raise UpdateFailed(f"Error reading the Servicewelt: {err}") from err
        except Exception as err:  # pylint: disable=broad-except
            raise UpdateFailed(f"Error reading the Servicewelt: {err}") from err

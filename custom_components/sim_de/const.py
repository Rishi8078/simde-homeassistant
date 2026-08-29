"""Constants for the sim.de integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "sim_de"

CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_SCAN_INTERVAL: Final = "scan_interval"

# The Servicewelt refreshes its usage counters a few times a day, so there is
# nothing to gain from polling often.  Half an hour is already generous.
DEFAULT_SCAN_INTERVAL: Final = 1800
MIN_SCAN_INTERVAL: Final = 300

BASE_URL: Final = "https://service.sim.de"

PATH_START: Final = "/start"
PATH_LOGIN: Final = "/public/login_check"
PATH_OVERVIEW: Final = "/mytariff/overview"
PATH_TARIFF_INFO: Final = "/mytariff/tariff/showTariffInfo"
PATH_DATA_USAGE: Final = "/mytariff/invoice/showGprsDataUsage"

REQUEST_TIMEOUT: Final = 30

# Ids of the two tabs on the data-usage page.
TAB_CURRENT: Final = "tab-cur"
TAB_PREVIOUS: Final = "tab-mon"

# Labels used by the Servicewelt key/value blocks (the pages are German only).
LABEL_TARIFF: Final = "Tarif"
LABEL_NETWORK: Final = "Mobilfunknetz"
LABEL_CUSTOMER_NUMBER: Final = "Kundennummer"
LABEL_MSISDN: Final = "Rufnummer"
LABEL_BRAND: Final = "Marke"
LABEL_BILLING: Final = "Abrechnungsart"
LABEL_MIN_TERM: Final = "Mindestvertragslaufzeit"
LABEL_NOTICE_PERIOD: Final = "Kündigungsfrist"

ATTR_ALLOWANCE_GB: Final = "allowance_gb"
ATTR_USED_GB: Final = "used_gb"
ATTR_REMAINING_GB: Final = "remaining_gb"
ATTR_AUTO_TOPUP: Final = "auto_topup"
ATTR_TARIFF_CODE: Final = "tariff_code"
ATTR_PACKAGE_CODE: Final = "package_code"
ATTR_NETWORK: Final = "network"
ATTR_CUSTOMER_NUMBER: Final = "customer_number"
ATTR_MSISDN: Final = "phone_number"
ATTR_BILLING: Final = "billing"
ATTR_MIN_TERM: Final = "minimum_term"
ATTR_NOTICE_PERIOD: Final = "notice_period"

KEY_PLAN: Final = "plan"
KEY_CURRENT: Final = "current_month"
KEY_PREVIOUS: Final = "previous_month"

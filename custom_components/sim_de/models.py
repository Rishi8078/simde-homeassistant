"""Parsing of the sim.de Servicewelt pages.

The Servicewelt has no public API, so the integration reads the same HTML a
browser would.  Everything in this module is pure: it turns page source into
dataclasses and never touches the network, which is what makes it testable
without Home Assistant.

Two shapes are extracted:

* the labelled key/value blocks (``c-key_value_container``) that carry the
  tariff name, network and contract details;
* the two data-usage tabs, ``#tab-cur`` (current month) and ``#tab-mon``
  (previous month), each holding a sentence like
  ``15,58 GB von 16,00 GB verbraucht``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from .const import (
    ATTR_ALLOWANCE_GB,
    ATTR_AUTO_TOPUP,
    ATTR_BILLING,
    ATTR_CUSTOMER_NUMBER,
    ATTR_MIN_TERM,
    ATTR_MSISDN,
    ATTR_NETWORK,
    ATTR_NOTICE_PERIOD,
    ATTR_PACKAGE_CODE,
    ATTR_REMAINING_GB,
    ATTR_TARIFF_CODE,
    ATTR_USED_GB,
    KEY_CURRENT,
    KEY_PLAN,
    KEY_PREVIOUS,
    LABEL_BILLING,
    LABEL_BRAND,
    LABEL_CUSTOMER_NUMBER,
    LABEL_MIN_TERM,
    LABEL_MSISDN,
    LABEL_NETWORK,
    LABEL_NOTICE_PERIOD,
    LABEL_TARIFF,
    TAB_CURRENT,
    TAB_PREVIOUS,
)

# "15,58 GB von 16,00 GB verbraucht"
_USED_OF_ALLOWANCE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(GB|MB|KB)\s*"
    r"von\s+(\d+(?:[.,]\d+)?)\s*(GB|MB|KB)\s*"
    r"verbraucht",
    re.IGNORECASE,
)
_VALUE_WITH_UNIT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(GB|MB|KB)\b", re.IGNORECASE)

# "(davon 3 x 300,00 MB Datenautomatik)"
_AUTO_TOPUP = re.compile(r"\(([^)]*Datenautomatik[^)]*)\)", re.IGNORECASE)

_UNIT_TO_GB = {"gb": 1.0, "mb": 1 / 1024.0, "kb": 1 / (1024.0 * 1024.0)}


class _ElementTextParser(HTMLParser):
    """Collect the text inside the first element carrying ``element_id``."""

    def __init__(self, element_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self._id = element_id
        self._tag: str | None = None
        self._depth = 0
        self._parts: list[str] = []
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return

        if self._tag is None:
            if dict(attrs).get("id") == self._id:
                self._tag = tag
                self._depth = 0
        elif tag == self._tag:
            # A nested element of the same kind - remember to skip its close.
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._done or self._tag is None or tag != self._tag:
            return

        if self._depth == 0:
            self._done = True
        else:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._tag is not None and not self._done:
            self._parts.append(data)

    @property
    def text(self) -> str:
        return " ".join("".join(self._parts).split())


class _KeyValueParser(HTMLParser):
    """Read the ``label -> value`` rows the Servicewelt renders as divs.

        <div class="c-key_value_container">
          <div class="row">
            <div class="... font-weight-bold">Tarif</div>
            <div class="...">Allnet Flat 10 + 6 GB</div>
    """

    CONTAINER_CLASS = "c-key_value_container"
    ROW_CLASS = "row"

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pairs: dict[str, str] = {}
        self._depth = 0
        self._container: int | None = None
        self._row: int | None = None
        self._cell: int | None = None
        self._cells: list[str] = []
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return

        classes = dict(attrs).get("class", "").split()
        depth = self._depth
        self._depth += 1

        if self._container is None:
            if self.CONTAINER_CLASS in classes:
                self._container = depth
        elif self._row is None:
            if self.ROW_CLASS in classes:
                self._row = depth
                self._cells = []
        elif self._cell is None and depth == self._row + 1:
            self._cell = depth
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return

        self._depth -= 1
        depth = self._depth

        if self._cell is not None and depth == self._cell:
            text = " ".join("".join(self._buffer).split())
            if text:
                self._cells.append(text)
            self._cell = None
            self._buffer = []
        elif self._row is not None and depth == self._row:
            if len(self._cells) >= 2:
                # First row wins: the same label can repeat further down.
                self.pairs.setdefault(self._cells[0], self._cells[1])
            self._row = None
            self._cells = []
        elif self._container is not None and depth == self._container:
            self._container = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._buffer.append(data)


class _HiddenInputParser(HTMLParser):
    """Collect the hidden form fields of a page (the CSRF token lives here)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return

        attributes = {key: (value or "") for key, value in attrs}

        if attributes.get("type") == "hidden" and attributes.get("name"):
            self.fields[attributes["name"]] = attributes.get("value", "")


def element_text(html: str, element_id: str) -> str:
    """Return the collapsed text of the element with ``element_id``."""
    parser = _ElementTextParser(element_id)
    parser.feed(html)
    return parser.text


def parse_key_values(html: str) -> dict[str, str]:
    """Return the ``label -> value`` pairs of a Servicewelt page."""
    parser = _KeyValueParser()
    parser.feed(html)
    return parser.pairs


def hidden_inputs(html: str) -> dict[str, str]:
    """Return the hidden form fields of a page."""
    parser = _HiddenInputParser()
    parser.feed(html)
    return parser.fields


def find_csrf_token(html: str) -> str | None:
    """Return the Symfony CSRF token of the login form, if present."""
    for name, value in hidden_inputs(html).items():
        if "_token" in name.lower() and value:
            return value

    return None


def parse_german_number(value: str) -> float:
    """Convert a German-formatted number to a float.

    German writes the thousands separator as a dot and the decimal separator
    as a comma, so ``15,58`` is 15.58 and ``3.840`` is 3840 - never 3.84.
    """
    value = re.sub(r"[^\d,.\-]", "", value.replace("\xa0", " ").strip())

    return float(value.replace(".", "").replace(",", "."))


def to_gb(value: str, unit: str) -> float:
    """Convert a German number plus its unit to gigabytes."""
    return parse_german_number(value) * _UNIT_TO_GB[unit.lower()]


@dataclass
class Usage:
    """Data usage of one billing month."""

    period: str
    used_gb: float | None = None
    allowance_gb: float | None = None
    remaining_gb: float | None = None
    usage_percent: float | None = None
    auto_topup: str | None = None

    @property
    def over_allowance(self) -> bool:
        """Return True when the month used more than its allowance."""
        if self.used_gb is None or self.allowance_gb is None:
            return False

        return self.used_gb > self.allowance_gb

    def as_attributes(self) -> dict[str, Any]:
        """Return the figures that ride along as entity attributes."""
        attributes: dict[str, Any] = {
            ATTR_USED_GB: self.used_gb,
            ATTR_ALLOWANCE_GB: self.allowance_gb,
            ATTR_REMAINING_GB: self.remaining_gb,
        }

        if self.auto_topup:
            attributes[ATTR_AUTO_TOPUP] = self.auto_topup

        return {key: value for key, value in attributes.items() if value is not None}


@dataclass
class Plan:
    """The tariff behind the SIM."""

    name: str | None = None
    tariff_code: str | None = None
    package_code: str | None = None
    network: str | None = None
    customer_number: str | None = None
    msisdn: str | None = None
    details: dict[str, str] = field(default_factory=dict)

    def as_attributes(self) -> dict[str, Any]:
        """Return the plan details that ride along as entity attributes."""
        attributes = {
            ATTR_TARIFF_CODE: self.tariff_code,
            ATTR_PACKAGE_CODE: self.package_code,
            ATTR_NETWORK: self.network,
            ATTR_CUSTOMER_NUMBER: self.customer_number,
            ATTR_MSISDN: self.msisdn,
            ATTR_BILLING: self.details.get(LABEL_BILLING),
            ATTR_MIN_TERM: self.details.get(LABEL_MIN_TERM),
            ATTR_NOTICE_PERIOD: self.details.get(LABEL_NOTICE_PERIOD),
        }

        return {key: value for key, value in attributes.items() if value}


def parse_usage(text: str, period: str) -> Usage:
    """Parse one usage tab.

    The tab reads ``15,58 GB von 16,00 GB verbraucht``, optionally followed by
    ``(davon 3 x 300,00 MB Datenautomatik)`` once the automatic top-up has
    bought extra volume.
    """
    used: float | None = None
    allowance: float | None = None

    match = _USED_OF_ALLOWANCE.search(text)

    if match:
        used = to_gb(match.group(1), match.group(2))
        allowance = to_gb(match.group(3), match.group(4))
    else:
        # Fall back to the first two figures on the tab.
        values = _VALUE_WITH_UNIT.findall(text)

        if len(values) >= 2:
            used = to_gb(*values[0])
            allowance = to_gb(*values[1])

    percent = None
    remaining = None

    if used is not None and allowance:
        percent = round(used / allowance * 100.0, 1)

    if used is not None and allowance is not None:
        remaining = round(max(allowance - used, 0.0), 2)

    auto_topup = None
    topup_match = _AUTO_TOPUP.search(text)

    if topup_match:
        auto_topup = topup_match.group(1).strip()

    return Usage(
        period=period,
        used_gb=None if used is None else round(used, 2),
        allowance_gb=None if allowance is None else round(allowance, 2),
        remaining_gb=remaining,
        usage_percent=percent,
        auto_topup=auto_topup,
    )


def parse_usage_page(html: str) -> tuple[Usage, Usage]:
    """Parse the current and previous month from the data-usage page."""
    return (
        parse_usage(element_text(html, TAB_CURRENT), KEY_CURRENT),
        parse_usage(element_text(html, TAB_PREVIOUS), KEY_PREVIOUS),
    )


def parse_plan(pages: dict[str, str]) -> Plan:
    """Build the plan from the tariff pages.

    The tariff name only appears on ``showTariffInfo``; the overview page
    carries a ``digitalData`` object whose tariff fields are usually empty
    strings, so it is only consulted as a fallback.
    """
    plan = Plan()

    for html in pages.values():
        for label, value in parse_key_values(html).items():
            plan.details.setdefault(label, value)

    plan.name = plan.details.get(LABEL_TARIFF)
    plan.network = plan.details.get(LABEL_NETWORK)
    plan.customer_number = plan.details.get(LABEL_CUSTOMER_NUMBER)
    plan.msisdn = plan.details.get(LABEL_MSISDN)

    if not plan.name:
        plan.name = _digital_data(pages, "eppixTariffName")

    plan.tariff_code = _form_value(pages, "tariffCode")
    plan.package_code = _form_value(pages, "packageCode") or _digital_data(
        pages, "eppixPackageId"
    )

    if not plan.name:
        plan.name = plan.details.get(LABEL_BRAND)

    return plan


def _digital_data(pages: dict[str, str], key: str) -> str | None:
    """Return a non-empty ``digitalData`` product field."""
    pattern = re.compile(r'"product\.' + re.escape(key) + r'"\s*:\s*"([^"]+)"')

    for html in pages.values():
        match = pattern.search(html)

        if match:
            return match.group(1)

    return None


def _form_value(pages: dict[str, str], field_name: str) -> str | None:
    """Return a value the tariff-option forms carry, e.g. ``tariffCode``."""
    pattern = re.compile(
        r'name="[^"]+\[' + re.escape(field_name) + r'\]"\s+value="([^"]+)"',
        re.IGNORECASE,
    )

    for html in pages.values():
        match = pattern.search(html)

        if match:
            return match.group(1)

    return None


def build_data(plan: Plan, current: Usage, previous: Usage) -> dict[str, Any]:
    """Shape one poll into the structure the entities read."""
    return {
        KEY_PLAN: plan,
        KEY_CURRENT: current,
        KEY_PREVIOUS: previous,
    }

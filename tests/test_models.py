"""Tests for the Servicewelt page parsing."""
from __future__ import annotations

import pytest

from sim_de.models import (
    Usage,
    element_text,
    find_csrf_token,
    parse_german_number,
    parse_key_values,
    parse_plan,
    parse_usage,
    parse_usage_page,
    to_gb,
)

from fixtures import (
    CSRF_TOKEN,
    CUSTOMER_NUMBER,
    LOGIN_PAGE,
    MSISDN,
    OVERVIEW_PAGE,
    PACKAGE_CODE,
    PAGES,
    TARIFF_CODE,
    TARIFF_INFO_PAGE,
    TARIFF_NAME,
    USAGE_PAGE,
    usage_page,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15,58", 15.58),
        ("1.234,56", 1234.56),
        ("16", 16.0),
        # A dot is a thousands separator in German, never a decimal point.
        ("3.840", 3840.0),
        (" 300,00 MB ", 300.0),
        ("-3,5", -3.5),
    ],
)
def test_parse_german_number(text, expected):
    """German decimal commas and thousands dots are read correctly."""
    assert parse_german_number(text) == expected


def test_to_gb_converts_units():
    """Values are normalised to gigabytes."""
    assert to_gb("16,00", "GB") == 16.0
    assert to_gb("300,00", "MB") == pytest.approx(0.29296875)
    assert to_gb("3.840", "kb") == pytest.approx(3840 / 1024 / 1024)


def test_key_values_reads_the_tariff_block():
    """Every label/value row on the tariff page is picked up."""
    pairs = parse_key_values(TARIFF_INFO_PAGE)

    assert pairs["Tarif"] == TARIFF_NAME
    assert pairs["Kundennummer"] == CUSTOMER_NUMBER
    assert pairs["Rufnummer"] == MSISDN
    # Whitespace inside a value is collapsed.
    assert pairs["Mindestvertragslaufzeit"] == "24 Monate"


def test_key_values_ignores_pages_without_the_block():
    """A page with no key/value container yields nothing."""
    assert parse_key_values(OVERVIEW_PAGE) == {}


def test_element_text_is_scoped_to_the_tab():
    """Each tab's text stops at that tab's closing element."""
    current = element_text(USAGE_PAGE, "tab-cur")
    previous = element_text(USAGE_PAGE, "tab-mon")

    assert "15,58 GB von 16,00 GB verbraucht" in current
    assert "16,97" not in current
    assert "16,97 GB von 16,88 GB verbraucht" in previous


def test_element_text_missing_id():
    """An id that is not on the page yields an empty string."""
    assert element_text(USAGE_PAGE, "tab-nope") == ""


def test_parse_usage_current_month():
    """The current month is read without an allowance top-up."""
    usage = parse_usage(element_text(USAGE_PAGE, "tab-cur"), "current_month")

    assert usage.used_gb == 15.58
    assert usage.allowance_gb == 16.0
    assert usage.remaining_gb == 0.42
    assert usage.usage_percent == 97.4
    assert usage.auto_topup is None
    assert usage.over_allowance is False


def test_parse_usage_previous_month_over_allowance():
    """A month over its allowance reports no remainder and the top-up text."""
    usage = parse_usage(element_text(USAGE_PAGE, "tab-mon"), "previous_month")

    assert usage.used_gb == 16.97
    assert usage.allowance_gb == 16.88
    assert usage.remaining_gb == 0.0
    assert usage.usage_percent == 100.5
    assert usage.auto_topup == "davon 3 x 300,00 MB Datenautomatik"
    assert usage.over_allowance is True


def test_parse_usage_page_returns_both_months():
    """Both tabs are parsed in one pass."""
    current, previous = parse_usage_page(USAGE_PAGE)

    assert current.period == "current_month"
    assert previous.period == "previous_month"
    assert current.used_gb == 15.58
    assert previous.used_gb == 16.97


def test_parse_usage_handles_megabyte_figures():
    """A month reported in MB is converted to GB."""
    page = usage_page(current="512,00 MB", current_allowance="16,00 GB")
    current, _ = parse_usage_page(page)

    assert current.used_gb == 0.5
    assert current.allowance_gb == 16.0


def test_parse_usage_without_figures():
    """A tab with no numbers yields an empty Usage rather than raising."""
    usage = parse_usage("Für diesen Monat liegen keine Daten vor.", "current_month")

    assert usage == Usage(period="current_month")
    assert usage.over_allowance is False


def test_parse_plan_finds_the_tariff():
    """The plan comes from the key/value block, the codes from the forms."""
    plan = parse_plan(PAGES)

    assert plan.name == TARIFF_NAME
    assert plan.network == "1&1 5G Netz"
    assert plan.customer_number == CUSTOMER_NUMBER
    assert plan.msisdn == MSISDN
    assert plan.tariff_code == TARIFF_CODE
    assert plan.package_code == PACKAGE_CODE


def test_parse_plan_ignores_empty_digitaldata():
    """An empty digitalData field never becomes the plan name.

    This is the bug the standalone script had: the overview page always ships
    ``"product.eppixTariffName" : ""``, and the tariff name only appears on
    showTariffInfo.
    """
    plan = parse_plan({"overview": OVERVIEW_PAGE, "usage": USAGE_PAGE})

    assert plan.name is None


def test_parse_plan_falls_back_to_digitaldata():
    """A populated digitalData field is used when the block is missing."""
    overview = OVERVIEW_PAGE.replace(
        '"product.eppixTariffName" : ""',
        '"product.eppixTariffName" : "Allnet Flat 5 GB"',
    )

    plan = parse_plan({"overview": overview})

    assert plan.name == "Allnet Flat 5 GB"


def test_plan_attributes_drop_empty_values():
    """Only details the account actually has become attributes."""
    attributes = parse_plan(PAGES).as_attributes()

    assert attributes["tariff_code"] == TARIFF_CODE
    assert attributes["phone_number"] == MSISDN
    assert attributes["minimum_term"] == "24 Monate"
    assert all(value for value in attributes.values())


def test_find_csrf_token():
    """The Symfony token is read out of the login form."""
    assert find_csrf_token(LOGIN_PAGE) == CSRF_TOKEN
    assert find_csrf_token("<html><body>nothing here</body></html>") is None

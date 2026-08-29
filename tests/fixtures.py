"""Page fragments shaped like the sim.de Servicewelt.

The markup mirrors the real pages - the same containers, classes and tab ids -
but every value is invented.  No real customer data lives in this repository.
"""
from __future__ import annotations

USERNAME = "test-user"
PASSWORD = "sup3r-s3cret"
CSRF_TOKEN = "test-csrf-token"

TARIFF_NAME = "Allnet Flat 10 + 6 GB"
CUSTOMER_NUMBER = "C1234567"
MSISDN = "017600000000"
TARIFF_CODE = "5EF"
PACKAGE_CODE = "V5L22"


def _key_value(label: str, value: str) -> str:
    """Render one Servicewelt label/value row."""
    return f"""
<div class="c-key_value_container">
    <div class="row">
        <div class="cute-12-phone cute-5-tablet font-weight-bold">{label}</div>
        <div class="cute-12-phone cute-7-tablet">{value}</div>
        <div class="cute-12-phone"><hr class="my-2"></div>
    </div>
</div>
"""


LOGIN_PAGE = f"""
<html><body>
<form action="/public/login_check" method="post">
    <input type="text" name="UserLoginType[alias]" value="">
    <input type="password" name="UserLoginType[password]" value="">
    <input type="hidden" name="UserLoginType[_token]" value="{CSRF_TOKEN}">
</form>
</body></html>
"""

TARIFF_INFO_PAGE = "<html><body>" + "".join(
    [
        _key_value("Marke", "sim.de"),
        _key_value("Mobilfunknetz", "1&amp;1 5G Netz"),
        _key_value("Kundennummer", CUSTOMER_NUMBER),
        _key_value("Rufnummer", MSISDN),
        _key_value("Tarif", TARIFF_NAME),
        _key_value("Abrechnungsart", "Postpaid - Monatliche Rechnung"),
        _key_value("Mindestvertragslaufzeit", "24             Monate"),
        _key_value("Kündigungsfrist", "1             Monat"),
    ]
) + "</body></html>"

# The overview page carries digitalData, whose tariff fields are empty.
OVERVIEW_PAGE = """
<html><body>
<script>
    var digitalData = {
        "product.eppixTariffName" : "",
        "product.eppixPackageId" : ""
    };
</script>
</body></html>
"""


def usage_page(
    current: str = "15,58 GB",
    current_allowance: str = "16,00 GB",
    previous: str = "16,97 GB",
    previous_allowance: str = "16,88 GB",
    previous_extra: str = "(davon 3 x 300,00 MB Datenautomatik)",
) -> str:
    """Render the data-usage page with both month tabs."""
    return f"""
<html><body>
<div class="c-tabs_container">
    <div class="c-tabs-content " id="tab-cur">
        <div class="e-data_usage_graph">
            <div class="flex-tablet">
                <div class="mb-phone-2">
                    <span class="l-h4 font-weight-bold"> {current}</span>
                    <span class="font-weight-bold l-txt-small pr-2">von {current_allowance} verbraucht</span>
                </div>
            </div>
        </div>
        <form>
            <input type="hidden" name="option_form[tariffCode]" value="{TARIFF_CODE}">
            <input type="hidden" name="option_form[packageCode]" value="{PACKAGE_CODE}">
        </form>
    </div>
    <div class="c-tabs-content " id="tab-mon">
        <div class="e-data_usage_graph">
            <div class="flex-tablet">
                <div class="mb-phone-2">
                    <span class="l-h4 font-weight-bold"> {previous}</span>
                    <span class="font-weight-bold l-txt-small pr-2">von {previous_allowance} verbraucht {previous_extra}</span>
                </div>
            </div>
        </div>
    </div>
</div>
</body></html>
"""


USAGE_PAGE = usage_page()

PAGES = {
    "tariff_info": TARIFF_INFO_PAGE,
    "overview": OVERVIEW_PAGE,
    "usage": USAGE_PAGE,
}

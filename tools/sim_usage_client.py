#!/usr/bin/env python3
"""
SIM.de usage client

Goal:
  - Log into the SIM.de Servicewelt
  - Identify the current tariff/plan
  - Read current-month data usage
  - Read previous-month data usage
  - Extract allowance, used amount, remaining amount and usage %
  - Preserve the raw HTML for debugging

Based on the captured SIM.de Servicewelt HTML:
  GET /mytariff/overview
  GET /mytariff/tariff/showTariffInfo
  GET /mytariff/invoice/showGprsDataUsage

The usage page contains both:
  #tab-cur = current month
  #tab-mon = previous month

Do NOT hard-code cookies or CSRF tokens. They are session-specific.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://service.sim.de"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) "
        "Gecko/20100101 Firefox/151.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
}


@dataclass
class Usage:
    period: str
    used_gb: Optional[float] = None
    allowance_gb: Optional[float] = None
    remaining_gb: Optional[float] = None
    usage_percent: Optional[float] = None
    extra_text: Optional[str] = None


@dataclass
class Plan:
    name: Optional[str] = None
    data_allowance_gb: Optional[float] = None
    tariff_code: Optional[str] = None
    package_code: Optional[str] = None
    network: Optional[str] = None
    customer_number: Optional[str] = None
    msisdn: Optional[str] = None
    details: dict = field(default_factory=dict)


class SimClient:
    def __init__(self, output_dir: str = "sim_output"):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def url(self, path: str) -> str:
        return BASE_URL + path

    def get(self, path: str) -> requests.Response:
        r = self.session.get(self.url(path), timeout=30)
        r.raise_for_status()
        return r

    def extract_csrf(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")

        for inp in soup.select('input[type="hidden"]'):
            name = inp.get("name", "")
            if "_token" in name.lower() and inp.get("value"):
                return inp["value"]

        return None

    def login(self, username: str, password: str) -> None:
        # The login page contains the dynamically generated Symfony token.
        login_page = self.get("/start")

        token = self.extract_csrf(login_page.text)
        if not token:
            raise RuntimeError("Could not find login CSRF token.")

        data = {
            "UserLoginType[alias]": username,
            "UserLoginType[password]": password,
            "UserLoginType[logindata]": "",
            "UserLoginType[_token]": token,
        }

        r = self.session.post(
            self.url("/public/login_check"),
            data=data,
            timeout=30,
            allow_redirects=True,
        )

        if r.status_code >= 400:
            raise RuntimeError(f"Login failed: HTTP {r.status_code}")

        # Verify that the authenticated page is accessible.
        check = self.session.get(
            self.url("/mytariff/invoice/showGprsDataUsage"),
            timeout=30,
        )

        if check.url.rstrip("/") == BASE_URL:
            raise RuntimeError("Login did not create an authenticated session.")

    # ---------------------------------------------------------
    # Parsing helpers
    # ---------------------------------------------------------

    @staticmethod
    def parse_german_number(value: str) -> float:
        """
        Convert:
            15,58 -> 15.58
            1.234,56 -> 1234.56
        """
        value = value.strip().replace("\xa0", " ")
        value = re.sub(r"[^\d,.\-]", "", value)

        if "," in value:
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")

        return float(value)

    @classmethod
    def parse_gb(cls, value: str, unit: str) -> float:
        number = cls.parse_german_number(value)

        if unit.lower() == "mb":
            return number / 1024.0
        if unit.lower() == "kb":
            return number / (1024.0 * 1024.0)

        return number

    @classmethod
    def parse_usage_block(
        cls,
        container,
        period: str,
    ) -> Usage:
        """
        Parse a block like:

            15,58 GB
            von 16,00 GB verbraucht

        or:

            16,97 GB
            von 16,88 GB verbraucht
            (davon 3 x 300,00 MB Datenautomatik)
        """

        text = " ".join(container.stripped_strings)

        # Find all "number + unit" occurrences.
        values = re.findall(
            r"(\d+(?:[.,]\d+)?)\s*(GB|MB|KB)\b",
            text,
            flags=re.IGNORECASE,
        )

        used = None
        allowance = None

        # Prefer the exact "X von Y ... verbraucht" structure.
        match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(GB|MB|KB)\s*"
            r"von\s+(\d+(?:[.,]\d+)?)\s*(GB|MB|KB)\s*"
            r"verbraucht",
            text,
            flags=re.IGNORECASE,
        )

        if match:
            used = cls.parse_gb(match.group(1), match.group(2))
            allowance = cls.parse_gb(match.group(3), match.group(4))
        elif len(values) >= 2:
            used = cls.parse_gb(values[0][0], values[0][1])
            allowance = cls.parse_gb(values[1][0], values[1][1])

        percent = None
        if used is not None and allowance not in (None, 0):
            percent = used / allowance * 100.0

        remaining = None
        if used is not None and allowance is not None:
            remaining = max(allowance - used, 0.0)

        # Capture Dataautomatik / other explanatory usage text.
        extra = None
        extra_match = re.search(
            r"\(([^)]*(?:Datenautomatik|Datenautomatik)[^)]*)\)",
            text,
            flags=re.IGNORECASE,
        )
        if extra_match:
            extra = extra_match.group(1)

        return Usage(
            period=period,
            used_gb=used,
            allowance_gb=allowance,
            remaining_gb=remaining,
            usage_percent=percent,
            extra_text=extra,
        )

    @staticmethod
    def parse_key_values(html: str) -> dict:
        """
        The Servicewelt renders its facts as label/value pairs:

            <div class="c-key_value_container">
              <div class="row">
                <div class="... font-weight-bold">Tarif</div>
                <div class="...">Allnet Flat 10 + 6 GB</div>

        Returns {"Tarif": "Allnet Flat 10 + 6 GB", "Rufnummer": ...}.
        """
        soup = BeautifulSoup(html, "html.parser")
        pairs: dict = {}

        for row in soup.select(".c-key_value_container .row"):
            cells = [
                " ".join(div.get_text(" ", strip=True).split())
                for div in row.find_all("div", recursive=False)
            ]
            cells = [c for c in cells if c]

            if len(cells) >= 2 and cells[0] not in pairs:
                pairs[cells[0]] = cells[1]

        return pairs

    def get_usage(self) -> tuple[Usage, Usage, str]:
        r = self.get("/mytariff/invoice/showGprsDataUsage")
        html = r.text

        (self.output_dir / "data_usage.html").write_text(
            html,
            encoding="utf-8",
        )

        soup = BeautifulSoup(html, "html.parser")

        current = soup.select_one("#tab-cur")
        previous = soup.select_one("#tab-mon")

        if current is None:
            raise RuntimeError("Could not find #tab-cur.")

        if previous is None:
            raise RuntimeError("Could not find #tab-mon.")

        current_usage = self.parse_usage_block(
            current,
            "current_month",
        )

        previous_usage = self.parse_usage_block(
            previous,
            "previous_month",
        )

        return current_usage, previous_usage, html

    # ---------------------------------------------------------
    # Plan detection
    # ---------------------------------------------------------

    def get_plan(self) -> Plan:
        """
        The usage page is actually useful for plan identification because
        it contains the active data allowance and the tariff-option forms.

        We also inspect /mytariff/overview and /mytariff/tariff/showTariffInfo.
        """

        pages = {}

        for name, endpoint in {
            "tariff": "/mytariff/overview",
            "tariff_info": "/mytariff/tariff/showTariffInfo",
            "usage": "/mytariff/invoice/showGprsDataUsage",
        }.items():
            r = self.get(endpoint)
            pages[name] = r.text

            (self.output_dir / f"{name}.html").write_text(
                r.text,
                encoding="utf-8",
            )

        plan = Plan()

        # 1. The labelled key/value blocks are the reliable source. The tariff
        #    name lives on showTariffInfo, not on the overview page.
        for name in ("tariff_info", "tariff", "usage"):
            for label, value in self.parse_key_values(pages[name]).items():
                plan.details.setdefault(label, value)

        plan.name = plan.details.get("Tarif")
        plan.network = plan.details.get("Mobilfunknetz")
        plan.customer_number = plan.details.get("Kundennummer")
        plan.msisdn = plan.details.get("Rufnummer")

        # 2. digitalData is often present but empty - only trust non-blank values.
        for key, attr in (
            ("eppixTariffName", "name"),
            ("eppixPackageId", "package_code"),
        ):
            if getattr(plan, attr):
                continue
            for html in pages.values():
                m = re.search(r'"product\.' + key + r'"\s*:\s*"([^"]+)"', html)
                if m:
                    setattr(plan, attr, m.group(1))
                    break

        # 3. Last resort: the longest "... N GB ..." phrase on the tariff pages.
        if not plan.name:
            visible = " ".join(
                BeautifulSoup(pages["tariff_info"], "html.parser").stripped_strings
            )
            candidates = re.findall(
                r"([A-Za-zÄÖÜäöüß0-9+&()\- ]{3,80}"
                r"\d+(?:[.,]\d+)?\s*GB"
                r"(?:[A-Za-zÄÖÜäöüß0-9+&()\- ]{0,40}))",
                visible,
                flags=re.IGNORECASE,
            )
            if candidates:
                plan.name = max(candidates, key=len).strip()

        # 4. Currently displayed allowance, from the usage page.
        current = BeautifulSoup(pages["usage"], "html.parser").select_one("#tab-cur")

        if current:
            plan.data_allowance_gb = self.parse_usage_block(
                current,
                "current_month",
            ).allowance_gb

        # 5. Tariff/package codes are carried by the option forms.
        tariff_code = re.search(
            r'name="[^"]+\[tariffCode\]"\s+value="([^"]+)"',
            pages["usage"],
            flags=re.IGNORECASE,
        )
        if tariff_code:
            plan.tariff_code = tariff_code.group(1)

        package_code = re.search(
            r'name="[^"]+\[packageCode\]"\s+value="([^"]+)"',
            pages["usage"],
            flags=re.IGNORECASE,
        )
        if package_code:
            plan.package_code = package_code.group(1)

        return plan

    # ---------------------------------------------------------
    # Public high-level method
    # ---------------------------------------------------------

    def get_status(self) -> dict:
        plan = self.get_plan()
        current, previous, _ = self.get_usage()

        result = {
            "plan": asdict(plan),
            "usage": {
                "current_month": asdict(current),
                "previous_month": asdict(previous),
            },
        }

        (self.output_dir / "status.json").write_text(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return result


def print_report(result: dict) -> None:
    plan = result["plan"]
    current = result["usage"]["current_month"]
    previous = result["usage"]["previous_month"]

    print()
    print("=" * 60)
    print("SIM.DE DATA USAGE")
    print("=" * 60)

    print(f"Plan:        {plan.get('name') or 'unknown'}")

    if plan.get("network"):
        print(f"Network:     {plan['network']}")

    if plan.get("msisdn"):
        print(f"Number:      {plan['msisdn']}")

    if plan.get("customer_number"):
        print(f"Customer:    {plan['customer_number']}")

    if plan.get("tariff_code"):
        print(f"Tariff code: {plan['tariff_code']}")

    if plan.get("package_code"):
        print(f"Package:     {plan['package_code']}")

    print()
    print("CURRENT MONTH")
    print("-" * 60)

    print(
        f"Used:       "
        f"{current['used_gb']:.2f} GB"
        if current.get("used_gb") is not None
        else "Used:       unknown"
    )

    print(
        f"Allowance:  "
        f"{current['allowance_gb']:.2f} GB"
        if current.get("allowance_gb") is not None
        else "Allowance:  unknown"
    )

    print(
        f"Remaining:  "
        f"{current['remaining_gb']:.2f} GB"
        if current.get("remaining_gb") is not None
        else "Remaining:  unknown"
    )

    print(
        f"Usage:      "
        f"{current['usage_percent']:.1f}%"
        if current.get("usage_percent") is not None
        else "Usage:      unknown"
    )

    if current.get("extra_text"):
        print(f"Extra:      {current['extra_text']}")

    print()
    print("PREVIOUS MONTH")
    print("-" * 60)

    print(
        f"Used:       "
        f"{previous['used_gb']:.2f} GB"
        if previous.get("used_gb") is not None
        else "Used:       unknown"
    )

    print(
        f"Allowance:  "
        f"{previous['allowance_gb']:.2f} GB"
        if previous.get("allowance_gb") is not None
        else "Allowance:  unknown"
    )

    print(
        f"Remaining:  "
        f"{previous['remaining_gb']:.2f} GB"
        if previous.get("remaining_gb") is not None
        else "Remaining:  unknown"
    )

    print(
        f"Usage:      "
        f"{previous['usage_percent']:.1f}%"
        if previous.get("usage_percent") is not None
        else "Usage:      unknown"
    )

    if previous.get("extra_text"):
        print(f"Extra:      {previous['extra_text']}")

    print()
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Read SIM.de plan and current/previous data usage."
    )

    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument(
        "--output",
        default="sim_output",
    )

    args = parser.parse_args()

    username = args.username or input("SIM.de username: ")
    password = args.password or getpass.getpass(
        "SIM.de password: "
    )

    client = SimClient(
        output_dir=args.output,
    )

    try:
        print("Logging in...")
        client.login(username, password)

        print("Reading tariff and data usage...")
        result = client.get_status()

        print_report(result)

        print()
        print(
            f"JSON saved to: "
            f"{Path(args.output) / 'status.json'}"
        )

    except requests.RequestException as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        sys.exit(1)

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

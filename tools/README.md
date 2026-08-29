# tools

Exploration scripts. Nothing here is part of the integration, and nothing here
is installed by HACS.

## `sim_usage_client.py`

The standalone command-line client the integration grew out of. It logs into
the Servicewelt with `requests`, prints the plan and both months of data usage,
and — usefully when the site changes — writes every page it loaded to
`sim_output/` so the HTML can be diffed against what the parser expects.

```bash
pip install requests beautifulsoup4
python tools/sim_usage_client.py --username <alias> --output sim_output
```

```
Plan:        Allnet Flat 10 + 6 GB
Network:     1&1 5G Netz
Tariff code: 5EF
Package:     V5L22

CURRENT MONTH
------------------------------------------------------------
Used:       15.58 GB
Allowance:  16.00 GB
Remaining:  0.42 GB
Usage:      97.4%
```

The integration does not share code with this script: it re-implements the same
parsing on `aiohttp` and the standard library's `html.parser`, so it needs no
third-party dependency at all. When the Servicewelt markup changes, run this
script first to capture the new pages, then update
`custom_components/sim_de/models.py` and the fixtures in `tests/fixtures.py`.

> The saved pages contain your customer number and phone number. `sim_output/`
> is in `.gitignore` — keep it that way.

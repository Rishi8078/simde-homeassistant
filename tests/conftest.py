"""Test bootstrap.

``custom_components/sim_de`` is registered here as the ``sim_de`` package.
Its ``__init__.py`` is not executed, which keeps the pure-Python modules
(``api``, ``models``, ``const``) importable without a Home Assistant install.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "sim_de"

if "sim_de" not in sys.modules:
    package = types.ModuleType("sim_de")
    package.__path__ = [str(COMPONENT)]
    sys.modules["sim_de"] = package

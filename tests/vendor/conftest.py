"""Bridge src.json_repair imports to vendored json_repair + apply monkeypatch."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = Path("/a0")
VENDOR = PLUGIN_ROOT / "vendor"

for p in (str(FRAMEWORK_ROOT), str(PLUGIN_ROOT), str(VENDOR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from usr.plugins.context_doctor.helpers.json_repair_patch import apply_patch  # noqa: E402

apply_patch()

# Bridge src.json_repair -> vendored json_repair
import json_repair as _vr  # noqa: E402

if "src" not in sys.modules:
    sys.modules["src"] = type(sys)("src")
sys.modules["src.json_repair"] = _vr

_submodules = [
    "json_repair",
    "json_parser",
    "parse_string",
    "parse_object",
    "parse_array",
    "parse_number",
    "parse_comment",
    "schema_repair",
    "parser_schema",
    "parser_parenthesized",
]
for sub in _submodules:
    full = f"src.json_repair.{sub}"
    if full not in sys.modules:
        sys.modules[full] = importlib.import_module(f"json_repair.{sub}")

# Bridge subpackages
for sub in ["parse_string_helpers", "utils"]:
    full = f"src.json_repair.{sub}"
    if full not in sys.modules:
        sys.modules[full] = importlib.import_module(f"json_repair.{sub}")

# Bridge individual modules in subpackages
for sub in [
    "parse_string_helpers.object_value_context",
    "parse_string_helpers.parse_boolean_or_null",
    "parse_string_helpers.parse_json_llm_block",
    "utils.constants",
    "utils.json_context",
    "utils.object_comparer",
    "utils.pattern_properties",
    "utils.string_file_wrapper",
]:
    full = f"src.json_repair.{sub}"
    if full not in sys.modules:
        sys.modules[full] = importlib.import_module(f"json_repair.{sub}")

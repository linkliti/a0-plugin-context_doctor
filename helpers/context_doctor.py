"""Context Doctor core: repair and beautify JSON tool-call responses.

Uses the ``json_repair`` library (mangiucugna/json_repair) to repair malformed
JSON that the native DirtyJson could not fully fix, then validates against the
A0 tool-call schema and beautifies with 4-space indentation.

The entire raw model response is passed to ``repair_json`` without any
pre-extraction — the library handles finding and repairing JSON in arbitrary
text (prose, thinking tags, markdown fences, truncated input).
"""

from __future__ import annotations

import json
from typing import Any, TypedDict


class A0ToolCall(TypedDict, total=False):
    """A0 tool-call JSON schema.

    | Field | Type | Required |
    |---|---|---|
    | thoughts | list[str] | yes |
    | headline | str | yes |
    | tool_name | str | yes |
    | tool_args | dict | yes |
    """

    thoughts: list[str]
    headline: str
    tool_name: str
    tool_args: dict[str, Any]


# Required fields with their expected types (for post-repair validation)
# Only tool_name and tool_args are strictly required — the A0 framework
# handles missing thoughts/headline gracefully.
_REQUIRED_FIELDS: dict[str, type] = {
    "tool_name": str,
    "tool_args": dict,
}

# Optional fields with their expected types (validated only if present)
_OPTIONAL_FIELDS: dict[str, type] = {
    "thoughts": list,
    "headline": str,
}


def _validate_schema(obj: Any) -> bool:
    """Type-check *obj* against the A0 tool-call schema.

    Requires ``tool_name`` and ``tool_args``. If ``thoughts`` or ``headline``
    are present, they must have the correct type.
    """
    if not isinstance(obj, dict):
        return False
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in obj:
            return False
        if not isinstance(obj[field], expected_type):
            return False
    for field, expected_type in _OPTIONAL_FIELDS.items():
        if field in obj and not isinstance(obj[field], expected_type):
            return False
    if "thoughts" in obj:
        for item in obj["thoughts"]:
            if not isinstance(item, str):
                return False
    return True


# JSON Schema for salvage mode — guides repair shape without enforcing required fields
_A0_SALVAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thoughts": {"type": "array", "items": {"type": "string"}},
        "headline": {"type": "string"},
        "tool_name": {"type": "string"},
        "tool_args": {"type": "object"},
    },
    "required": [],
}


def _a0_completeness_score(obj: dict[str, Any]) -> int:
    """Score how complete an A0 tool-call dict is.

    Higher score = more likely the real tool call. Ties broken by position
    (first wins via ``max`` stability).
    """
    score = 0
    for field in ("thoughts", "headline", "tool_name", "tool_args"):
        if field in obj:
            score += 1
    if obj.get("tool_args"):
        score += 1
    return score


def repair_and_beautify(
    raw: str,
    *,
    minify: bool = False,
    use_standard_mode: bool = False,
) -> str | None:
    """Repair malformed JSON and beautify with 4-space indentation.

    The entire raw text is passed to ``json_repair.repair_json`` which handles
    finding and repairing JSON in arbitrary text — no pre-extraction needed.

    Returns ``None`` if *raw* contains no recognizable A0 tool-call JSON
    or if the repaired object fails schema validation.
    Returns the beautified JSON string on success.
    """
    if not raw:
        return None

    try:
        import os
        import sys

        _vendor = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vendor")
        if _vendor not in sys.path:
            sys.path.insert(0, _vendor)
        from usr.plugins.context_doctor.helpers.json_repair_patch import apply_patch

        apply_patch()
        from json_repair import repair_json
    except ImportError:
        return None

    try:
        repair_kwargs: dict[str, Any] = {
            "return_objects": True,
        }
        if use_standard_mode:
            repair_kwargs["schema_repair_mode"] = "standard"
        else:
            repair_kwargs["schema"] = _A0_SALVAGE_SCHEMA
            repair_kwargs["schema_repair_mode"] = "salvage"
        try:
            repaired_obj = repair_json(raw, **repair_kwargs)
        except Exception:
            repaired_obj = repair_json(raw, return_objects=True)
    except Exception:
        return None

    # Always try no-schema mode to discover all JSON fragments.
    # Salvage mode may pick only the first fragment, missing the real tool call.
    # No-schema mode returns the full list, letting scoring pick the best one.
    if not use_standard_mode:
        try:
            noschema_obj = repair_json(raw, return_objects=True)
        except Exception:
            noschema_obj = None
        # Prefer no-schema list over salvage single dict when it has more
        # valid candidates with higher completeness.
        if isinstance(noschema_obj, list):
            noschema_valid = [
                item
                for item in noschema_obj
                if isinstance(item, dict) and _validate_schema(item)
            ]
            if len(noschema_valid) > 1:
                repaired_obj = noschema_obj
            elif len(noschema_valid) == 1 and not _validate_schema(repaired_obj):
                repaired_obj = noschema_obj

    if isinstance(repaired_obj, list):
        valid = [
            item
            for item in repaired_obj
            if isinstance(item, dict) and _validate_schema(item)
        ]
        if valid:
            repaired_obj = max(valid, key=_a0_completeness_score)
        else:
            repaired_obj = None

    if not isinstance(repaired_obj, dict):
        return None

    if not _validate_schema(repaired_obj):
        return None

    try:
        return json.dumps(
            repaired_obj,
            indent=None if minify else 4,
            ensure_ascii=False,
            separators=(",", ":") if minify else None,
        )
    except (TypeError, ValueError):
        return None


# JSON replacement for plain text with XML tags (corrupted tool call)
_XML_CORRUPTION_REPLACEMENT = "{}"


def build_heading(agent: Any, text: str) -> str:
    """Match A0's heading format with agent prefix (A0:, A1:, etc.)."""
    agent_prefix = f"{getattr(agent, 'agent_name', 'A0')}: "
    return f"{agent_prefix}{text}"


def update_log_item(
    agent: Any,
    log_item: Any,
    transformed: str,
    *,
    update_log: bool,
    raw_message: str = "",
) -> None:
    """Update log item kvps, heading, and optionally content from transformed JSON."""
    try:
        try:
            parsed = json.loads(transformed)
        except (ValueError, TypeError):
            parsed = {}

        if isinstance(parsed, dict):
            new_kvps = {k: v for k, v in parsed.items()}
            new_heading = parsed.get("headline", "")
            if not new_heading and parsed.get("tool_name"):
                new_heading = f"Using {parsed['tool_name']}"
            if new_heading:
                new_heading = build_heading(agent, new_heading)
            update_kwargs: dict[str, Any] = {"kvps": new_kvps}
            if new_heading:
                update_kwargs["heading"] = new_heading
            if update_log:
                update_kwargs["content"] = transformed
            elif raw_message:
                update_kwargs["content"] = raw_message
            log_item.update(**update_kwargs)
    except (AttributeError, TypeError):
        pass


def transform_response(
    raw: str,
    *,
    minify: bool = False,
    use_standard_mode: bool = False,
    suppress_xml: bool = True,
) -> str:
    """Transform a raw model response into clean JSON.

    Three cases:
    1. Valid (possibly malformed) A0 tool-call JSON → repair + beautify.
    2. Plain text with XML tags (corrupted tool call) → replace with ``{}``
       when *suppress_xml* is True, otherwise wrap as raw text.
    3. Plain text without XML → wrap the raw text in ``{"thoughts": [raw]}``.

    Always returns a JSON string. Never returns ``None``.
    """
    _indent = None if minify else 4

    if not raw:
        return json.dumps({"thoughts": [""]}, indent=_indent, ensure_ascii=False)

    # Try to repair as A0 tool-call JSON first
    beautified = repair_and_beautify(
        raw,
        minify=minify,
        use_standard_mode=use_standard_mode,
    )
    if beautified is not None:
        return beautified

    # Not a valid tool call — determine replacement based on XML presence
    has_xml = "<" in raw and ">" in raw
    if has_xml and suppress_xml:
        return _XML_CORRUPTION_REPLACEMENT
    return json.dumps({"thoughts": [raw]}, indent=_indent, ensure_ascii=False)

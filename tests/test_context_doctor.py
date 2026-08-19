from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = Path("/a0")
for p in (str(FRAMEWORK_ROOT), str(PLUGIN_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from usr.plugins.context_doctor.helpers.context_doctor import (
    A0ToolCall,
    _a0_completeness_score,
    _validate_schema,
    repair_and_beautify,
    transform_response,
)


# ─── _validate_schema ─────────────────────────────────────────────


_FULL: A0ToolCall = {
    "thoughts": ["thinking"],
    "headline": "Test",
    "tool_name": "response",
    "tool_args": {"text": "hi"},
}


def test_validate_schema_valid() -> None:
    assert _validate_schema(_FULL) is True


def test_validate_schema_missing_thoughts() -> None:
    """thoughts is optional — missing it should still pass."""
    obj = dict(_FULL)
    del obj["thoughts"]
    assert _validate_schema(obj) is True


def test_validate_schema_missing_headline() -> None:
    """headline is optional — missing it should still pass."""
    obj = dict(_FULL)
    del obj["headline"]
    assert _validate_schema(obj) is True


def test_validate_schema_missing_tool_name() -> None:
    obj = dict(_FULL)
    del obj["tool_name"]
    assert _validate_schema(obj) is False


def test_validate_schema_missing_tool_args() -> None:
    obj = dict(_FULL)
    del obj["tool_args"]
    assert _validate_schema(obj) is False


def test_validate_schema_wrong_type_thoughts() -> None:
    obj = dict(_FULL)
    obj["thoughts"] = "not a list"
    assert _validate_schema(obj) is False


def test_validate_schema_wrong_type_heading() -> None:
    obj = dict(_FULL)
    obj["headline"] = 123
    assert _validate_schema(obj) is False


def test_validate_schema_wrong_type_tool_name() -> None:
    obj = dict(_FULL)
    obj["tool_name"] = 99
    assert _validate_schema(obj) is False


def test_validate_schema_wrong_type_tool_args() -> None:
    obj = dict(_FULL)
    obj["tool_args"] = "not a dict"
    assert _validate_schema(obj) is False


def test_validate_schema_thoughts_non_str_items() -> None:
    obj = dict(_FULL)
    obj["thoughts"] = ["ok", 42, None]
    assert _validate_schema(obj) is False


def test_validate_schema_not_dict() -> None:
    assert _validate_schema([1, 2, 3]) is False
    assert _validate_schema(None) is False


# ─── repair_and_beautify ──────────────────────────────────────────


def test_repair_valid_json_passes_through() -> None:
    raw = '{"thoughts":["thinking"],"headline":"Test","tool_name":"response","tool_args":{"text":"hi"}}'
    result = repair_and_beautify(raw)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["tool_name"] == "response"
    assert parsed["tool_args"] == {"text": "hi"}


def test_repair_beautifies_with_4_space_indent() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"x","tool_args":{}}'
    result = repair_and_beautify(raw)
    assert result is not None
    assert '    "tool_name"' in result
    parsed = json.loads(result)
    assert parsed["tool_name"] == "x"
    assert parsed["tool_args"] == {}


def test_repair_malformed_json_missing_quote() -> None:
    raw = '{"thoughts":["thinking"],"headline":"Test","tool_name":"response","tool_args":{"text":"hi}}'
    result = repair_and_beautify(raw)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["tool_name"] == "response"


def test_repair_malformed_json_trailing_comma() -> None:
    raw = '{"thoughts":["thinking"],"headline":"Test","tool_name":"response","tool_args":{"text":"hi",},}'
    result = repair_and_beautify(raw)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["tool_args"] == {"text": "hi"}


def test_repair_returns_none_for_plain_text() -> None:
    assert repair_and_beautify("Just a plain response.") is None


def test_repair_returns_none_for_empty() -> None:
    assert repair_and_beautify("") is None


def test_repair_returns_none_for_non_dict() -> None:
    assert repair_and_beautify("[1, 2, 3]") is None


def test_repair_returns_none_for_no_tool_name() -> None:
    assert repair_and_beautify('{"key": "value"}') is None


def test_repair_preserves_extra_fields() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"x","tool_args":{},"id":"abc"}'
    result = repair_and_beautify(raw)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["id"] == "abc"


def test_repair_surrounding_noise() -> None:
    raw = 'Here is my response:\n{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"hi"}}\nDone.'
    result = repair_and_beautify(raw)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["tool_name"] == "response"


# ─── Extension: response_stream_end ───────────────────────────────


def test_response_stream_end_modifies_log_content() -> None:
    from usr.plugins.context_doctor.extensions.python.response_stream_end._20_context_doctor import (
        ContextDoctorLog,
    )

    updated: dict[str, str] = {}
    log_item = SimpleNamespace(
        content='{"thoughts":["t"],"headline":"H","tool_name":"x","tool_args":{}}',
        update=lambda **kw: updated.update(kw),
    )
    loop_data = SimpleNamespace(params_temporary={"log_item_generating": log_item})
    agent = SimpleNamespace()

    ext = ContextDoctorLog(agent=agent)  # pyright: ignore[reportArgumentType]
    import asyncio

    asyncio.run(ext.execute(loop_data=loop_data))

    assert "content" in updated
    parsed = json.loads(updated["content"])
    assert parsed["tool_name"] == "x"


def test_response_stream_end_skips_non_json() -> None:
    from usr.plugins.context_doctor.extensions.python.response_stream_end._20_context_doctor import (
        ContextDoctorLog,
    )

    original_content = "Plain text response"
    updated: dict[str, str] = {}
    log_item = SimpleNamespace(
        content=original_content, update=lambda **kw: updated.update(kw)
    )
    loop_data = SimpleNamespace(params_temporary={"log_item_generating": log_item})
    agent = SimpleNamespace()

    ext = ContextDoctorLog(agent=agent)  # pyright: ignore[reportArgumentType]
    import asyncio

    asyncio.run(ext.execute(loop_data=loop_data))

    assert updated.get("content") is not None
    import json as _json

    parsed = _json.loads(updated["content"])
    assert parsed == {"thoughts": [original_content]}


def test_response_stream_end_no_log_item() -> None:
    from usr.plugins.context_doctor.extensions.python.response_stream_end._20_context_doctor import (
        ContextDoctorLog,
    )

    loop_data = SimpleNamespace(params_temporary={})
    agent = SimpleNamespace()

    ext = ContextDoctorLog(agent=agent)  # pyright: ignore[reportArgumentType]
    import asyncio

    asyncio.run(ext.execute(loop_data=loop_data))  # should not raise


# ─── Extension: hist_add_ai_response/end ──────────────────────────


def test_hist_add_ai_response_end_modifies_message_content() -> None:
    from usr.plugins.context_doctor.extensions.python._functions.agent.Agent.hist_add_ai_response.end._20_context_doctor import (
        ContextDoctorHistory,
    )

    msg = SimpleNamespace(
        content='{"thoughts":["t"],"headline":"H","tool_name":"x","tool_args":{}}'
    )
    data = {"result": msg, "args": (), "kwargs": {}}
    agent = SimpleNamespace()

    ext = ContextDoctorHistory(agent=agent)  # pyright: ignore[reportArgumentType]
    ext.execute(data=data)

    parsed = json.loads(msg.content)
    assert parsed["tool_name"] == "x"


def test_hist_add_ai_response_end_skips_plain_text() -> None:
    from usr.plugins.context_doctor.extensions.python._functions.agent.Agent.hist_add_ai_response.end._20_context_doctor import (
        ContextDoctorHistory,
    )

    original = "Plain text response"
    msg = SimpleNamespace(content=original)
    data = {"result": msg, "args": (), "kwargs": {}}
    agent = SimpleNamespace()

    ext = ContextDoctorHistory(agent=agent)  # pyright: ignore[reportArgumentType]
    ext.execute(data=data)

    assert msg.content == original


def test_hist_add_ai_response_end_no_result() -> None:
    from usr.plugins.context_doctor.extensions.python._functions.agent.Agent.hist_add_ai_response.end._20_context_doctor import (
        ContextDoctorHistory,
    )

    agent = SimpleNamespace()
    ext = ContextDoctorHistory(agent=agent)  # pyright: ignore[reportArgumentType]
    ext.execute(data={"result": None, "args": (), "kwargs": {}})  # should not raise


# ─── Extension: tool_execute_before ───────────────────────────────


def test_tool_execute_before_replaces_args_from_full_response() -> None:
    from usr.plugins.context_doctor.extensions.python.tool_execute_before._30_context_doctor import (
        ContextDoctorTool,
    )

    raw = '{"thoughts":["t"],"headline":"H","tool_name":"x","tool_args":{"key":"val"}}'
    tool_args = {"old_key": "old_val"}
    loop_data = SimpleNamespace(last_response=raw)
    agent = SimpleNamespace(loop_data=loop_data)

    ext = ContextDoctorTool(agent=agent)  # pyright: ignore[reportArgumentType]
    import asyncio

    asyncio.run(ext.execute(tool_args=tool_args))

    assert tool_args == {"key": "val"}


def test_tool_execute_before_skips_non_json_response() -> None:
    from usr.plugins.context_doctor.extensions.python.tool_execute_before._30_context_doctor import (
        ContextDoctorTool,
    )

    original = {"code": "print('hello')"}
    tool_args = dict(original)
    loop_data = SimpleNamespace(last_response="plain text response")
    agent = SimpleNamespace(loop_data=loop_data)

    ext = ContextDoctorTool(agent=agent)  # pyright: ignore[reportArgumentType]
    import asyncio

    asyncio.run(ext.execute(tool_args=tool_args))

    assert tool_args == original


def test_tool_execute_before_skips_non_dict_args() -> None:
    from usr.plugins.context_doctor.extensions.python.tool_execute_before._30_context_doctor import (
        ContextDoctorTool,
    )

    agent = SimpleNamespace(loop_data=SimpleNamespace(last_response=""))
    ext = ContextDoctorTool(agent=agent)  # pyright: ignore[reportArgumentType]
    import asyncio

    asyncio.run(ext.execute(tool_args=None))  # should not raise


def test_tool_execute_before_skips_missing_loop_data() -> None:
    from usr.plugins.context_doctor.extensions.python.tool_execute_before._30_context_doctor import (
        ContextDoctorTool,
    )

    original = {"count": 42}
    tool_args = dict(original)
    agent = SimpleNamespace()

    ext = ContextDoctorTool(agent=agent)  # pyright: ignore[reportArgumentType]
    import asyncio

    asyncio.run(ext.execute(tool_args=tool_args))

    assert tool_args == original


def test_tool_execute_before_skips_response_without_tool_name() -> None:
    from usr.plugins.context_doctor.extensions.python.tool_execute_before._30_context_doctor import (
        ContextDoctorTool,
    )

    original = {"key": "val"}
    tool_args = dict(original)
    loop_data = SimpleNamespace(last_response='{"key": "val"}')
    agent = SimpleNamespace(loop_data=loop_data)

    ext = ContextDoctorTool(agent=agent)  # pyright: ignore[reportArgumentType]
    import asyncio

    asyncio.run(ext.execute(tool_args=tool_args))

    assert tool_args == original


# ─── json_repair_patch regression tests ─────────────────────────────


def test_patch_prevents_quoted_key_with_newline_split() -> None:
    """Unescaped quotes inside a string value must not create a false member
    boundary when the candidate key spans a newline."""
    raw = '{"tool_name": "response", "tool_args": {"text": "a, "first\nsecond": val"}}'
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert set(obj["tool_args"].keys()) == {"text"}
    assert "first" in obj["tool_args"]["text"]
    assert "second" in obj["tool_args"]["text"]


def test_patch_prevents_long_quoted_key_split() -> None:
    """Unescaped quotes creating a candidate key longer than 24 chars must
    not be classified as a real object member."""
    long_key = "w" * 25
    raw = (
        '{"tool_name": "response", "tool_args": {"text": "a, "' + long_key + '": val"}}'
    )
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert set(obj["tool_args"].keys()) == {"text"}
    assert long_key in obj["tool_args"]["text"]


def test_patch_prevents_timestamp_like_bare_key_split() -> None:
    """A comma followed by digits with a colon (timestamp-like pattern) must
    not be classified as a bare object member key."""
    raw = '{"tool_name": "response", "tool_args": {"text": "a, 2026: 01 data"}}'
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert set(obj["tool_args"].keys()) == {"text"}
    assert "2026" in obj["tool_args"]["text"]


def test_patch_preserves_valid_short_keys() -> None:
    """Short, letter-only keys must still be recognized as real members."""
    raw = '{"tool_name": "response", "tool_args": {"text": "ok", "note": "extra"}}'
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert set(obj["tool_args"].keys()) == {"text", "note"}


# ─── XML fallback and kvps regression tests ─────────────────────────


def test_xml_wrapped_json_repaired_via_no_schema_fallback() -> None:
    """JSON wrapped in XML tags must be recovered, not replaced with {}."""
    raw = '<tool_args>\n{"tool_name": "response", "tool_args": {"text": "hi"}}\n</tool_args>'
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert obj["tool_name"] == "response"
    assert obj["tool_args"]["text"] == "hi"


def test_plain_text_fallback_populates_kvps_from_thoughts() -> None:
    """Plain text wrapped in {"thoughts": [raw]} must populate kvps with thoughts."""
    raw = "just some plain text"
    transformed = transform_response(raw)
    assert transformed is not None
    obj = json.loads(transformed)
    assert "thoughts" in obj
    assert obj["thoughts"] == ["just some plain text"]


def test_doubled_json_extracts_valid_tool_call_from_list() -> None:
    """When repair returns a list of dicts (prose with inline JSON before a
    fenced code block), extract the first one that passes schema validation."""
    raw = (
        'See `{"thoughts": ["raw"]}` in the docs.\n'
        "```\n"
        '{"tool_name": "response", "tool_args": {"text": "hi"}}\n'
        "```\n"
    )
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert obj["tool_name"] == "response"
    assert obj["tool_args"]["text"] == "hi"


def test_concatenated_jsons_picks_first_valid() -> None:
    """Two valid tool-call JSONs concatenated with no separator — pick the
    first, not the second (which may be a hallucinated continuation)."""
    raw = (
        '{"thoughts": ["first"], "headline": "First", "tool_name": "call_subordinate", '
        '"tool_args": {"message": "go"}}'
        '{"thoughts": ["second"], "headline": "Second", "tool_name": "response", '
        '"tool_args": {"text": "hi"}}'
    )
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert obj["tool_name"] == "call_subordinate"
    assert obj["tool_args"]["message"] == "go"


def test_nested_json_inside_thoughts_not_extracted() -> None:
    """JSON embedded inside a thoughts string must not be extracted as the
    tool call — the outer object is the real tool call."""
    raw = (
        '{"thoughts": ["Consider this: {\\"tool_name\\": \\"response\\", \\"tool_args\\": {\\"text\\": \\"fake\\"}}"], '
        '"headline": "Real", "tool_name": "code_execution_tool", '
        '"tool_args": {"runtime": "terminal", "code": "echo hi"}}'
    )
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert obj["tool_name"] == "code_execution_tool"
    assert obj["tool_args"]["code"] == "echo hi"


def test_multiple_json_with_prose_picks_first_valid() -> None:
    """Multiple JSON objects separated by prose — first valid tool call wins.
    The no-schema fallback returns a list when salvage mode picks the wrong
    fragment, and forward iteration selects the first schema-valid dict."""
    raw = (
        "Here is the first call:\n"
        '{"tool_name": "response", "tool_args": {"text": "hello"}}\n'
        "And here is a second one:\n"
        '{"tool_name": "response", "tool_args": {"text": "world"}}\n'
    )
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert obj["tool_args"]["text"] == "hello"


def test_suppress_xml_default_returns_empty_obj() -> None:
    """When suppress_xml is True (default), XML-containing text returns {}."""
    raw = "<response>some xml content</response>"
    result = transform_response(raw)
    assert result == "{}"


def test_suppress_xml_disabled_treats_as_raw_text() -> None:
    """When suppress_xml is False, XML-containing text is wrapped as thoughts."""
    raw = "<response>some xml content</response>"
    result = transform_response(raw, suppress_xml=False)
    obj = json.loads(result)
    assert "thoughts" in obj
    assert obj["thoughts"] == [raw]


# ─── completeness scoring ──────────────────────────────────────────


def test_a0_completeness_score_full() -> None:
    obj: dict = {
        "thoughts": ["t"],
        "headline": "H",
        "tool_name": "response",
        "tool_args": {"text": "hi"},
    }
    assert _a0_completeness_score(obj) == 5


def test_a0_completeness_score_minimal() -> None:
    obj = {"tool_name": "response", "tool_args": {"text": "hi"}}
    assert _a0_completeness_score(obj) == 3


def test_a0_completeness_score_empty_args() -> None:
    obj = {"tool_name": "response", "tool_args": {}}
    assert _a0_completeness_score(obj) == 2


def test_scoring_picks_full_over_minimal() -> None:
    """When a list has a full A0 tool call and an unrelated fragment with only
    tool_name+tool_args, the full one wins via higher completeness score."""
    raw = (
        'Here is some data: {"tool_name": "data", "tool_args": {"val": 1}}\n'
        'Now the real call: {"thoughts": ["go"], "headline": "Act", '
        '"tool_name": "response", "tool_args": {"text": "hi"}}'
    )
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert obj["tool_name"] == "response"
    assert obj["tool_args"]["text"] == "hi"
    assert obj.get("headline") == "Act"


def test_scoring_two_complete_calls_picks_first() -> None:
    """Two equally complete A0 tool calls — first one wins (tie broken by
    position via max stability)."""
    raw = (
        '{"thoughts": ["first"], "headline": "A", "tool_name": "response", '
        '"tool_args": {"text": "one"}}'
        '{"thoughts": ["second"], "headline": "B", "tool_name": "response", '
        '"tool_args": {"text": "two"}}'
    )
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert obj["tool_args"]["text"] == "one"


def test_scoring_only_incomplete_fragments_picks_best() -> None:
    """When no full tool call exists, pick the most complete fragment."""
    raw = (
        'Fragment A: {"tool_name": "x", "tool_args": {}}\n'
        'Fragment B: {"tool_name": "y", "tool_args": {"code": "ls"}}'
    )
    result = repair_and_beautify(raw)
    assert result is not None
    obj = json.loads(result)
    assert obj["tool_name"] == "y"
    assert obj["tool_args"]["code"] == "ls"

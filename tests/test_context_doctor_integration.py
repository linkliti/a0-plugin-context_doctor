from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = Path("/a0")
for p in (str(FRAMEWORK_ROOT), str(PLUGIN_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from helpers import extract_tools
from helpers.dirty_json import DirtyJson
from helpers.log import Log

from usr.plugins.context_doctor.helpers.context_doctor import (
    repair_and_beautify,
)


# ─── Full pipeline: DirtyJson → json_repair → extract_tools round-trip ──


def test_valid_json_round_trips_through_extract_tools() -> None:
    raw = '{"thoughts":["planning"],"headline":"Test","tool_name":"response","tool_args":{"text":"hi"}}'
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    extracted = extract_tools.extract_tool_request(beautified)
    assert extracted is not None
    name, args = extract_tools.normalize_tool_request(extracted)
    assert name == "response"
    assert args == {"text": "hi"}


def test_malformed_json_repaired_then_extracted() -> None:
    raw = '{"thoughts":["planning"],"headline":"Test","tool_name":"response","tool_args":{"text":"hi",},}'
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    extracted = extract_tools.extract_tool_request(beautified)
    assert extracted is not None
    name, args = extract_tools.normalize_tool_request(extracted)
    assert name == "response"
    assert args["text"] == "hi"


def test_missing_closing_brace_repaired_then_extracted() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"code_execution_tool","tool_args":{"runtime":"python","code":"print(1)"'
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    extracted = extract_tools.extract_tool_request(beautified)
    assert extracted is not None
    name, args = extract_tools.normalize_tool_request(extracted)
    assert name == "code_execution_tool"
    assert args["runtime"] == "python"
    assert args["code"] == "print(1)"


def test_dirtyjson_partial_then_repair_fills_gaps() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"hello"'
    parsed = DirtyJson.parse_string(raw)
    assert isinstance(parsed, dict)
    assert parsed.get("tool_name") == "response"
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    extracted = extract_tools.extract_tool_request(beautified)
    assert extracted is not None
    name, args = extract_tools.normalize_tool_request(extracted)
    assert name == "response"
    assert args["text"] == "hello"


def test_beautified_output_is_valid_json_loads() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"x","tool_args":{"a":1,"b":[1,2,3]}}'
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    obj = json.loads(beautified)
    assert obj["tool_name"] == "x"
    assert obj["tool_args"]["b"] == [1, 2, 3]


def test_beautified_output_has_4_space_indent() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"x","tool_args":{}}'
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    assert '\n    "tool_name"' in beautified


def test_non_tool_call_json_rejected() -> None:
    raw = '{"status":"ok","data":[1,2,3]}'
    assert repair_and_beautify(raw) is None


def test_plain_text_rejected() -> None:
    assert repair_and_beautify("Just a plain response with no JSON.") is None


# ─── Integration: real Log/LogItem with response_stream_end extension ──


def test_response_stream_end_with_real_log() -> None:
    from usr.plugins.context_doctor.extensions.python.response_stream_end._20_context_doctor import (
        ContextDoctorLog,
    )

    log = Log()
    log_item = log.log(type="agent", heading="A0: Thinking", id="msg-1")
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"hello world"}}'
    log_item.update(content=raw)
    loop_data = SimpleNamespace(params_temporary={"log_item_generating": log_item})
    agent = SimpleNamespace()

    ext = ContextDoctorLog(agent=agent)  # pyright: ignore[reportArgumentType]
    asyncio.run(ext.execute(loop_data=loop_data))

    assert log_item.content != raw
    obj = json.loads(log_item.content)
    assert obj["tool_name"] == "response"
    assert obj["tool_args"]["text"] == "hello world"


def test_response_stream_end_skips_non_json_with_real_log() -> None:
    from usr.plugins.context_doctor.extensions.python.response_stream_end._20_context_doctor import (
        ContextDoctorLog,
    )

    log = Log()
    log_item = log.log(type="agent", heading="A0: Thinking")
    original = "This is a plain text response."
    log_item.update(content=original)
    loop_data = SimpleNamespace(params_temporary={"log_item_generating": log_item})
    agent = SimpleNamespace()

    ext = ContextDoctorLog(agent=agent)  # pyright: ignore[reportArgumentType]
    asyncio.run(ext.execute(loop_data=loop_data))

    assert log_item.content != original
    import json as _json2

    parsed = _json2.loads(log_item.content)
    assert parsed == {"thoughts": [original]}


# ─── Integration: real LoopData with tool_execute_before extension ──


def test_tool_execute_before_with_real_loop_data() -> None:
    from agent import LoopData
    from usr.plugins.context_doctor.extensions.python.tool_execute_before._30_context_doctor import (
        ContextDoctorTool,
    )

    raw = '{"thoughts":["thinking"],"headline":"H","tool_name":"code_execution_tool","tool_args":{"runtime":"terminal","code":"ls -la"}}'
    loop_data = LoopData()
    loop_data.last_response = raw
    tool_args = {"old_key": "old_val"}
    agent = SimpleNamespace(loop_data=loop_data)

    ext = ContextDoctorTool(agent=agent)  # pyright: ignore[reportArgumentType]
    asyncio.run(ext.execute(tool_args=tool_args, tool_name="code_execution_tool"))

    assert "old_key" not in tool_args
    assert tool_args["runtime"] == "terminal"
    assert tool_args["code"] == "ls -la"


def test_tool_execute_before_skips_plain_response_with_real_loop_data() -> None:
    from agent import LoopData
    from usr.plugins.context_doctor.extensions.python.tool_execute_before._30_context_doctor import (
        ContextDoctorTool,
    )

    loop_data = LoopData()
    loop_data.last_response = "Plain text, no JSON here."
    original = {"key": "val"}
    tool_args = dict(original)
    agent = SimpleNamespace(loop_data=loop_data)

    ext = ContextDoctorTool(agent=agent)  # pyright: ignore[reportArgumentType]
    asyncio.run(ext.execute(tool_args=tool_args, tool_name="response"))

    assert tool_args == original


# ─── Integration: DirtyJson parse → repair → normalize_tool_request ──


def test_dirty_json_parse_then_repair_then_normalize() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"search_engine","tool_args":{"query":"test query"}}'
    parsed = DirtyJson.parse_string(raw)
    assert isinstance(parsed, dict)
    assert parsed["tool_name"] == "search_engine"
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    extracted = extract_tools.extract_tool_request(beautified)
    assert extracted is not None
    name, args = extract_tools.normalize_tool_request(extracted)
    assert name == "search_engine"
    assert args["query"] == "test query"


def test_extract_tool_request_from_beautified_with_method_suffix() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"text_editor:read","tool_args":{"path":"/tmp/test.txt"}}'
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    extracted = extract_tools.extract_tool_request(beautified)
    assert extracted is not None
    name, args = extract_tools.normalize_tool_request(extracted)
    assert name == "text_editor"
    assert args["action"] == "read"
    assert args["path"] == "/tmp/test.txt"


def test_beautified_output_preserves_extra_fields_for_extraction() -> None:
    raw = '{"thoughts":["t"],"headline":"My Headline","tool_name":"response","tool_args":{"text":"ok"},"id":"msg-42"}'
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    obj = json.loads(beautified)
    assert obj["id"] == "msg-42"
    assert obj["headline"] == "My Headline"
    extracted = extract_tools.extract_tool_request(beautified)
    assert extracted is not None


def test_repair_handles_unicode_in_tool_args() -> None:
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"héllo wörld 日本語"}}'
    beautified = repair_and_beautify(raw)
    assert beautified is not None
    assert "héllo wörld 日本語" in beautified
    extracted = extract_tools.extract_tool_request(beautified)
    assert extracted is not None
    _, args = extract_tools.normalize_tool_request(extracted)
    assert args["text"] == "héllo wörld 日本語"


# ─── Integration: multiple tool calls in sequence ──


def test_sequential_repairs_each_independent() -> None:
    calls = [
        '{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"first"}}',
        '{"thoughts":["t"],"headline":"H","tool_name":"code_execution_tool","tool_args":{"runtime":"python","code":"print(2)"}}',
        '{"thoughts":["t"],"headline":"H","tool_name":"search_engine","tool_args":{"query":"third"}}',
    ]
    for raw in calls:
        beautified = repair_and_beautify(raw)
        assert beautified is not None
        extracted = extract_tools.extract_tool_request(beautified)
        assert extracted is not None
        name, args = extract_tools.normalize_tool_request(extracted)
        assert name in ("response", "code_execution_tool", "search_engine")


# ─── Integration: real Log output after modification ──


def test_log_output_reflects_repaired_content() -> None:
    from usr.plugins.context_doctor.extensions.python.response_stream_end._20_context_doctor import (
        ContextDoctorLog,
    )

    log = Log()
    log_item = log.log(type="agent", heading="A0: Thinking", id="msg-1")
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"x","tool_args":{"key":"val"}}'
    log_item.update(content=raw)
    loop_data = SimpleNamespace(params_temporary={"log_item_generating": log_item})
    agent = SimpleNamespace()

    ext = ContextDoctorLog(agent=agent)  # pyright: ignore[reportArgumentType]
    asyncio.run(ext.execute(loop_data=loop_data))

    output = log.output()
    assert len(output.items) > 0
    found = False
    for item in output.items:
        if item.get("no") == log_item.no:
            content = item.get("content", "")
            if "tool_name" in content and "    " in content:
                found = True
                break
    assert found, "Repaired content not found in log output"

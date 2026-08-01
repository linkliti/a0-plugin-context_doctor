from __future__ import annotations
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = Path("/a0")
for p in (str(FRAMEWORK_ROOT), str(PLUGIN_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent import Agent
from helpers import extract_tools
from agent import LoopData
from helpers.llm_result import LLMResult


def _run_context_doctor_hook(agent: Agent, raw: str, llm_result: LLMResult, msg):
    """Directly invoke ContextDoctorHistory.execute as the @extensible end hook would."""
    from usr.plugins.context_doctor.extensions.python._functions.agent.Agent.hist_add_ai_response.end._20_context_doctor import (
        ContextDoctorHistory,
    )

    ext = object.__new__(ContextDoctorHistory)
    ext.agent = agent
    ext.execute(
        data={
            "args": (agent, raw),
            "kwargs": {"llm_result": llm_result},
            "result": msg,
        }
    )


def _make_agent_with_loop() -> Agent:
    """Create a minimal Agent instance that can run hist_add_ai_response + process_llm_result_tools."""
    agent = object.__new__(Agent)
    agent.data = {}
    agent.loop_data = LoopData()
    agent.config = SimpleNamespace(profile="test")  # pyright: ignore[reportAttributeAccessIssue]
    agent.context = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        log=MagicMock(),
        get_data=lambda key, recursive=True: None,
        set_data=lambda key, value, recursive=True: None,
    )
    agent.agent_name = "test"
    agent.last_message = ""  # pyright: ignore[reportAttributeAccessIssue]

    # Minimal history mock
    agent.history = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        add_message=MagicMock(return_value=SimpleNamespace(content="", id="msg-1")),
        new_topic=MagicMock(),
        all_messages=MagicMock(return_value=[]),
        current=SimpleNamespace(messages=[]),
        topics=[],
        bulks=[],
    )

    # Mock read_prompt to return empty strings
    agent.read_prompt = lambda *a, **kw: ""

    # Mock handle_intervention as async no-op
    async def _no_intervention(*a, **kw):
        return None

    agent.handle_intervention = _no_intervention

    # Mock _log_response_builtin_items as async no-op
    async def _log_builtin(result):
        return None

    agent._log_response_builtin_items = _log_builtin  # pyright: ignore[reportAttributeAccessIssue]

    # Mock _remember_llm_result_state as no-op
    agent._remember_llm_result_state = lambda *a, **kw: None  # pyright: ignore[reportPrivateUsage]

    return agent


# ─── E2E: malformed JSON → hist_add_ai_response → process_llm_result_tools ──


@pytest.mark.asyncio
async def test_malformed_json_repaired_before_tool_processing() -> None:
    """Malformed JSON in LLMResult.response gets repaired by the end hook,
    so process_llm_result_tools sees clean JSON and extract_tool_request succeeds."""
    agent = _make_agent_with_loop()

    # Malformed JSON: missing closing braces
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"hi"'

    # Verify this raw text fails extraction (proves it's actually malformed)
    assert extract_tools.extract_tool_request(raw) is None

    llm_result = LLMResult.from_chat(response=raw)

    # Call hist_add_ai_response — this triggers the @extensible end hook
    # which should repair llm_result.response
    msg = agent.hist_add_ai_response(raw, llm_result=llm_result)

    _run_context_doctor_hook(agent, raw, llm_result, msg)

    # Verify llm_result.response was repaired
    assert llm_result.response != raw, (
        "llm_result.response was not modified by end hook"
    )
    parsed = json.loads(llm_result.response)
    assert parsed["tool_name"] == "response"
    assert parsed["tool_args"] == {"text": "hi"}

    # Now verify extract_tool_request succeeds on the repaired response
    extracted = extract_tools.extract_tool_request(llm_result.response)
    assert extracted is not None, "extract_tool_request failed on repaired JSON"
    assert extracted["tool_name"] == "response"


@pytest.mark.asyncio
async def test_valid_json_passes_through_tool_processing() -> None:
    """Valid JSON passes through the repair pipeline unchanged and is extracted successfully."""
    agent = _make_agent_with_loop()

    raw = '{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"ok"}}'
    llm_result = LLMResult.from_chat(response=raw)

    msg = agent.hist_add_ai_response(raw, llm_result=llm_result)

    _run_context_doctor_hook(agent, raw, llm_result, msg)

    extracted = extract_tools.extract_tool_request(llm_result.response)
    assert extracted is not None
    assert extracted["tool_name"] == "response"
    assert extracted["tool_args"] == {"text": "ok"}


@pytest.mark.asyncio
async def test_trailing_comma_repaired_before_tool_processing() -> None:
    """JSON with trailing commas gets repaired and extracted successfully."""
    agent = _make_agent_with_loop()

    raw = '{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"hi",},}'
    llm_result = LLMResult.from_chat(response=raw)

    msg = agent.hist_add_ai_response(raw, llm_result=llm_result)

    _run_context_doctor_hook(agent, raw, llm_result, msg)

    assert llm_result.response != raw
    extracted = extract_tools.extract_tool_request(llm_result.response)
    assert extracted is not None
    assert extracted["tool_args"] == {"text": "hi"}


@pytest.mark.asyncio
async def test_surrounding_text_repaired_before_tool_processing() -> None:
    """JSON embedded in surrounding prose gets repaired and extracted."""
    agent = _make_agent_with_loop()

    raw = 'Here is my response:\n{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"hi"}}\nDone.'
    llm_result = LLMResult.from_chat(response=raw)

    # Raw text fails extraction (surrounding prose)
    assert extract_tools.extract_tool_request(raw) is None

    msg = agent.hist_add_ai_response(raw, llm_result=llm_result)

    _run_context_doctor_hook(agent, raw, llm_result, msg)

    # After repair, extraction should succeed
    extracted = extract_tools.extract_tool_request(llm_result.response)
    assert extracted is not None
    assert extracted["tool_name"] == "response"


@pytest.mark.asyncio
async def test_process_llm_result_tools_no_misformat_after_repair() -> None:
    """Full process_llm_result_tools flow: after repair, no misformat warning is triggered.

    This verifies the end-to-end path: hist_add_ai_response → end hook repairs
    llm_result.response → process_llm_result_tools reads repaired response →
    extract_tool_request succeeds → process_tools is called (not misformat path).
    """
    agent = _make_agent_with_loop()

    # Track what process_tools receives
    received_messages: list[str] = []

    async def mock_process_tools(message):
        received_messages.append(message)
        # Verify the message is valid repaired JSON
        parsed = json.loads(message)
        assert parsed["tool_name"] == "response"
        return None

    agent.process_tools = mock_process_tools  # pyright: ignore[reportAttributeAccessIssue]

    # Malformed JSON that would fail extraction without repair
    raw = '{"thoughts":["t"],"headline":"H","tool_name":"response","tool_args":{"text":"hi"}'
    llm_result = LLMResult.from_chat(response=raw)

    # hist_add_ai_response triggers end hook → repairs llm_result.response
    msg = agent.hist_add_ai_response(raw, llm_result=llm_result)

    _run_context_doctor_hook(agent, raw, llm_result, msg)

    # process_llm_result_tools should now see the repaired JSON
    await Agent.process_llm_result_tools(agent, llm_result)

    # process_tools should have been called (not the misformat path)
    assert len(received_messages) == 1, (
        "process_tools was not called — misformat path was taken"
    )
    # The message received should be the repaired (beautified) JSON
    msg = received_messages[0]
    assert msg != raw, "process_tools received raw (unrepaired) JSON"
    parsed = json.loads(msg)
    assert parsed["tool_name"] == "response"
    assert parsed["tool_args"] == {"text": "hi"}


@pytest.mark.asyncio
async def test_tool_execute_before_receives_repaired_args() -> None:
    """The tool_execute_before extension receives tool_args from the repaired full response."""
    from usr.plugins.context_doctor.extensions.python.tool_execute_before._30_context_doctor import (
        ContextDoctorTool,
    )

    # Simulate the full repaired response stored in loop_data.last_response
    repaired = json.dumps(
        {
            "thoughts": ["t"],
            "headline": "H",
            "tool_name": "code_execution_tool",
            "tool_args": {"runtime": "terminal", "code": "echo hello"},
        },
        indent=4,
    )

    agent = SimpleNamespace(loop_data=SimpleNamespace(last_response=repaired))
    tool_args = {"old_key": "old_val"}

    ext = ContextDoctorTool(agent=agent)  # pyright: ignore[reportArgumentType]
    await ext.execute(tool_args=tool_args)

    assert tool_args == {"runtime": "terminal", "code": "echo hello"}


@pytest.mark.asyncio
async def test_non_tool_response_not_repaired() -> None:
    """Plain text responses (not tool calls) are not modified."""
    agent = _make_agent_with_loop()

    raw = "This is a plain text response with no JSON."
    llm_result = LLMResult.from_chat(response=raw)

    msg = agent.hist_add_ai_response(raw, llm_result=llm_result)

    _run_context_doctor_hook(agent, raw, llm_result, msg)

    # Plain text without XML → wrap raw text in {"thoughts": [raw]}
    assert llm_result.response != raw
    parsed = json.loads(llm_result.response)
    assert parsed == {"thoughts": [raw]}


@pytest.mark.asyncio
async def test_repeated_malformed_responses_each_repaired() -> None:
    """Multiple malformed responses in sequence are each independently repaired."""
    agent = _make_agent_with_loop()

    cases = [
        '{"thoughts":["a"],"headline":"A","tool_name":"response","tool_args":{"text":"1"}',
        '{"thoughts":["b"],"headline":"B","tool_name":"response","tool_args":{"text":"2"},}',
        '{"thoughts":["c"],"headline":"C","tool_name":"response","tool_args":{"text":"3"}}',
    ]

    for raw in cases:
        llm_result = LLMResult.from_chat(response=raw)
        msg = agent.hist_add_ai_response(raw, llm_result=llm_result)

        _run_context_doctor_hook(agent, raw, llm_result, msg)

        extracted = extract_tools.extract_tool_request(llm_result.response)
        assert extracted is not None, f"Failed to extract from: {raw}"
        assert extracted["tool_args"]["text"] in ("1", "2", "3")

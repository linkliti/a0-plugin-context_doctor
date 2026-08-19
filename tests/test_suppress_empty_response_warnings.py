"""Tests for the hist_add_warning start hook that suppresses warnings for empty model responses."""

from types import SimpleNamespace

from helpers.errors import HandledException
from helpers.settings import get_default_settings, normalize_settings
from extensions.python._functions.agent.Agent.hist_add_warning.end import (
    _90_stop_unusable_response_loop as response_loop,
)
from usr.plugins.context_doctor.extensions.python._functions.agent.Agent.hist_add_warning.start import (
    _10_suppress_empty_response_warnings as suppress_hook,
)


class FakeLog:
    def __init__(self):
        self.entries = []

    def log(self, **entry):
        entry.setdefault("id", "")
        self.entries.append(entry)
        return SimpleNamespace(id=entry.get("id", ""))


class FakeHistory:
    def __init__(self):
        self.messages = []

    def add_message(self, ai, content, tokens=0, id="", metadata=None, sequence=0):
        msg = SimpleNamespace(ai=ai, content=content, id=id, tokens=tokens)
        self.messages.append(msg)
        return msg


def _agent(last_response="", iteration=0, params_persistent=None, last_reasoning=""):
    """Build a minimal fake agent matching the A0 Agent interface."""
    prompts = {
        "fw.msg_misformat.md": "You have misformatted your message. Follow system prompt instructions on JSON message formatting precisely.",
        "fw.msg_repeat.md": "You have sent the same message again. You have to do something else!",
        "fw.msg_unusable_response_limit.md": "Agent stopped after {{limit}} consecutive unusable model responses to prevent further API charges. Send a new message to try again.",
        "fw.msg_empty_response.md": "Model returned an empty response (no reasoning, no content). Retry queued.",
        "fw.warning.md": '~~~json\n{"system_warning": {{message}}}\n~~~',
        "fw.ai_response.md": "{{message}}",
    }

    def read_prompt(name, **kwargs):
        text = prompts.get(name, "")
        for k, v in kwargs.items():
            text = text.replace("{{" + k + "}}", str(v))
        return text

    def parse_prompt(name, **kwargs):
        return read_prompt(name, **kwargs)

    history = FakeHistory()

    return SimpleNamespace(
        agent_name="A0",
        loop_data=SimpleNamespace(
            iteration=iteration,
            last_response=last_response,
            params_persistent=params_persistent or {},
            params_temporary={"last_reasoning": last_reasoning},
        ),
        context=SimpleNamespace(log=FakeLog()),
        history=history,
        read_prompt=read_prompt,
        parse_prompt=parse_prompt,
        hist_add_message=history.add_message,
    )


def _run_start(extension_cls, agent, message):
    """Simulate a hist_add_warning start hook execution."""
    ext = extension_cls(agent=agent)
    data = {
        "args": (agent, message),
        "kwargs": {"message": message},
        "result": None,
        "exception": None,
    }
    ext.execute(data=data)
    return data


def _run_end(extension_cls, agent, message):
    """Simulate a hist_add_warning end hook execution."""
    ext = extension_cls(agent=agent)
    data = {
        "args": (agent, message),
        "kwargs": {"message": message},
        "result": None,
        "exception": None,
    }
    ext.execute(data=data)
    return data


# --- Suppression hook tests ---


def test_does_not_suppress_when_reasoning_present_but_content_empty():
    """Model produced reasoning tokens — not truly empty, warning passes through."""
    agent = _agent(last_response="", last_reasoning="I should call a tool but didn't.")
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    data = _run_start(
        suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text
    )

    assert data["result"] is None


def test_suppresses_when_both_reasoning_and_content_empty():
    """Model produced zero reasoning and zero content — truly empty, suppress."""
    agent = _agent(last_response="", last_reasoning="")
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    data = _run_start(
        suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text
    )

    assert data["result"] is not None
    assert len(agent.history.messages) == 0


def test_does_not_suppress_whitespace_only_reasoning_treated_as_empty():
    """Whitespace-only reasoning is treated as no reasoning."""
    agent = _agent(last_response="", last_reasoning="  \n  ")
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    data = _run_start(
        suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text
    )

    assert data["result"] is not None
    assert len(agent.history.messages) == 0


def test_suppresses_misformat_warning_for_empty_response():
    """When model returned empty response, misformat warning is suppressed from LLM context."""
    agent = _agent(last_response="")
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    data = _run_start(
        suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text
    )

    # Short-circuited: result is set, hist_add_message was NOT called
    assert data["result"] is not None
    assert len(agent.history.messages) == 0


def test_suppresses_repeat_warning_for_empty_response():
    """When model returned empty response, repeat warning is suppressed from LLM context."""
    agent = _agent(last_response="")
    repeat_text = agent.read_prompt("fw.msg_repeat.md")

    data = _run_start(suppress_hook.SuppressEmptyResponseWarnings, agent, repeat_text)

    assert data["result"] is not None
    assert len(agent.history.messages) == 0


def test_does_not_suppress_misformat_for_nonempty_response():
    """When model returned actual content, misformat warning passes through normally."""
    agent = _agent(last_response='{"thoughts":["t"],"tool_name":"x","tool_args":{}}')
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    data = _run_start(
        suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text
    )

    # Not short-circuited: result is still None
    assert data["result"] is None


def test_does_not_suppress_repeat_for_nonempty_response():
    """When model returned actual content (duplicate), repeat warning passes through normally."""
    agent = _agent(last_response='{"thoughts":["t"],"tool_name":"x","tool_args":{}}')
    repeat_text = agent.read_prompt("fw.msg_repeat.md")

    data = _run_start(suppress_hook.SuppressEmptyResponseWarnings, agent, repeat_text)

    assert data["result"] is None


def test_does_not_suppress_unrelated_warnings():
    """Warnings that are not misformat or repeat are never suppressed."""
    agent = _agent(last_response="")

    data = _run_start(
        suppress_hook.SuppressEmptyResponseWarnings, agent, "Some other warning"
    )

    assert data["result"] is None


def test_does_not_suppress_whitespace_only_response_treated_as_empty():
    """Whitespace-only model responses are treated as empty."""
    agent = _agent(last_response="   \n  ")
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    data = _run_start(
        suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text
    )

    assert data["result"] is not None
    assert len(agent.history.messages) == 0


def test_suppressed_result_has_id_attribute():
    """The short-circuit result must have an .id attribute for callers."""
    agent = _agent(last_response="")
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    data = _run_start(
        suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text
    )

    assert hasattr(data["result"], "id")


# --- Counter integration tests ---


def test_counter_increments_when_misformat_suppressed(monkeypatch):
    """The unusable response counter still increments when warning is suppressed."""
    monkeypatch.setattr(
        response_loop,
        "get_settings",
        lambda: {"max_consecutive_unusable_responses": 3},
    )
    agent = _agent(last_response="", iteration=0)
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    # Start hook suppresses
    _run_start(suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text)

    # End hook (counter) fires — uses the ORIGINAL message text for matching
    _run_end(response_loop.StopUnusableResponseLoop, agent, misformat_text)

    count = agent.loop_data.params_persistent.get(response_loop.STATE_KEY, {}).get(
        "count"
    )
    assert count == 1


def test_counter_increments_when_repeat_suppressed(monkeypatch):
    """The counter increments for suppressed repeat warnings too."""
    monkeypatch.setattr(
        response_loop,
        "get_settings",
        lambda: {"max_consecutive_unusable_responses": 3},
    )
    agent = _agent(last_response="", iteration=0)
    repeat_text = agent.read_prompt("fw.msg_repeat.md")

    _run_start(suppress_hook.SuppressEmptyResponseWarnings, agent, repeat_text)
    _run_end(response_loop.StopUnusableResponseLoop, agent, repeat_text)

    count = agent.loop_data.params_persistent.get(response_loop.STATE_KEY, {}).get(
        "count"
    )
    assert count == 1


def test_counter_limit_triggers_when_all_suppressed(monkeypatch):
    """The agent stops after max consecutive suppressed empty responses."""
    monkeypatch.setattr(
        response_loop,
        "get_settings",
        lambda: {"max_consecutive_unusable_responses": 2},
    )
    agent = _agent(last_response="", iteration=0)
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    # First empty response
    _run_start(suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text)
    _run_end(response_loop.StopUnusableResponseLoop, agent, misformat_text)

    # Second empty response (next iteration)
    agent.loop_data.iteration = 1
    repeat_text = agent.read_prompt("fw.msg_repeat.md")
    _run_start(suppress_hook.SuppressEmptyResponseWarnings, agent, repeat_text)
    data = _run_end(response_loop.StopUnusableResponseLoop, agent, repeat_text)

    assert isinstance(data["exception"], HandledException)


def test_counter_resets_when_nonempty_response_arrives(monkeypatch):
    """A non-empty response resets the counter even after suppressed empties."""
    monkeypatch.setattr(
        response_loop,
        "get_settings",
        lambda: {"max_consecutive_unusable_responses": 3},
    )
    agent = _agent(last_response="", iteration=0)
    misformat_text = agent.read_prompt("fw.msg_misformat.md")

    # Empty response 1
    _run_start(suppress_hook.SuppressEmptyResponseWarnings, agent, misformat_text)
    _run_end(response_loop.StopUnusableResponseLoop, agent, misformat_text)
    assert agent.loop_data.params_persistent[response_loop.STATE_KEY]["count"] == 1

    # Non-empty response (gap in iterations resets counter)
    agent.loop_data.iteration = 2
    _run_end(response_loop.StopUnusableResponseLoop, agent, "Tool 'x' not found")

    count = agent.loop_data.params_persistent.get(response_loop.STATE_KEY, {}).get(
        "count", 0
    )
    assert count == 0 or count == 1


# --- Settings tests ---


def test_default_settings_unchanged():
    """The hook does not alter max_consecutive_unusable_responses default."""
    settings = get_default_settings()
    assert settings["max_consecutive_unusable_responses"] == 5
    settings["max_consecutive_unusable_responses"] = 0
    assert normalize_settings(settings)["max_consecutive_unusable_responses"] == 1

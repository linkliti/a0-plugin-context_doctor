"""Suppress misformat/repeat warnings from LLM context when model returned empty response.

When the model produces zero reasoning and zero content tokens, the framework's
misformat and repeat warnings are misleading. This hook:

* Detects empty responses via agent.loop_data.last_response and params_temporary['last_reasoning'].
* Short-circuits hist_add_message so nothing is appended to LLM context.
* Logs a custom user-visible warning from fw.msg_empty_response.md.
* Leaves the end-hook counter (_90_stop_unusable_response_loop) intact.

Note: agent.py also logs the original warning text to UI after hist_add_warning
returns (lines 511 and 1514-1518). This results in two UI entries for empty
responses — our custom one and the framework's original.
"""

from types import SimpleNamespace
from typing import Any

from helpers.extension import Extension


class SuppressEmptyResponseWarnings(Extension):
    """Short-circuit hist_add_warning for empty model responses."""

    def execute(self, data: dict[str, Any] | None = None, **kwargs: Any):
        if not self.agent or not isinstance(data, dict):
            return

        call_kwargs = data.get("kwargs")
        message = call_kwargs.get("message") if isinstance(call_kwargs, dict) else None
        if message is None:
            call_args = data.get("args")
            if isinstance(call_args, tuple) and len(call_args) > 1:
                message = call_args[1]

        if not isinstance(message, str) or not message:
            return

        misformat_text = self.agent.read_prompt("fw.msg_misformat.md")
        repeat_text = self.agent.read_prompt("fw.msg_repeat.md")
        if message not in {misformat_text, repeat_text}:
            return

        loop_data = getattr(self.agent, "loop_data", None)
        last_response = getattr(loop_data, "last_response", "")
        if not isinstance(last_response, str) or last_response.strip():
            return

        params = getattr(loop_data, "params_temporary", None)
        if isinstance(params, dict):
            last_reasoning = params.get("last_reasoning", "")
            if isinstance(last_reasoning, str) and last_reasoning.strip():
                return

        data["result"] = SimpleNamespace(id=data.get("kwargs", {}).get("id", ""))

        custom_msg = self.agent.read_prompt("fw.msg_empty_response.md")
        self.agent.context.log.log(
            type="warning",
            content=f"{self.agent.agent_name}: {custom_msg}",
        )

"""Store last response content and reasoning on loop_data for downstream hooks.

Runs before _20_context_doctor so repair hooks and warning suppression hooks
can access both fields without needing llm_result directly.
"""

from __future__ import annotations
from typing import Any, override

from helpers.extension import Extension


class StoreLastResponse(Extension):
    @override
    def execute(self, data: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if not self.agent or not isinstance(data, dict):
            return

        params = getattr(
            getattr(self.agent, "loop_data", None), "params_temporary", None
        )
        if not isinstance(params, dict):
            return

        call_kwargs = data.get("kwargs", {})
        if not isinstance(call_kwargs, dict):
            return

        llm_result = call_kwargs.get("llm_result")
        params["last_reasoning"] = getattr(llm_result, "reasoning", "") or ""

        args = data.get("args")
        if isinstance(args, tuple) and len(args) > 1 and isinstance(args[1], str):
            params["last_content"] = args[1]
        else:
            params["last_content"] = getattr(llm_result, "response", "") or ""

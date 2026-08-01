"""Context Doctor: repair or replace AI response in history and llm_result.

Fires in the @extensible end hook of Agent.hist_add_ai_response.
Always updates kvps and heading. Only updates log content (View Details JSON)
when update_log setting is enabled.
"""

from __future__ import annotations

from typing import Any, override

from helpers.extension import Extension
from helpers.plugins import get_plugin_config
from usr.plugins.context_doctor.helpers.context_doctor import (
    transform_response,
    update_log_item,
)


class ContextDoctorHistory(Extension):
    @override
    def execute(self, data: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if not self.agent or not isinstance(data, dict):
            return

        config = get_plugin_config("context_doctor", agent=self.agent) or {}
        minify = config.get("minify", False)
        update_log = config.get("update_log", False)
        indent = config.get("indent", 4)
        use_standard_mode = config.get("use_standard_mode", False)

        args = data.get("args")
        if not isinstance(args, tuple) or len(args) < 2:
            return
        raw_message = args[1]
        if not isinstance(raw_message, str) or not raw_message:
            return

        transformed = transform_response(
            raw_message,
            indent=indent,
            minify=minify,
            use_standard_mode=use_standard_mode,
        )
        if transformed == raw_message:
            return

        msg = data.get("result")
        if msg is not None:
            msg.content = transformed

        call_kwargs = data.get("kwargs", {})
        if isinstance(call_kwargs, dict):
            llm_result = call_kwargs.get("llm_result")
            if llm_result is not None:
                try:
                    llm_result.response = transformed
                except (AttributeError, TypeError):
                    pass

        # {} fallback (XML corruption) is history-only — skip log update.
        if transformed == "{}":
            return

        params = getattr(
            getattr(self.agent, "loop_data", None), "params_temporary", None
        )
        if isinstance(params, dict):
            log_item = params.get("log_item_generating")
            if log_item is not None:
                update_log_item(
                    self.agent,
                    log_item,
                    transformed,
                    update_log=update_log,
                    raw_message=raw_message,
                )

"""Context Doctor: transform WebUI log item in-place after stream ends.

Always updates kvps and heading. Only updates content (View Details JSON)
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


class ContextDoctorLog(Extension):
    @override
    async def execute(self, **kwargs: Any) -> None:
        if not self.agent:
            return

        config = get_plugin_config("context_doctor", agent=self.agent) or {}
        minify = config.get("minify", False)
        update_log = config.get("update_log", False)
        indent = config.get("indent", 4)
        use_standard_mode = config.get("use_standard_mode", False)

        loop_data = kwargs.get("loop_data")
        if loop_data is None:
            return

        params = getattr(loop_data, "params_temporary", None)
        if not isinstance(params, dict):
            return

        log_item = params.get("log_item_generating")
        if log_item is None:
            return

        content = getattr(log_item, "content", "")
        if not content:
            return

        transformed = transform_response(
            content,
            indent=indent,
            minify=minify,
            use_standard_mode=use_standard_mode,
        )
        if transformed == content:
            return

        # {} fallback (XML corruption) is history-only — skip log update
        if transformed == "{}":
            return

        update_log_item(
            self.agent,
            log_item,
            transformed,
            update_log=update_log,
            raw_message=content,
        )

        # Refresh response tool text if streaming failed to create log_item_response
        import json as _json

        try:
            parsed = _json.loads(transformed)
        except (ValueError, TypeError):
            parsed = {}

        if (
            isinstance(parsed, dict)
            and parsed.get("tool_name") == "response"
            and hasattr(self.agent, "context")
        ):
            tool_args = parsed.get("tool_args", {})
            if isinstance(tool_args, dict):
                response_text = tool_args.get("text") or tool_args.get("message")
                if isinstance(response_text, str) and response_text.strip():
                    resp_item = params.get("log_item_response")
                    if resp_item is None:
                        gen_id = getattr(log_item, "id", "")
                        resp_item = self.agent.context.log.log(
                            type="response",
                            heading=f"icon://chat {getattr(self.agent, 'agent_name', 'A0')}: Responding",
                            id=gen_id,
                        )
                        params["log_item_response"] = resp_item
                    resp_item.update(content=response_text)

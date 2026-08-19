"""Context Doctor: transform full response and update tool_args in-place."""

from __future__ import annotations

import json
from typing import Any, override

from helpers.extension import Extension
from helpers.plugins import get_plugin_config
from usr.plugins.context_doctor.helpers.context_doctor import (
    transform_response,
)


class ContextDoctorTool(Extension):
    @override
    async def execute(self, **kwargs: Any) -> None:
        if not self.agent:
            return

        config = get_plugin_config("context_doctor", agent=self.agent) or {}
        minify = config.get("minify", False)
        use_standard_mode = config.get("use_standard_mode", False)
        suppress_xml = config.get("suppress_xml", True)

        tool_args = kwargs.get("tool_args")
        if not isinstance(tool_args, dict):
            return

        loop_data = getattr(self.agent, "loop_data", None)
        if loop_data is None:
            return

        raw_response = getattr(loop_data, "last_response", "")
        if not raw_response:
            return

        transformed = transform_response(
            raw_response,
            minify=minify,
            use_standard_mode=use_standard_mode,
            suppress_xml=suppress_xml,
        )

        try:
            transformed_obj = json.loads(transformed)
        except (json.JSONDecodeError, TypeError):
            return

        repaired_args = transformed_obj.get("tool_args")
        if not isinstance(repaired_args, dict):
            return

        tool_args.clear()
        tool_args.update(repaired_args)

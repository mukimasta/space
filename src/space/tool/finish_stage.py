from __future__ import annotations

from space.tool.base import BaseTool


class FinishStageTool(BaseTool):
    name = "finish_stage"
    description = "Call this when you have completed all work for this stage. Do not call write_file or any other tool after this."
    parameters = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Brief summary of what was done in this stage."},
        },
        "required": ["summary"],
        "additionalProperties": False,
    }

    async def execute(self, **kwargs: str) -> str:
        return kwargs.get("summary", "Stage complete.")

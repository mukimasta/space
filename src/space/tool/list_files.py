from __future__ import annotations

import json

from space.store.base import FileStore
from space.tool.base import BaseTool


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List files and directories at a relative path inside the sandbox. Only call when you need to discover or browse files; not for simple greetings."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list. Use empty string for sandbox root.",
                "default": "",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def execute(self, **kwargs: str) -> str:
        path = kwargs.get("path", "")
        entries = await self._store.list(path)
        return json.dumps({"path": path, "entries": entries}, ensure_ascii=False)

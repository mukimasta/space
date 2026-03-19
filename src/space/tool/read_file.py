from __future__ import annotations

from space.store.base import FileStore
from space.tool.base import BaseTool


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read UTF-8 text content from a file path inside the sandbox. Do not call for a file you have already read in this conversation."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path inside sandbox."},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def execute(self, **kwargs: str) -> str:
        path = kwargs["path"]
        return await self._store.read(path)

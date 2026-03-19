from __future__ import annotations

from space.store.base import FileStore
from space.tool.base import BaseTool


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Delete a file at the given path inside the sandbox. Fails if path is a directory."
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
        await self._store.delete(path)
        return f"Deleted {path}"

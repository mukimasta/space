from __future__ import annotations

from space.store.base import FileStore
from space.tool.base import BaseTool


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write UTF-8 content to a file path inside the sandbox."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path inside sandbox."},
            "content": {"type": "string", "description": "File content to write."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def execute(self, **kwargs: str) -> str:
        path = kwargs["path"]
        content = kwargs["content"]
        await self._store.write(path, content)
        return f"Wrote {len(content)} chars to {path}"

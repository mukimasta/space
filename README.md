# space

Memory-native AI workspace with isolated conversational spaces.

## Current Status

Implemented:

- Phase 0: project scaffold (`uv`, package layout, dependency setup)
- Phase 1: data layer (`models`, config loader, sandboxed local file store, space data operations)
- Phase 2: LLM provider contracts + OpenRouter adapter
- Phase 3: Tool system (`read_file`, `write_file`, `list_files`, `confirm`, `run_agent`)
- Phase 4: Agent system (`agent_loop`, `ChatAgent`, `ArchiveAgent`, `TitleAgent`)
- Phase 5: Skill loader (frontmatter + instructions parsing)
- Phase 6 (mostly done): `AppService` command routing + archive/resume/continue + model switching

## Quick Start

```bash
uv sync --group dev
SPACE_HOME=/tmp/space-home uv run space
```

`uv run space` launches the stdin/stdout CLI.

The sandbox in this environment may block writing to `~/.space`, so `SPACE_HOME` is useful in local tests.

Before chatting, set `api_key` in `~/.space/config.json` (or `$SPACE_HOME/config.json`).
If it is empty, the app shows a clear validation error instead of a low-level HTTP header error.

`/status` shows current space/provider/model plus cumulative `tokens` and `cost` (when provider usage is available).
Provider/model switches are persisted back to `config.json`.

## Commands

```text
/space <name|index>
/spaces
/providers
/provider <name|index>
/models
/archive
/resume [index|filename]
/continue
/new
/exit
/model <name|index>
/status
/help
/quit
```

## Tests

```bash
uv run pytest -q
```

## Package Layout

```text
src/space/
  core/
  agent/
  skill/
  tool/
  channel/
  llm/
  store/
```

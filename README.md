# space

**Memory-native AI workspace**：在终端里用 **Textual TUI** 与 LLM 对话，通过多个相互隔离的 **Space** 管理长期上下文（`SPACE.md`、认知文档、记录与历史），避免「全局记忆串味」。

**技术亮点**：
- 🔄 Agent Loop — LLM + Tool 循环
- 📁 Tool Use — read / write / delete file
- 📋 多阶段 Pipeline — record → context → space-md
- 📜 Skill — Markdown 剧本
- 🔒 Sandbox — FileStore 沙箱

---

## 功能概览


| 能力                | 说明                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------- |
| **Space**         | 每个空间独立目录：`SPACE.md`、`context/`、`records/`、`history/`                                  |
| **聊天**            | 未进入 Space 时为纯对话（可流式）；进入 Space 后注入系统提示 + Context，并开放文件类 Tool                           |
| **归档 `/archive`** | 多阶段 Agent：写记录 → 更新 context → 更新 `SPACE.md` 索引，再保存完整 `history/*.jsonl` 并清空当前会话         |
| **历史**            | 自动保存 `history/_current.jsonl`；`/resume`、`/continue` 恢复；换 Space / 新开对话会写入带时间戳的 history |
| **模型**            | 支持 **OpenRouter**、**KKSJ**（OpenAI 兼容 API）；`/provider`、`/model` 可切换并写回 `config.json`   |
| **TUI**           | 状态栏 token/费用、流式 Markdown、工具调用摘要、Esc 中断流式、`/spaces` 等选择面板、对话 Rewind                    |


更完整的产品与交互设计见 `[docs/DESIGN.md](docs/DESIGN.md)`；实现阶段说明见 `[docs/PLAN.md](docs/PLAN.md)`。

---

## 环境要求

- **Python ≥ 3.13**
- 包管理：**uv**（见 `pyproject.toml` / `uv.lock`）

主要依赖：`httpx`、`textual`。

---

## 快速开始

```bash
uv sync --group dev
```

首次运行会在数据目录生成 `config.json`（若不存在）。

```bash
# 可选：自定义数据根目录（默认 ~/.space）
export SPACE_HOME=/tmp/space-home

uv run space
```

### 配置 `config.json`

路径：`$SPACE_HOME/config.json` 或 `~/.space/config.json`。


| 字段         | 说明                                                 |
| ---------- | -------------------------------------------------- |
| `api_key`  | OpenRouter 等使用的 Bearer Token；为空时启动会警告，请求会失败并给出明确错误 |
| `provider` | `openrouter` 或 `kksj`                              |
| `model`    | 模型 ID（如 `openai/gpt-4o-mini`）                      |
| `base_url` | API 根地址；切换 provider 时程序会按内置表或环境变量更新                |


**KKSJ** 可在环境中覆盖（与 `main.py` 中逻辑一致）：

- `KKSJ_API_KEY` — 优先于 config 里的 `api_key`（当 provider 为 kksj 时拼装逻辑会使用）
- `KKSJ_BASE_URL`
- `KKSJ_MODEL`（默认示例：`gemini-3-flash-preview`）

### 沙箱与权限

Space 数据落在 `$SPACE_HOME/spaces/<name>/`。`LocalFileStore` 禁止绝对路径与 `..` 逃逸，所有读写相对于该 Space 根目录。

---

## 命令一览

在输入框输入以下命令（TUI 中部分命令会弹出选择面板）：

```text
/space <name|index>     进入或创建 Space
/spaces                 列出 Space（TUI：选择面板）
/providers              选择 Provider（TUI：若无 key 可提示输入）
/provider <name|index>
/models [provider]      列出模型（TUI：选择面板）
/model <name|index>
/archive                归档当前对话（多阶段 + 写 history）
/resume [index|filename]  恢复历史（无参数时列出；TUI 可选面板）
/continue               优先加载 _current，否则最新 history
/new                    新会话（会先保存当前对话到 history）
/exit                   退出 Space
/status                 space、provider、model、消息数、tokens、费用
/help
/quit                   退出应用
```

`/status` 中的 `tokens`、`cost` 为会话内累计；具体是否含费用取决于 Provider 返回的 usage（如 OpenRouter）。

---

## 磁盘布局

数据根：`~/.space` 或 `$SPACE_HOME`。

```text
.space/
├── config.json
└── spaces/
    └── <space_name>/
        ├── SPACE.md           # 空间描述 + ## Context 索引（引用 context/*.md）
        ├── context/           # 认知层 Markdown（归档等流程可更新）
        ├── records/           # 本轮对话提炼的记录（归档 record 阶段）
        └── history/
            ├── _current.jsonl # 当前会话自动保存（autosave）
            └── *.jsonl        # 带 meta 首行的历史存档
```

`SPACE.md` 里 `## Context` 小节下列出的 `*.md` 会按索引顺序（再补全其余文件）加载进系统提示，见 `core/space.py` 中 `load_space`。

---

## 设计说明：分层与接口

本项目的结构目标在 `[docs/DEVELOP.md](docs/DEVELOP.md)` 里写得很清楚：**优雅、简洁、模块化、结构清晰、去耦合**。落地时，**边界主要靠 `typing.Protocol` 定义的「接口」** 划开——上层只依赖协议，不关心具体是 OpenRouter 还是本地目录存储，从而便于替换实现与单测注入 mock。

### 设计意图（摘自开发文档）

- **Agent**：运行时主体；持有（或通过消息携带）system prompt、一组 Tool，在 **LLM ↔ Tool** 的循环里推理与行动。归档等多阶段流程由 `AppService` 编排，每阶段注入不同 Skill 指令。
- **Skill**：静态「剧本」——Markdown + frontmatter，被加载成指令文本交给 Agent；**不**直接执行 I/O。用户触发的长流程（如 `/archive`）用 Skill 描述各阶段行为（见 `skill/skills/archive/*.md`）。
- **Tool**：能力单元；**对外**用 JSON Schema 描述参数（`to_api_dict()` → OpenAI 式 tools），**对内** `execute`。依赖一律 **构造注入**（例如 `FileStore`），Tool 自己不知道「全局路径」。
- **Sandbox**：不是单独类型，而是 **FileStore 的实现契约**——每个实例绑定一个 root，路径相对 root，禁止 `..` / 绝对路径逃逸（`store/local.py` 的 `LocalFileStore`）。谁能写盘，由 **App 注入哪一个 root 的 FileStore** 决定，Agent 无法自行扩大范围。

更完整的概念图与伪代码见 **DEVELOP.md** 的「层次关系」「接口定义」「主循环」三节。

### 层次关系（接口为中心）

```text
                        Skill (static prompt text)
                                     │ load
                                     ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ AppService — composition root: routing, messages, tool bundles, store roots   │
└───────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │                    │
         ▼                    ▼                    ▼                    ▼
   LLMProvider            Tool               FileStore          MessageChannel
    (Protocol)         (Protocol)           (Protocol)            (Protocol)
         │                    │                    ▲                    │
         │                    └────────────────────┘                    │
         │                            uses                              │
         ▼                              ▼                               ▼
  OpenRouterProvider,            LocalFileStore                  StdioChannel
  KKSJProvider                 (sandboxed per space)              (injected)
```

`**AppService**` 是组合根（composition root）：在 `main.py` 里装配具体 Provider、根 `LocalFileStore`、`space_store_factory`（每个 Space 子目录一个沙箱）、`llm_builder` / `settings_persistor` 等；业务测试里也可只构造 `AppService` 而不启动 TUI。

### 核心接口（与代码一致）

以下与 `src/space` 中 `Protocol` 定义对齐；细节以源码为准。


| 接口                   | 职责                                                            | 当前实现示例                                                                    |
| -------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `**FileStore**`      | 异步文件抽象；沙箱由实现保证                                                | `LocalFileStore`                                                          |
| `**LLMProvider**`    | `generate`（含 tool_calls）、`stream`（流式正文）、`list_models`         | `OpenRouterProvider`, `KKSJProvider`                                      |
| `**Tool**`           | `name` / `description` / `parameters`、`execute`、`to_api_dict` | `read_file`, `write_file`, `list_files`, `delete_file`, `finish_stage`, … |
| `**MessageChannel**` | `receive` / `send`（`InputEvent` / `OutputEvent`）              | `StdioChannel`（已注入 `AppService`，便于后续 TUI Channel、确认流）                     |


**Agent 运行时**并不强制每个 Agent 都实现单一 `Agent` Protocol；共性逻辑在 `**agent_loop`**（`agent/base.py`）：`llm.generate` → 若有 tool_calls 则 `tool.execute` 并追加消息 → 直到无工具调用、触发 `finish_tool_name`、或超出 `max_iterations`。`ArchiveAgent` 在此基础上按阶段挂上不同 system 指令与 `FinishStageTool`。

DEVELOP.md 里 `**LLMProvider` 示例** 把流式写成 `generate(..., stream=...)`；**当前代码** 为 `**generate` + 独立的 `stream`**（`llm/base.py`），便于 TUI 在无 Tool 场景下边收 token 边渲染。

### 数据与配置（非接口但属于设计边界）

- **共享模型**（`models.py`）：`Message`, `Space`, `LoadedSpace`, `HistoryMeta`, `AppState` —— 跨层传递的状态与持久化形状。
- **配置**（`config.py`）：`Config` 与 `config.json` 读写；与 LLM 接口正交，由入口装配进 Provider。

### 与 UI 的边界

**Textual** 的 `SpaceApp` 只负责展示与输入；每次发送调用 `AppService.handle_input`，通过回调 `on_token` / `on_tool_call` / `cancel` 与流式、工具可视化、中断协作，避免 TUI 直接依赖 `httpx` 或文件路径。

---

## 开发与测试

```bash
uv sync --group dev
uv run pytest -q
```

- 默认包含异步测试（`pytest-asyncio`，`asyncio_mode = auto`）  
- 需要真实 API 的测试可标 `@pytest.mark.e2e`，排除：  
`uv run pytest -q -m "not e2e"`

辅助脚本见 `scripts/`（如归档相关调试）。

---

## 包目录结构

```text
src/space/
├── main.py
├── config.py
├── models.py
├── core/           # AppService, conversation, space 数据操作
├── agent/          # agent_loop, ArchiveAgent
├── skill/          # loader + skills/archive/*.md
├── tool/
├── llm/
├── store/          # FileStore, LocalFileStore
├── channel/
└── tui/
```

---

## 许可证与作者

见 `pyproject.toml` 中 `authors` 字段。
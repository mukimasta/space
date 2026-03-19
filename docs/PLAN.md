# Implementation Plan

分阶段实现，每个阶段结束后都有可验证的产出。前一阶段是后一阶段的依赖。


## Phase 0: 项目脚手架

- `uv init` 初始化项目
- 创建完整的包目录结构（空 `__init__.py`）
- `pyproject.toml` 添加依赖：`textual`, `httpx`（用于异步 HTTP 请求 LLM API）
- 创建 `~/.space/` 数据目录和 `config.json` 模板

验证：`uv run python -c "import space"` 不报错


## Phase 1: 数据层

### models.py

定义共享数据模型：
- `Message(role, content, timestamp)` — 对话消息
- `Space(name, path)` — Space 元数据
- `AppState(space, conversation, model, provider)` — 应用状态

### store/base.py

FileStore 协议定义。

### store/local.py

LocalFileStore 实现：
- 构造函数接收 `root: Path`，所有操作相对于 root
- **沙箱校验**：每个方法在执行前 resolve 完整路径，确认在 root 内。拒绝 `../`、绝对路径、符号链接逃逸
- 实现 `read`, `write`, `list`, `exists`, `mkdir`
- `write` 自动创建父目录

### config.py

- 读取 `~/.space/config.json`
- 首次运行时创建默认配置
- 字段：`api_key`, `provider`（openrouter/openai）, `model`, `base_url`

### core/space.py

Space 数据操作（纯数据，不涉及 LLM）：
- `load_space(name, store)` — 读取 SPACE.md + 所有 context/*.md
- `list_spaces(store)` — 列出所有 Space
- `create_space(name, store)` — 创建 Space 目录结构 + 空 SPACE.md
- `save_history(conversation, store)` — 对话存入 history/*.jsonl

验证：单元测试，用临时目录测试 LocalFileStore 沙箱 + Space 读写


## Phase 2: LLM 层

### llm/base.py

- `LLMResponse(content, tool_calls)` 数据类
- `ToolCall(id, name, arguments)` 数据类
- `LLMProvider` 协议：拆成两个方法更清晰
  - `generate(messages, tools?)` → `LLMResponse`（用于 Agent tool loop）
  - `stream(messages)` → `AsyncIterator[str]`（用于 Chat 流式输出）

### llm/openrouter.py

OpenRouter 实现（兼容 OpenAI API 格式）：
- 用 `httpx.AsyncClient` 发请求
- `generate()` — 普通请求，解析 response JSON，提取 content 或 tool_calls
- `stream()` — SSE 流式请求，`async for` 逐 chunk yield token
- tool calling：将 `list[ToolDef]` 转成 OpenAI tools 格式发送
- 错误处理：HTTP 错误、速率限制、超时

验证：写一个测试脚本，调 OpenRouter API，发一条消息拿到回复；发一条带 tools 的消息拿到 tool_call


## Phase 3: Tool 系统

### tool/base.py

Tool 协议：
- `name`, `description`, `parameters`（JSON Schema）
- `execute(**kwargs) -> str`
- `to_api_dict()` — 转成 OpenAI tools 格式的 dict

### 文件 Tools

基于 FileStore 实现，构造时注入 FileStore 实例：
- `read_file.py` — ReadFileTool
- `write_file.py` — WriteFileTool
- `list_files.py` — ListFilesTool

### tool/confirm.py

ConfirmTool：
- 向用户展示内容，等待用户确认（同意/拒绝/修改）
- 依赖 MessageChannel，构造时注入
- 用户拒绝时返回拒绝信息，Agent 可据此调整行为

### tool/run_agent.py

RunAgentTool：
- 启动另一个 Agent 作为子任务
- 需要访问 Agent 注册表来查找并实例化 Agent
- 返回子 Agent 的最终输出

验证：单元测试 Tool 的 `to_api_dict()` 输出符合 OpenAI 格式；测试文件 Tools 配合 LocalFileStore 沙箱


## Phase 4: Agent 系统

### agent/base.py

Agent tool loop 的核心实现：
- `agent_loop(llm, messages, tools)` — 通用的 tool 循环函数
  - 调用 `llm.generate(messages, tools=...)`
  - 如果有 tool_calls → 执行每个 tool → 将结果追加到 messages → 继续循环
  - 如果无 tool_calls → 返回 content
- 边界情况：
  - tool 执行出错 → 将错误信息作为 tool result 返回给 LLM
  - 循环次数上限（防止无限循环）
  - 用户通过 Esc 中断

### agent/chat.py

Chat Agent：
- 不使用 tool loop，直接调 `llm.stream()`
- `run(messages) -> AsyncIterator[str]`
- 不持有 system prompt——由 AppService 组装好放进 messages

### agent/archive.py

Archive Agent：
- 使用 agent_loop 执行 tool 循环
- system prompt 来自 archive SKILL.md + 当前对话内容
- 可用 tools：read_file, write_file, list_files, confirm, run_agent
- Agent 自主决定：读哪些文件、生成什么记录、更新哪些 context、是否更新 SPACE.md

### agent/title.py

Title Agent：
- 最简单的 Agent，不需要 tools
- 接收对话片段，返回标题字符串
- 直接调 `llm.generate()`，解析 content

验证：测试脚本，手动构造 messages + tools，运行 agent_loop，验证 tool 被正确调用和循环终止


## Phase 5: Skill 系统

### skill/loader.py

解析 SKILL.md（遵循 Agent Skills 规范）：
- 解析 YAML frontmatter → 提取 name, description
- 解析 Markdown body → 作为 Agent 的指令文本
- 返回 `SkillDef(name, description, instructions)` 数据对象

### skill/skills/archive/SKILL.md

归档 Skill 定义。YAML frontmatter + Markdown 指令：
- 描述归档任务的完整指令
- 告诉 Agent：先读已有 context 和 SPACE.md，理解当前认知状态
- 从对话中提炼记录，用 confirm 让用户确认后写入
- 判断是否有新认知需要沉淀，用 confirm 确认后更新 context
- 判断 SPACE.md 是否需要更新，用 confirm 确认后更新
- 每步确认后才执行写入

验证：loader 能正确解析 SKILL.md，提取出 name 和 instructions


## Phase 6: Core 应用逻辑

### core/conversation.py

对话管理：
- `build_system_prompt(space?)` — 组装 system prompt
  - 无 Space：通用 system prompt
  - 有 Space：SPACE.md 内容 + 所有 context 文档内容拼接
- `to_api_messages(conversation)` — 将内部 Message 列表转成 API 格式

### core/app.py

AppService — 应用核心，管理状态和命令路由：

状态：
- `state: AppState` — 当前空间、对话、模型配置

内部命令：
- `/space <name>` — 加载 Space，重置对话，组装 system prompt
- `/spaces` — 列出所有 Space，展示选择面板
- `/new` — 清空 conversation，保持当前 Space
- `/exit` — 清空 Space 和 conversation，回到普通聊天
- `/resume` — 列出 history/*.jsonl，选择后加载到 conversation
- `/continue` — 加载最新的 history
- `/model <name>` — 切换模型
- `/status` — 展示当前状态
- `/quit` — 退出应用

Agent 命令：
- `/archive` — 创建 Archive Agent，加载 archive SKILL.md 作为指令，注入 tools（沙箱 FileStore root 为当前 Space 路径），运行 agent_loop

对话处理：
- `chat(user_input)` — 追加用户消息 → 组装 messages → Chat Agent → 流式输出 → 追加 assistant 消息

验证：不接 TUI，用简单的 stdin/stdout 循环测试 AppService


## Phase 7: TUI

### channel/base.py

MessageChannel 协议 + 事件类型：
- `InputEvent` — 用户输入（文本 or 命令）
- `OutputEvent` — 输出事件（文本、流式 token、状态更新、确认请求等）

### channel/tui/app.py

Textual App，类 Claude Code 布局：

组件：
- `MessageArea` — 消息显示区，Markdown 渲染，向上滚动
- `InputArea` — 底部输入框，多行，Enter 发送
- `StatusBar` — 最底部：token 用量 · 费用 | provider · model | Space 名

交互：
- Enter → 提取文本 → 发给 AppService
- 流式输出：Chat Agent yield token → TUI 实时追加渲染
- Esc → 中断当前 LLM 请求
- 双击 Esc → 滚动到历史消息位置
- Confirm 交互：展示内容 + 确认/拒绝按钮 → 返回结果给 Agent

验证：启动 TUI，能输入、发送、收到流式回复、状态栏显示正确


## Phase 8: 入口与集成

### main.py

组装所有依赖，启动应用：
1. 加载 config
2. 创建 LocalFileStore（root: `~/.space/`）
3. 创建 LLMProvider（根据 config 选择 provider）
4. 创建 Textual App
5. 创建 Tools（注入 FileStore、Channel）
6. 创建 AppService（注入 LLMProvider、FileStore、Tools、Channel）
7. 启动 Textual App

`pyproject.toml` 入口点：`space = "space.main:main"`

验证：`uv run space` 启动完整应用，能进行普通对话


## Phase 9: 端到端功能

按顺序逐个打通：

1. **普通对话** — 启动 → 输入 → 流式回复 → 多轮对话
2. **Space 创建与进入** — `/space dreams` → 创建目录 → 进入 → 对话
3. **Space 记忆** — 进入已有 Space → system prompt 体现记忆
4. **归档** — `/archive` → Archive Agent 运行 → 逐步确认 → 文件写入 → 对话清空
5. **历史恢复** — `/resume` → 选择历史 → 加载对话 → 继续
6. **配置命令** — `/model`, `/status`, `/spaces`


## 依赖关系

```
Phase 0  脚手架           ← 无依赖
Phase 1  数据层           ← 无依赖
Phase 2  LLM 层           ← models
Phase 3  Tool 系统        ← store, models
Phase 4  Agent 系统       ← llm, tool
Phase 5  Skill 系统       ← 无代码依赖
Phase 6  Core 应用逻辑    ← agent, skill, space, conversation
Phase 7  TUI              ← channel 协议
Phase 8  入口与集成        ← 全部
Phase 9  端到端功能        ← 全部
```

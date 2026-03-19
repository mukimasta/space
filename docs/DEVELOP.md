开发要求：优雅，简洁，有审美，易用，模块化，结构清晰，去耦合

## 技术栈

- **语言**：Python + asyncio
- **TUI**：Textual（类 Claude Code 风格）
- **包管理**：uv
- **配置格式**：JSON
- **数据目录**：`~/.space/`


## 核心概念

### Agent

运行时实体。拥有 system prompt、一组 Tools、通过 LLM 循环推理和行动。

Agent 是系统中唯一的"主体"——只有 Agent 能思考、决策、执行。

- **Chat Agent**：主对话 Agent。在 Space 中时加载 SPACE.md + context 作为 system prompt。
- **Archive Agent**：归档 Agent。读取对话和已有认知，生成记录、更新 context、更新 SPACE.md。
- **Title Agent**：生成对话标题。

Agent 启动方式：
- **App 直接启动**：响应用户命令（如 `/archive`）
- **Agent 通过 tool call 启动另一个 Agent**：通过 `run_agent` tool

### Skill

静态定义。遵循 [Agent Skills 规范](https://agentskills.io/specification)，是 Agent 的"剧本"。

每个 Skill 是一个目录 + `SKILL.md`，提供 Agent 执行任务时的 prompt 和指令。Skill 本身不启动任何东西——Agent 加载 Skill 的指令来执行。

只有用户可触发的工作流才是 Skill（如 `/archive`）。内部功能（如 `/space`、`/new`、`/exit`）是 App 命令，不是 Skill。

### Tool

能力单元。每个 Tool 自包含定义（给 LLM API）和实现（实际执行）。

不同 Agent 拿不同的 Tool 组合。Tool 的依赖（FileStore、MessageChannel）通过构造函数注入。


### Sandbox

Agent 通过 Tool 操作文件，所有文件操作必须限制在安全范围内。

沙箱在 FileStore 层实现：每个 FileStore 实例绑定一个 root 路径，所有操作的路径都相对于 root，且不允许逃逸（`../`、符号链接、绝对路径）。

- Archive Agent 的 FileStore root → `~/.space/spaces/{space_name}/`
- Chat Agent 无文件操作权限

创建 Agent 时，由 App 决定给它什么 root 的 FileStore，Agent 自身无法突破边界。


## 层次关系

```
Agent（运行时：system prompt + tool loop 循环）
  ↓ 推理                ↓ 调用
LLMProvider            Tool
                        ↓ 依赖
                   FileStore / MessageChannel

Skill（静态：SKILL.md，提供 Agent 的指令）
  ↑ 加载
Agent
```


## 代码结构

```
space/
├── main.py                         # 入口：组装依赖，启动
├── config.py                       # 配置加载
├── models.py                       # 共享数据模型
│
├── core/
│   ├── app.py                      # AppService：状态管理 + 命令路由
│   ├── space.py                    # Space 数据操作
│   └── conversation.py             # 对话管理、prompt 组装
│
├── agent/
│   ├── base.py                     # Agent 协议 + tool loop
│   ├── chat.py                     # Chat Agent
│   ├── archive.py                  # Archive Agent
│   └── title.py                    # Title Agent
│
├── skill/
│   ├── loader.py                   # 解析 SKILL.md
│   └── skills/                     # Skill 定义
│       └── archive/
│           └── SKILL.md
│
├── tool/
│   ├── base.py                     # Tool 协议
│   ├── read_file.py
│   ├── write_file.py
│   ├── list_files.py
│   ├── confirm.py
│   └── run_agent.py                # Agent 启动 Agent
│
├── channel/
│   ├── base.py                     # MessageChannel 协议
│   └── tui/
│       ├── app.py                  # Textual App
│       └── components/
│
├── llm/
│   ├── base.py                     # LLMProvider 协议
│   ├── openrouter.py
│   └── openai.py
│
└── store/
    ├── base.py                     # FileStore 协议
    └── local.py
```


## 数据结构

```
~/.space/
├── config.json                     # API keys, 默认模型, provider
└── spaces/
    └── {space_name}/
        ├── SPACE.md
        ├── context/
        │   └── *.md
        ├── records/
        │   └── *.md
        └── history/
            └── *.jsonl
```


## 接口定义

### MessageChannel

```python
class MessageChannel(Protocol):
    async def receive(self) -> InputEvent: ...
    async def send(self, event: OutputEvent) -> None: ...
```

实现：TuiChannel, TelegramChannel

### LLMProvider

```python
class LLMProvider(Protocol):
    async def generate(self,
                       messages: list[Message],
                       tools: list[ToolDef] | None = None,
                       stream: bool = False) -> LLMResponse: ...
```

实现：OpenRouterProvider, OpenAIProvider

```python
@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] | None

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
```

### FileStore

```python
class FileStore(Protocol):
    async def read(self, path: str) -> str: ...
    async def write(self, path: str, content: str) -> None: ...
    async def list(self, path: str) -> list[str]: ...
    async def exists(self, path: str) -> bool: ...
    async def mkdir(self, path: str) -> None: ...
```

实现：LocalFileStore

### Tool

```python
class Tool(Protocol):
    name: str
    description: str
    parameters: dict              # JSON Schema

    async def execute(self, **kwargs) -> str: ...
```

### Agent

```python
class Agent(Protocol):
    async def run(self,
                  messages: list[Message],
                  tools: list[Tool],
                  llm: LLMProvider) -> str: ...
```

Agent tool loop 伪代码：

```python
async def agent_loop(llm, messages, tools):
    tool_defs = [t.to_api_dict() for t in tools]
    while True:
        response = await llm.generate(messages, tools=tool_defs)
        if not response.tool_calls:
            return response.content
        for call in response.tool_calls:
            tool = find_tool(tools, call.name)
            result = await tool.execute(**call.arguments)
            messages.append(tool_message(call.id, result))
```


## 主循环

```
Textual App 启动 → 渲染界面 → 等待输入
                                ↓
                         用户提交输入
                                ↓
                    ┌── "/" 开头：命令
                    │     ├── 内部命令 (/space, /new, /exit, /model...)
                    │     │     → AppService 直接处理
                    │     └── Agent 命令 (/archive...)
                    │           → 创建对应 Agent
                    │           → Agent 加载 Skill（SKILL.md）作为指令
                    │           → Agent 运行 tool loop
                    │
                    └── 普通文本：对话
                          → Chat Agent
                          → 组装 system prompt (SPACE.md + contexts)
                          → conversation + user message
                          → LLMProvider.generate(stream=True)
                          → TUI 逐 token 渲染
                          → 完整响应追加到 conversation
```


## TUI


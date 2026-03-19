# 我是如何设计 Space 的（下篇）：系统设计

上篇聊了产品层面的思考——为什么需要"空间"，记忆如何生长，归档的仪式感。这篇展开系统设计：如何把这些想法变成一个可实现的架构。

## 技术选型

**Python + asyncio**。LLM 生态最成熟，TUI 框架选择多，异步天然适合 LLM 流式调用和 IO 操作。

**Textual** 做 TUI。目标是类 Claude Code 的终端体验——底部输入框，消息向上滚动，状态栏。Textual 组件化、支持样式，能实现这种布局。

**uv** 做包管理。快。

**JSON** 做配置。Python 原生支持，不需要额外依赖。

关于框架：没有用 LangGraph 或 LangChain。归档流程本质就是线性步骤加用户确认，不需要图执行引擎。引入重框架只会增加理解成本和依赖，不值得。

## 三个核心接口

系统的底层是三个接口，负责与外部世界交互：

```python
class MessageChannel(Protocol):
    """消息通道：负责与用户的输入输出"""
    async def receive(self) -> InputEvent: ...
    async def send(self, event: OutputEvent) -> None: ...

class LLMProvider(Protocol):
    """模型调用：负责与 LLM API 通信"""
    async def generate(self, messages, tools?) -> LLMResponse: ...
    async def stream(self, messages) -> AsyncIterator[str]: ...

class FileStore(Protocol):
    """文件存储：负责数据的持久化"""
    async def read(self, path) -> str: ...
    async def write(self, path, content) -> None: ...
    async def list(self, path) -> list[str]: ...
    async def exists(self, path) -> bool: ...
    async def mkdir(self, path) -> None: ...
```

每个接口可以有多种实现——MessageChannel 可以是 TUI 或 Telegram，LLMProvider 可以是 OpenRouter 或 OpenAI，FileStore 可以是本地文件系统。核心逻辑不 import 任何具体实现，依赖在入口处组装注入。

LLMProvider 拆成 `generate()` 和 `stream()` 两个方法：前者用于 Agent 的 tool loop（需要完整响应来判断是否有 tool call），后者用于 Chat 的流式输出（逐 token 渲染到 TUI）。

## Agent / Skill / Tool

这是架构的核心。三个概念，各有边界。

### Agent：唯一的运行时主体

Agent 是系统中唯一能"做事"的实体——拥有 system prompt、一组 Tools，通过 LLM 循环推理和行动。

系统里的 Agent：

- **Chat Agent**：主对话。在 Space 中时加载 SPACE.md + Context 作为 system prompt，不在 Space 中时用通用 prompt。不使用 tools。
- **Archive Agent**：归档。接收当前对话，自主读取已有认知文件，生成记录、更新 Context、更新 SPACE.md。
- **Title Agent**：给对话生成标题，最简单的 Agent，一次 LLM 调用即可。

Agent 的启动方式有两种：App 直接启动（响应用户命令），或者 Agent 通过 tool call 启动另一个 Agent。后者意味着 `run_agent` 本身就是一个 Tool。

### Skill：Agent 的剧本

Skill 是静态定义，遵循 [Agent Skills 规范](https://agentskills.io/specification)。每个 Skill 是一个目录加一个 `SKILL.md` 文件，里面是 YAML frontmatter（name、description）和 Markdown 指令。

Skill 提供 Agent 执行任务时的 prompt 和指令。Skill 本身不启动任何东西——Agent 主动加载 Skill 来获取指令。

一个关键区分：只有用户可触发的工作流才是 Skill（比如 `/archive`）。内部功能（`/space`、`/new`、`/exit`）是 App 自己的命令，不需要走 Skill 规范。

### Tool：Agent 的手

Tool 是能力单元。每个 Tool 自包含两部分：给 LLM 看的定义（name、description、JSON Schema 参数），和实际执行的实现。

```python
class Tool(Protocol):
    name: str
    description: str
    parameters: dict        # JSON Schema

    async def execute(self, **kwargs) -> str: ...
```

文件操作的 Tools（read_file、write_file、list_files）基于 FileStore 实现，confirm 基于 MessageChannel 实现，run_agent 用于 Agent 启动 Agent。不同 Agent 拿不同的 Tool 组合——Chat Agent 不需要任何 tools，Archive Agent 需要文件读写和用户确认。

### 三层关系

```
Agent（运行时：system prompt + tool loop）
  ↓ 推理                ↓ 调用
LLMProvider            Tool
                        ↓ 依赖
                   FileStore / MessageChannel

Skill（静态：SKILL.md）
  ↑ 加载
Agent
```

Agent 加载 Skill、调用 Tool、驱动 LLM。Skill 是剧本，Tool 是手，LLM 是大脑。

## Tool Calling 机制

Agent 如何使用 Tools？通过 LLM API 的 tool calling 机制。

发送请求时，除了 messages，还附带 tools 定义。LLM 可能返回普通文本，也可能返回 tool_calls——告诉你它想调用哪个 tool、传什么参数。我们执行 tool，把结果追加到 messages，再次调用 LLM。如此循环，直到 LLM 返回普通文本为止。

```python
async def agent_loop(llm, messages, tools):
    while True:
        response = await llm.generate(messages, tools=tools)
        if not response.tool_calls:
            return response.content
        for call in response.tool_calls:
            tool = find_tool(tools, call.name)
            result = await tool.execute(**call.arguments)
            messages.append(tool_result(call.id, result))
```

以 `/archive` 为例，Archive Agent 的 tool loop 可能是这样运转的：

1. Agent 调用 `list_files("context/")` → 看有哪些认知文档
2. Agent 调用 `read_file("SPACE.md")` → 读空间描述
3. Agent 调用 `read_file("context/symbols.md")` → 读已有认知
4. Agent 思考，生成记录摘要
5. Agent 调用 `confirm("以下是生成的记录：...")` → 用户确认
6. Agent 调用 `write_file("records/2025-06-15-falling-dream.md", "...")`
7. Agent 调用 `confirm("以下是 context 更新：...")` → 用户确认
8. Agent 调用 `write_file("context/symbols.md", "...")`
9. 循环结束，Agent 返回最终文本

整个过程中，Agent 自主决定读什么、改什么、写什么。我们只提供 tools 和 Skill 指令，不硬编码流程。

边界情况也要处理：tool 执行出错时，将错误信息作为 tool result 返回给 LLM，让它自行调整；设置循环次数上限，防止无限循环；用户可以按 Esc 中断。

## 沙箱 Sandbox

Agent 通过 tool call 操作文件。但 tool call 的参数来自 LLM 输出——LLM 可能输出任意路径。如果没有限制，Archive Agent 理论上可以读写你电脑上的任何文件。

沙箱在 **FileStore 层**实现。每个 FileStore 实例绑定一个 root 路径，所有操作的路径相对于 root，且不允许逃逸——拒绝 `../`、绝对路径、符号链接。

创建 Agent 时，App 决定给它什么 root 的 FileStore：Archive Agent 的 root 是 `~/.space/spaces/{space_name}/`，它只能操作当前 Space 的文件。Agent 自身无法突破这个边界。

沙箱不在 Tool 层也不在 Agent 层做，因为 FileStore 是所有文件操作的唯一出口，在这里卡住最干净。

## 流式输出与 Prompt Cache

Chat Agent 和 Archive Agent 对 LLM 的使用方式不同。Chat Agent 需要流式输出——用户发一条消息，回复逐 token 渲染到屏幕上。Archive Agent 需要完整响应——它要判断 LLM 返回的是文本还是 tool_calls，然后决定下一步。

所以 LLMProvider 有两个方法：`stream()` 返回 `AsyncIterator[str]`，`generate()` 返回完整的 `LLMResponse`。

关于 prompt caching，我们的架构天然适合。每次 API 调用的 messages 结构是：system prompt（SPACE.md + contexts）在最前面，然后是对话历史，最后是新消息。前缀始终稳定，只有尾部在增长。OpenAI 兼容 API 的自动 prefix caching 会直接生效——前缀相同就命中缓存，不需要改任何代码。

## 不做什么

架构设计中，决定不做什么和决定做什么同样重要。

**不搞 SpaceAgent**。进入 Space 时，Chat Agent 就是 Chat Agent，只是 system prompt 变了（加载 SPACE.md + contexts）。行为逻辑、tools、推理方式完全一样。单独搞一个 SpaceAgent 只是多了一层名字，没有多出任何能力。

**新 Space 不需要初始化 Agent**。新建 Space 之后直接对话就好。SPACE.md 一开始是空的，多次归档后，Archive Agent 会逐步填充空间描述和认知文档，Space 自然成型。

**内部命令不是 Skill**。`/space`、`/new`、`/exit` 这些是 App 自己的功能，逻辑简单明确（加载数据、清空对话、切换状态），不需要 LLM 参与，不需要遵循 Agent Skills 规范。只有需要 Agent 执行的工作流才是 Skill。

**Cache 不需要额外设计**。架构天然前缀稳定，自动 caching 就够了。Anthropic 的显式 cache_control 可以预留接口，但现在不加。

**不用重框架**。归档流程就是线性步骤，agent tool loop 就是一个 while 循环。几十行代码能解决的事，不需要引入一个框架。
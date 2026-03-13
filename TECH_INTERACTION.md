# myLabAgent Technical Interaction Guide

这份文档面向长期维护，重点说明 `myLabAgent` 当前的共享运行时、`Web` 交互形态和 `CLI` 交互形态分别是什么、各自依赖哪些模块，以及后续应该把变更放到哪里。

## 1. 项目一句话说明

`myLabAgent` 是一个基于 `OpenAI SDK 兼容接口` 的实验室 Agent 项目，当前同时支持：

1. `Web` 端交互，基于 `Streamlit`
2. `CLI` 端交互，基于 `argparse + rich`

这两个入口共享同一套 Agent runtime、RAG、工具注册和会话落盘能力。

## 2. 维护原则

后续维护时，优先遵守这条边界：

- `共享 runtime` 负责模型调用、工具调用、会话数据、RAG、权限
- `Web` 只负责 Streamlit UI 和 `st.session_state`
- `CLI` 只负责命令解析、终端输入输出和 Rich 渲染

一句话说：

`不要把 Web 状态写进共享 runtime，也不要把 CLI 渲染逻辑写进 Agent core。`

## 3. 当前整体结构

可以把项目拆成 4 层：

1. `Client Layer`
   - `app.py`
   - `ui_tabs/`
   - `cli.py`
   - `cli_repl.py`
   - `cli_render.py`
2. `Shared Runtime Layer`
   - `agent_core.py`
   - `services/agent_factory.py`
   - `services/session_service.py`
   - `services/chat_service.py`
3. `Knowledge and Tool Layer`
   - `rag_engine.py`
   - `core/tool_registry.py`
   - `core/permissions.py`
   - `core/skill_loader.py`
   - `config/tools.json`
4. `Persistence Layer`
   - `core/session_store.py`
   - `project_catalog/`
   - `license_catalog/`
   - `vector_store.json`
   - `chroma_db/`

## 4. 共享 Runtime

### 4.1 核心共享模块

共享 runtime 的核心文件有：

- [agent_core.py](D:\tongjiLabAgent\myLabAgent\agent_core.py)
- [services/agent_factory.py](D:\tongjiLabAgent\myLabAgent\services\agent_factory.py)
- [services/session_service.py](D:\tongjiLabAgent\myLabAgent\services\session_service.py)
- [core/session_store.py](D:\tongjiLabAgent\myLabAgent\core\session_store.py)
- [rag_engine.py](D:\tongjiLabAgent\myLabAgent\rag_engine.py)

它们是 Web 和 CLI 共同依赖的部分。

### 4.2 Agent 创建入口

共享的 runtime 创建入口现在是：

- [agent_factory.py](D:\tongjiLabAgent\myLabAgent\services\agent_factory.py)

`build_agent_runtime(...)` 的职责：

1. 创建 `RAGEngine`
2. 根据 `permission_mode` 构造 `PermissionManager`
3. 创建 `ToolRegistry`
4. 创建 `SkillLoader`
5. 加载 `prompts/lab_agent.md`
6. 实例化 `LabAgent`

这个文件不应该依赖 `streamlit`，也不应该依赖 CLI 的渲染逻辑。

### 4.3 Agent 主循环

- [agent_core.py](D:\tongjiLabAgent\myLabAgent\agent_core.py)

`LabAgent.chat(...)` 目前是共享 runtime 的主循环，负责：

1. 组装 `system prompt + history messages`
2. 发起第一次模型请求
3. 如果模型返回 `tool_calls`，则执行工具并把 `role="tool"` 消息拼回上下文
4. 如有必要继续下一轮工具调用
5. 最终以事件流的方式 `yield` 回调用方

当前会产出的事件类型主要有：

1. `thought`
2. `reasoning`
3. `tool_exec`
4. `tool_result`
5. `answer_chunk`
6. `error`

这套事件流是 Web 和 CLI 的共同协议。

### 4.4 Session 与 Task

底层会话落盘：

- [session_store.py](D:\tongjiLabAgent\myLabAgent\core\session_store.py)

高层会话封装：

- [session_service.py](D:\tongjiLabAgent\myLabAgent\services\session_service.py)

当前职责分工：

- `SessionStore`
  - 负责 JSON 落盘
  - 负责 `create/load/append_message/start_task/finish_task`
- `SessionService`
  - 负责更高层的消息追加和 session 查询
  - 负责 `create_or_resume_session`
  - 负责 `append_user_message` / `append_assistant_message`
  - 负责 `list_sessions`

后续如果要改 session 文件结构，优先改这里，不要散落在 UI 层里硬写 JSON。

### 4.5 工具与权限

共享工具系统由这些文件组成：

- [tool_registry.py](D:\tongjiLabAgent\myLabAgent\core\tool_registry.py)
- [permissions.py](D:\tongjiLabAgent\myLabAgent\core\permissions.py)
- [tools.json](D:\tongjiLabAgent\myLabAgent\config\tools.json)
- [skill_loader.py](D:\tongjiLabAgent\myLabAgent\core\skill_loader.py)

当前已注册工具：

1. `retrieve_document`
2. `recognize_handwritten_digit`
3. `get_amap_weather`
4. `load_skill`

当前权限等级包括：

1. `READ_ONLY`
2. `NETWORK`
3. `FILE_WRITE`
4. `EXEC`

`agent_factory.py` 里又在权限等级之上提供了更高层的运行模式：

1. `read-only`
2. `workspace-write`
3. `full-access`

这层是给 CLI 和未来多入口统一使用的，不是给模型直接看的。

### 4.6 Skill 机制

- [skill_loader.py](D:\tongjiLabAgent\myLabAgent\core\skill_loader.py)

当前 skill 仍然是“可复用说明包”，不是插件系统。

约定目录：

`myLabAgent/.agent_skills/skills/<skill_name>/SKILL.md`

当前行为：

1. 创建 Agent 时，先扫描 `SKILL.md`
2. 只把 `name` 和 `description` 暴露给模型
3. 模型明确调用 `load_skill(name)` 后，才把完整 skill 正文注入上下文

这部分仍然是共享 runtime，不应该写死在 Web 或 CLI 里。

## 5. Web 端

### 5.1 Web 入口文件

Web 相关核心文件：

- [app.py](D:\tongjiLabAgent\myLabAgent\app.py)
- [core/runtime.py](D:\tongjiLabAgent\myLabAgent\core\runtime.py)
- [ui_tabs/sidebar.py](D:\tongjiLabAgent\myLabAgent\ui_tabs\sidebar.py)
- [ui_tabs/chat_tab.py](D:\tongjiLabAgent\myLabAgent\ui_tabs\chat_tab.py)
- [services/chat_service.py](D:\tongjiLabAgent\myLabAgent\services\chat_service.py)

### 5.2 Web 的职责

Web 层只负责：

1. 设置页面和样式
2. 初始化 `st.session_state`
3. 读取侧边栏输入
4. 调用共享 runtime 创建 `agent`
5. 在聊天区域消费 `agent.chat(...)` 事件流
6. 把中间状态展示成 `st.status(...)` 和聊天消息

### 5.3 Web 特有状态

- [runtime.py](D:\tongjiLabAgent\myLabAgent\core\runtime.py)

这个文件是 `Web only`。它的职责是初始化和维护 `st.session_state`，包括：

1. `messages`
2. `agent`
3. `rag_engine`
4. `session_id`
5. `task_id`
6. `pending_chat_image_path`
7. 若干 UI 选择状态

这里不应该放 CLI 逻辑，也不应该放共享 runtime 的核心规则。

### 5.4 Web 侧服务适配层

- [chat_service.py](D:\tongjiLabAgent\myLabAgent\services\chat_service.py)

这个文件当前是 `Web adapter`，不是共享 runtime 核心。

它现在做两件事：

1. 调用 `build_agent_runtime(...)` 创建 Web 所需 Agent
2. 用 `st.session_state` 创建 task 并记录 `task_id`

后续如果 Web 有更多特有逻辑，继续放这里或拆到 `services/web_*` 文件里，不要回写到 `agent_factory.py`。

### 5.5 Web 链路

当前 Web 主链路是：

`Streamlit UI -> st.session_state -> build_agent_runtime -> LabAgent.chat -> tool/RAG/skill -> session_store -> UI 展示`

### 5.6 Web 维护建议

如果以后改的是这些内容，优先改 Web 层：

1. 页面布局
2. 侧边栏配置表单
3. Tab 结构
4. 聊天展示方式
5. 图片上传与前端预览

如果以后改的是这些内容，不要只改 Web，要同步考虑 CLI：

1. Agent 事件类型
2. Tool 行为
3. Session 数据结构
4. Permission 模型
5. Prompt 装配逻辑

## 6. CLI 端

### 6.1 CLI 入口文件

CLI 相关核心文件：

- [cli.py](D:\tongjiLabAgent\myLabAgent\cli.py)
- [cli_repl.py](D:\tongjiLabAgent\myLabAgent\cli_repl.py)
- [cli_render.py](D:\tongjiLabAgent\myLabAgent\cli_render.py)
- [services/agent_factory.py](D:\tongjiLabAgent\myLabAgent\services\agent_factory.py)
- [services/session_service.py](D:\tongjiLabAgent\myLabAgent\services\session_service.py)

### 6.2 CLI 的职责

CLI 层只负责：

1. 解析命令行参数
2. 读取 env / `vip_config.json`
3. 初始化共享 runtime
4. 进入 REPL 或执行单轮 ask
5. 用 `rich` 渲染事件流
6. 把消息和 task 写入 session

### 6.3 当前 CLI 命令

- `python cli.py chat`
- `python cli.py ask "..."`
- `python cli.py resume <session_id>`
- `python cli.py session-list`

### 6.4 当前 CLI REPL 内置命令

- `/help`
- `/session`
- `/models`
- `/exit`

其中 `/models` 会：

1. 从当前 profile 的 `vip_config.json` 里读取 `llm_models`
2. 在终端弹出单选列表
3. 用方向键移动
4. 用空格选中
5. 用回车确认
6. 重新构造当前 agent，并切换后续对话所使用的模型

### 6.5 CLI 参数配置来源

当前 CLI 的配置优先级大致是：

1. CLI 参数
2. 环境变量
3. `vip_config.json`
4. 代码内置默认值

主要配置项包括：

1. `--model`
2. `--base-url`
3. `--api-key`
4. `--embedding-model`
5. `--embedding-base-url`
6. `--embedding-api-key`
7. `--profile`
8. `--sandbox`
9. `--reasoning`
10. `--max-tool-rounds`

### 6.6 CLI 渲染层

- [cli_render.py](D:\tongjiLabAgent\myLabAgent\cli_render.py)

当前使用 `rich` 渲染：

1. banner
2. 帮助信息
3. 工具调用输入
4. 工具结果
5. 最终回答
6. session 列表
7. `/models` 模型选择器

如果以后只是要改终端展示样式，优先改这里，不要碰 `LabAgent.chat(...)`。

### 6.7 CLI REPL 层

- [cli_repl.py](D:\tongjiLabAgent\myLabAgent\cli_repl.py)

当前职责：

1. 读取用户输入
2. 处理 `/exit`、`/help`、`/session`、`/models`
3. 追加 user message
4. 创建 task
5. 调用 `agent.chat(...)`
6. 消费事件并落盘 assistant message

如果以后要加 CLI 特有命令，比如：

1. `/sandbox`
2. `/history`
3. `/tools`

应该优先改这个文件。

### 6.8 CLI 链路

当前 CLI 主链路是：

`argparse -> config resolve -> build_agent_runtime -> CliRepl -> LabAgent.chat -> tool/RAG/skill -> session_store -> rich render`

### 6.9 CLI 维护建议

如果以后改的是这些内容，优先改 CLI 层：

1. 命令结构
2. shell 友好参数
3. REPL 命令
4. Rich 样式
5. 会话恢复显示
6. 模型选择交互

如果未来要往 `Claude Code / OpenCode` 方向继续演进，CLI 层最优先新增的是：

1. 文件读取工具
2. 目录浏览工具
3. 文本搜索工具
4. 文件写入工具
5. shell 执行工具
6. 更细粒度的 sandbox

## 7. 当前两个入口的分工边界

可以用下面这张表快速判断“改动应该放哪里”。

| 变化内容 | 应该优先修改的位置 |
| --- | --- |
| Streamlit 页面布局 | Web |
| 侧边栏模型选择 | Web |
| Rich 输出样式 | CLI |
| REPL 命令 | CLI |
| `/models` 交互选择器 | CLI |
| Agent 创建方式 | Shared Runtime |
| Prompt 加载 | Shared Runtime |
| Tool 注册和权限 | Shared Runtime |
| Session JSON 结构 | Shared Runtime |
| RAG 检索逻辑 | Shared Runtime |
| Tool-calling 主循环 | Shared Runtime |

## 8. 推荐的后续演进顺序

为了长期维护更稳，建议按这个顺序继续演进：

1. 先稳定共享 runtime
   - 统一事件类型
   - 统一 session 数据结构
   - 统一权限模式
2. 再补 CLI 能力
   - `read_file`
   - `list_dir`
   - `search_text`
   - `write_file`
   - `run_shell`
3. 再考虑更强的交互层
   - Web 增强
   - CLI 命令增强
   - 未来如果需要再做 TUI

## 9. 运行方式

### 9.1 Web

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### 9.2 CLI

```bash
python -m pip install -r requirements.txt
python cli.py --help
python cli.py chat
python cli.py ask "解释当前项目结构"
python cli.py session-list
```

进入 CLI 交互后，可以输入：

```text
/models
```

来切换当前会话使用的模型。

## 10. 最重要的维护结论

现在这个项目已经不是“只有一个 Streamlit 页面”的结构，而是：

- 一套共享 Agent runtime
- 一个 Web client
- 一个 CLI client

以后长期维护时，尽量把新增能力先判断清楚属于哪一层：

- 属于交互体验，就放 Web 或 CLI
- 属于 Agent 能力，就放 Shared Runtime
- 属于落盘与知识库，就放 Persistence 或 Knowledge 层

这样后面不管你继续做 Web、CLI 还是更进一步做 TUI，都不会反复拆旧代码。

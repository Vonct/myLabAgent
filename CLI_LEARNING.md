# CLI Learning Guide

这份文档专门帮助理解 `myLabAgent` 当前的 CLI 代码结构。它关注的是：

1. CLI 是怎么启动的
2. 用户输入后消息如何流动
3. `CliRenderer`、`CliRepl`、`agent_core`、`session_store` 分别负责什么
4. 以后如果继续改 CLI，应该从哪里下手

## 1. 总体结构

CLI 主链路由这几个文件组成：

- `cli.py`
- `cli_repl.py`
- `cli_render.py`
- `services/agent_factory.py`
- `services/session_service.py`
- `core/session_store.py`
- `agent_core.py`

可以把它理解成四层：

1. 命令入口层
   - `cli.py`
2. 交互控制层
   - `cli_repl.py`
3. 渲染层
   - `cli_render.py`
4. 共享 runtime 层
   - `agent_core.py`
   - `services/agent_factory.py`
   - `services/session_service.py`
   - `core/session_store.py`

## 2. 启动入口

### 2.1 `cli.py`

`cli.py` 是 CLI 的主入口，负责：

- 解析命令行参数
- 加载 VIP 配置和模型配置
- 构建 agent runtime
- 决定是进入 `chat`、`ask`、`resume` 还是 `session-list`

最关键的函数有：

- `build_parser()`
- `_resolve_runtime_config(...)`
- `_build_agent_from_config(...)`
- `_run_chat(...)`
- `_run_ask(...)`

### 2.2 两种主要运行方式

CLI 现在主要支持两条主路径：

1. `chat`
   - 进入 REPL 多轮交互
   - 由 `CliRepl.run()` 驱动

2. `ask`
   - 单轮提问
   - 在 `cli.py` 里直接跑一轮 `agent.chat(...)`

## 3. 交互控制层

### 3.1 `CliRepl`

`cli_repl.py` 里的 `CliRepl` 负责管理多轮会话流程。

它的职责不是做模型推理，而是：

- 读取用户输入
- 处理本地命令，如 `/help`、`/models`、`/skills`
- 把普通提问交给共享 runtime
- 在一轮结束后把结果写回 session/task/memory

`CliRepl.run()` 是 REPL 的主循环。

每轮普通提问的大致过程是：

1. `renderer.print_user(...)`
2. `session_service.append_user_message(...)`
3. `session_store.start_task(...)`
4. `renderer.begin_turn(...)`
5. 调用 `agent.chat(...)`
6. 每收到一个 event，就交给 `renderer.render_event(...)`
7. 收集最终 assistant 文本
8. `session_store.finish_task(...)`
9. `session_service.append_memory_card(...)`
10. `renderer.finish_turn(...)`

## 4. 渲染层

### 4.1 `CliRenderer`

`cli_render.py` 负责终端展示，不负责业务逻辑。

当前版本基于 `rich`，已经从原来的顺序打印升级为“每轮一个轻量 Live 面板布局”。

当前渲染区域包括：

- `Status`
  - session
  - model
  - task
  - status
  - tool count
  - active tool
  - memory 是否已保存
  - elapsed time
- `Current Turn`
  - 当前 prompt 摘要
  - 当前 thought
- `Assistant`
  - 当前流式回答
- `Recent Activity`
  - 最近的工具调用、工具结果、错误等
- `Reasoning`
  - 当前 reasoning 摘要
- `Shortcuts`
  - 常用命令提示

### 4.2 渲染器的重要方法

- `set_session_context(...)`
  - 设置 session / model / mode 等静态上下文

- `begin_turn(...)`
  - 开始一轮渲染
  - 重置当前 turn 的状态
  - 启动 `rich.Live`

- `render_event(...)`
  - 把 runtime 产出的 event 更新到 CLI 面板

- `finish_turn(...)`
  - 结束当前 turn
  - 更新最终状态
  - 停止 `Live`

### 4.3 为什么这样拆

这样拆的好处是：

- `CliRepl` 只关心流程
- `CliRenderer` 只关心显示
- `agent_core` 只关心运行时和事件产生

这能避免把终端渲染逻辑写进 agent 主循环里。

## 5. 共享 runtime 层

### 5.1 `services/agent_factory.py`

这个文件负责构建共享 agent runtime。

它会创建：

- `RAGEngine`
- `PermissionManager`
- `ToolRegistry`
- `SkillLoader`
- `LabAgent`

也就是说，CLI 和 Web 都复用同一个 runtime 工厂。

### 5.2 `agent_core.py`

`agent_core.py` 是共享运行时的核心。

这里的 `LabAgent.chat(...)` 会：

1. 组装消息
2. 发起 `Responses API` 请求
3. 如果模型要求调用工具，则执行工具
4. 把工具结果回填为 `function_call_output`
5. 继续当前轮闭环
6. 以事件流的方式返回给 CLI 或 Web

CLI 看到的事件包括：

- `thought`
- `reasoning`
- `tool_exec`
- `tool_result`
- `answer_chunk`
- `final_message`
- `error`

CLI 并不直接操作模型返回对象，而是消费这些事件。

## 6. Session / Task / Memory

### 6.1 `services/session_service.py`

这是 CLI 和 Web 共同使用的高层 session 服务。

负责：

- 生产 canonical message
- 追加 user/assistant 消息
- 读取消息历史
- 追加 memory card

这里的 canonical transcript 指的是外层 `user / assistant` 会话历史，不包含工具结果。

### 6.2 `core/session_store.py`

这是底层 JSON 持久化层。

负责：

- 创建 session
- 记录消息
- 记录 task
- 记录 tool events
- 记录 memory

注意这里持久化的是 canonical transcript，而不是终端或 Streamlit 的展示态字段。
工具执行轨迹则进入 `tasks[*].tool_events`，只在当前一轮 `agent.chat(...)` 内部通过协议继续传递。

### 6.3 当前一轮结束后会写什么

当前一轮结束后，CLI 会写入三类信息：

1. assistant message
2. task result
3. memory card

memory card 里主要包括：

- `task_id`
- `status`
- `prompt`
- `answer`
- `has_image`
- `tool_names`
- `summary`

这说明当前 CLI 不只是“显示结果”，还在参与长期上下文积累。

## 7. 事件流怎么理解

你可以把 CLI 的工作方式理解成：

1. runtime 产生事件
2. CLI 逐个消费事件
3. 渲染器把事件映射到终端 UI

也就是说，CLI 的核心协议不是“最终文本”，而是“逐步事件”。

这是当前 CLI 代码最值得理解的一点，因为后续：

- 更复杂的状态面板
- task 监控
- subagent 展示
- memory 提示

都可以继续建立在这套事件流上。

## 8. 当前 CLI 的优势

当前这套 CLI 架构有几个明显优点：

- 基于 `rich`，成本低，和 Python runtime 无缝衔接
- 与共享 runtime 解耦，Web 和 CLI 不重复造轮子
- 已经具备 Live 状态面板，不再只是顺序打印
- task / tool / memory 信息都已经接上

## 9. 后续适合怎么演进

如果继续增强 CLI，我建议优先顺序是：

1. 增强 `CliRenderer`
   - 更多 task / subagent / memory 提示

2. 补更多 REPL 命令
   - 例如 `/tasks`、`/memories`、`/tools`

3. 增加 task 视图
   - 让用户能回看本 session 最近任务

4. 如果复杂度继续上升，再评估是否迁移到更完整的 TUI 框架
   - 当前阶段 `rich` 仍然是合理选择

## 10. 一句话记忆

如果只记一句话，可以记这个：

`cli.py` 决定怎么启动，`cli_repl.py` 决定怎么跑一轮，`cli_render.py` 决定怎么显示，`agent_core.py` 决定怎么和模型及工具闭环。`

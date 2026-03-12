# myLabAgent 技术交互说明

这份文档从整体架构、运行链路、工具系统和新增的 skill 机制四个角度说明 `myLabAgent` 当前是怎么工作的。

## 1. 项目一句话说明

`myLabAgent` 是一个基于 `Streamlit + OpenAI SDK 兼容接口` 的实验室 Agent Demo。

它当前主要包含三类能力：

1. 聊天问答：支持多轮对话、RAG 检索增强、工具调用。
2. 项目介绍展示：读取持久化的项目目录数据并展示详情。
3. License 看板：集中展示软件 License 信息和到期状态。

## 2. 整体架构

可以把项目拆成 5 层：

1. UI 层
   - `app.py`
   - `ui_tabs/`
   - 负责 Streamlit 页面、侧边栏、Tab 和聊天展示。
2. 运行时状态层
   - `core/runtime.py`
   - 负责初始化 `st.session_state`。
3. Agent 层
   - `services/chat_service.py`
   - `agent_core.py`
   - 负责构建 Agent、加载 prompt、发起模型请求、处理 tool call 闭环。
4. 知识与工具层
   - `rag_engine.py`
   - `core/tool_registry.py`
   - `core/permissions.py`
   - `core/skill_loader.py`
   - `config/tools.json`
5. 持久化层
   - `core/session_store.py`
   - `project_catalog/`
   - `license_catalog/`
   - `chroma_db/` 或 `vector_store.json`

整体主链路可以概括为：

`Streamlit UI -> Session State -> Agent -> Tool/RAG/Skill -> 回写消息和任务记录 -> UI 展示`

## 3. 程序入口

### 3.1 `app.py`

`app.py` 主要负责：

1. 定义项目根目录、上传目录、catalog 目录、session store 等常量。
2. 设置 Streamlit 页面配置和全局样式。
3. 调用 `init_session_state(...)` 初始化运行时状态。
4. 渲染侧边栏。
5. 渲染三个主 Tab：
   - `Projects`
   - `Licenses`
   - `LabAgent`

它本身不承担复杂 Agent 逻辑，主要负责装配应用。

## 4. 侧边栏如何把配置变成 Agent

### 4.1 `ui_tabs/sidebar.py`

侧边栏负责采集运行参数，例如：

1. API Key / VIP 登录状态
2. LLM 模型和 Embedding 模型
3. 是否允许图片输入、是否支持 thinking
4. PDF 上传和知识库处理

用户点击“应用配置”后，才会真正调用 `build_agent(...)` 创建：

1. `RAGEngine`
2. `PermissionManager`
3. `ToolRegistry`
4. `SkillLoader`
5. `LabAgent`

## 5. 运行时状态

### 5.1 `core/runtime.py`

主要依赖 `st.session_state` 保存前端运行时对象和会话信息，包括：

1. `messages`
2. `rag_engine`
3. `agent`
4. `session_id`
5. `task_id`
6. `pending_chat_image_path`
7. `reasoning_mode`
8. 若干 UI 选择状态

这个项目的“前端状态管理”本质上就是 Streamlit 的 session state。

## 6. Agent 是怎么创建的

### 6.1 `services/chat_service.py`

`build_agent(...)` 当前做了这些事：

1. 创建 `RAGEngine`
2. 创建 `PermissionManager`
3. 创建 `ToolRegistry`
4. 创建 `SkillLoader`
   - 扫描 `myLabAgent/.agent_skills/skills/*/SKILL.md`
   - 只提取每个 skill 的 `name` 和 `description`
5. 加载系统提示词 `prompts/lab_agent.md`
6. 实例化 `LabAgent`

当前允许的权限等级是：

1. `READ_ONLY`
2. `NETWORK`
3. `EXEC`

## 7. Agent 主逻辑

### 7.1 `agent_core.py`

`LabAgent` 是项目的核心。

初始化阶段主要做这些事：

1. 创建 OpenAI 客户端
2. 保存当前模型名称
3. 创建天气适配器 `AMapMCPAdapter`
4. 注入系统提示词
5. 向 `ToolRegistry` 注册工具：
   - `retrieve_document`
   - `recognize_handwritten_digit`
   - `get_amap_weather`
   - `load_skill`
6. 生成 OpenAI 兼容 tools schema

### 7.2 一次聊天请求的完整流程

`LabAgent.chat(...)` 的流程是：

1. 组装 `system prompt + history messages`
2. 第一次调用 `client.chat.completions.create(...)`
3. 如果模型返回 `tool_calls`
   - 逐个执行工具
   - 把工具结果包装成 `role="tool"` 消息
   - 再发起第二次模型调用
4. 如果模型没有调用工具
   - 直接输出答案
5. 把回答按 `answer_chunk` 分段 `yield` 给前端

这就是一个有上限的多轮 ReAct / tool-calling 闭环。当前默认最多执行 4 轮工具调用。

### 7.3 前端为什么能显示 thought / tool / result

因为 `chat(...)` 返回的是一个生成器，会逐步吐出：

1. `thought`
2. `reasoning`
3. `tool_exec`
4. `tool_result`
5. `answer_chunk`
6. `error`

`ui_tabs/chat_tab.py` 根据这些事件更新 `st.status(...)` 和聊天消息区。

## 8. RAG 引擎

### 8.1 `rag_engine.py`

这个模块负责把 PDF 处理成可检索知识库：

1. 用 `pypdf` 读取 PDF
2. 抽取文本并切块
3. 调用 embedding 接口生成向量
4. 写入 Chroma 或本地 `vector_store.json`

### 8.2 检索时做什么

`retrieve(...)` 会：

1. 在 Chroma 中查询，或
2. 在内存向量中手动做相似度计算

然后把最相关的文档片段返回给 `retrieve_document` 工具。

## 9. 工具系统

工具相关文件：

1. `config/tools.json`
2. `core/tool_registry.py`
3. `core/permissions.py`
4. `core/skill_loader.py`
5. `agent_core.py`

### 9.1 `config/tools.json`

负责定义工具的外部接口：

1. 工具名
2. 工具说明
3. 参数 schema

这份配置主要是给模型看的。

### 9.2 `core/tool_registry.py`

负责：

1. 读取 `tools.json`
2. 注册本地 Python 执行函数
3. 生成 OpenAI 兼容 tool schema
4. 在执行前做权限检查
5. 支持对某些工具描述做运行时覆盖

当前 `load_skill` 的描述就是运行时动态生成的，不是静态写死在 JSON 里。

### 9.3 `core/permissions.py`

这是一个轻量权限白名单：

1. `READ_ONLY`
2. `NETWORK`
3. `FILE_WRITE`
4. `EXEC`

工具执行前会先检查该工具对应的权限等级是否被当前运行策略允许。

## 10. 新增的 Skill 机制

### 10.1 skill 放在哪里

当前约定 skill 目录为：

`myLabAgent/.agent_skills/skills/<skill_name>/SKILL.md`

目前每个 skill 至少要有一个 `SKILL.md`。

### 10.2 `core/skill_loader.py` 做什么

`SkillLoader` 是一个非常轻量的 skill 发现器，不是插件系统。

它只做三件事：

1. 扫描 `.agent_skills/skills/*/SKILL.md`
2. 解析 frontmatter 中的 `name` 和 `description`
3. 在真正调用时返回完整 `SKILL.md` 正文

### 10.3 skill 是怎么暴露给模型的

这里采用的是“metadata 先暴露，正文按需加载”的最小模式。

具体来说：

1. 创建 Agent 时，`SkillLoader` 扫描所有 skills。
2. `load_skill` 工具的 description 会被动态改写。
3. 改写后的 description 里包含一个 `<available_skills>` 列表，只放：
   - `name`
   - `description`
   - `location`
4. 模型先根据这些 metadata 判断有没有匹配 skill。
5. 只有当模型明确调用 `load_skill(name)` 时，后端才把完整 skill 内容放进上下文。

这个设计避免了把所有 skill 全文一开始就塞进 system prompt，减少上下文浪费。

### 10.4 `load_skill` 工具返回什么

`load_skill(name)` 返回的是一个文本块，包含：

1. `<skill_content name="...">`
2. 完整 `SKILL.md` 正文
3. skill base directory
4. 少量文件列表 `<skill_files>`

这样模型在读完 skill 之后，知道：

1. skill 说了什么
2. skill 的相对路径应该相对于哪个目录解释
3. 目录里大概还有哪些文件可以继续参考

### 10.5 scripts / reference / assets 会不会自动执行

不会。

当前实现里，skill 的职责只是：

1. 提供可复用说明
2. 提供资源入口
3. 帮模型决定下一步该做什么

即使某个 skill 目录下存在：

1. `scripts/`
2. `reference/`
3. `assets/`

它们也不会因为 `load_skill` 被调用就自动执行。

当前行为是：

1. skill 被加载时，只返回 `SKILL.md` 和文件列表
2. 如果后续模型想使用这些资源，仍然必须继续走正常工具链
3. 真正执行动作的仍然是普通 tool，而不是 skill 本身

所以在本项目里：

`skill = 可复用说明包`
`tool = 真正执行动作`

### 10.6 为什么采用这个最小方案

因为它有几个优点：

1. 侵入性小，不需要改动现有 tool-calling 主链路
2. 不需要设计复杂插件协议
3. 不需要给 skill 单独设计执行沙箱
4. 后续如果你想把某些高价值 skill 再升级成专门工具，也不冲突

## 11. 从输入到回答的完整链路

### 11.1 用户发送消息时

在 `ui_tabs/chat_tab.py` 中：

1. `st.chat_input(...)` 接收输入
2. `start_task(...)` 创建任务记录
3. 组装 `user_message`
4. 写入 `st.session_state.messages`
5. 同步写入 `session_store`

如果携带图片：

1. 先保存到 `uploads/chat_images/`
2. 转成 `data URL`
3. 作为多模态内容发给模型

### 11.2 Agent 第一次请求模型

内部会构造：

```python
full_messages = [{"role": "system", "content": self.system_prompt}] + messages
```

然后带着 `tools=self.tools` 发给模型。

### 11.3 如果模型决定用工具

可能有两类情况：

1. 直接调用业务工具
   - `retrieve_document`
   - `recognize_handwritten_digit`
   - `get_amap_weather`
2. 先调用 `load_skill`
   - 先把 skill 正文加载进上下文
   - 再根据 skill 指引决定后续是否继续调用其他工具

### 11.4 工具执行后

后端会：

1. 执行工具函数
2. 记录 tool event
3. 将结果作为 `role="tool"` 消息拼回上下文
4. 如果模型还在请求工具，就继续下一轮；否则生成最终答案

### 11.5 前端展示时

前端会：

1. 显示中间状态
2. 流式拼接最终答案
3. 将结果写入 assistant 消息
4. 完成任务记录

## 12. 会话与任务持久化

### 12.1 `core/session_store.py`

落盘目录：

`app_data/sessions/<session_id>.json`

每个 session 文件大致包含：

1. `session_id`
2. `created_at`
3. `updated_at`
4. `messages`
5. `tasks`

每个 task 包含：

1. `task_id`
2. `prompt`
3. `status`
4. `tool_events`
5. `result`

## 13. 非聊天页面的数据来源

### 13.1 Projects Tab

数据来自：

1. `project_catalog/index.json`
2. `project_catalog/projects/*.json`
3. 对应 Markdown 和媒体资源

### 13.2 Licenses Tab

数据来自：

1. `license_catalog/index.json`
2. `license_catalog/licenses/*.json`
3. 对应 logo 等静态资源

## 14. 当前最值得注意的设计点

### 14.1 Agent 与 UI 分层还算清楚

聊天页不直接做模型调用，真正的 Agent 逻辑在 `agent_core.py`。

### 14.2 工具系统依然是最适合扩展的地方

新增工具通常只要补三件事：

1. `config/tools.json`
2. 本地执行函数
3. 注册代码

新增的 `load_skill` 也是沿用这条路径加进去的。

### 14.3 skill 机制故意做得很轻

它不是插件执行框架，而是“可按需注入上下文的说明包”。

这样可以先把 skill 机制引入进来，而不会把项目复杂度一下抬高。

## 15. 一句话总结

`myLabAgent` 现在是一个以聊天 Agent 为核心、带 RAG、工具调用、轻量 skill 加载、项目展示和 License 展示的 Streamlit 应用。

新增 skill 之后，系统多了一层“先发现可复用 workflow，再按需加载说明”的能力，但真正的执行动作仍然由原有工具系统完成。


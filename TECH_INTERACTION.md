# myLabAgent 技术文档

这份文档不再只讲 `chat tab`，而是从“整个项目怎么组成、模块怎么协作、数据怎么流转”的角度整理，方便你自己学习这个项目。

## 1. 项目一句话说明

`myLabAgent` 是一个基于 `Streamlit + OpenAI SDK 兼容接口` 的实验室 Agent Demo。

它现在主要做三件事：

1. 聊天问答：支持普通多轮对话、RAG 检索增强、工具调用。
2. 项目介绍展示：把实验室项目资料做成可浏览的卡片和详情页。
3. License 看板：集中展示软件 License 信息和到期状态。

从代码组织看，它不是“单纯聊天页面”，而是一个带多个业务 Tab 的小型应用。

## 2. 整体架构

可以把项目分成 5 层：

1. UI 层
   - `app.py`
   - `ui_tabs/`
   - 负责页面布局、Tab 切换、侧边栏配置、交互控件
2. 运行时状态层
   - `core/runtime.py`
   - 负责初始化 `st.session_state`
3. Agent 层
   - `agent_core.py`
   - `services/chat_service.py`
   - 负责构建 Agent、拼装 prompt、发起 LLM 请求、执行工具
4. 知识与工具层
   - `rag_engine.py`
   - `core/tool_registry.py`
   - `core/permissions.py`
   - `config/tools.json`
5. 数据持久化层
   - `core/session_store.py`
   - `project_catalog/`
   - `license_catalog/`
   - `chroma_db/` 或 `vector_store.json`

如果用一句话概括调用链：

`Streamlit UI -> Session State -> Agent -> Tool/RAG -> 回写消息和任务记录 -> UI 展示`

## 3. 目录怎么读

建议先按下面顺序读：

1. `app.py`
   - 看项目入口、页面有哪些 Tab、全局常量在哪里定义
2. `ui_tabs/sidebar.py`
   - 看模型配置、VIP 登录、PDF 上传、知识库清空这些控制入口
3. `ui_tabs/chat_tab.py`
   - 看消息发送、图片附件、Agent 响应展示
4. `services/chat_service.py`
   - 看 Agent 是怎么被创建出来的
5. `agent_core.py`
   - 看真正的 LLM 调用、tool call 闭环、回答流式输出
6. `rag_engine.py`
   - 看 PDF 解析、切块、向量化、检索
7. `core/session_store.py`
   - 看会话和任务怎么落盘
8. `ui_tabs/projects_tab.py` 和 `ui_tabs/licenses_tab.py`
   - 看另外两个业务页面的数据读取与展示方式

## 4. 程序入口：`app.py`

`app.py` 做了几件核心事情：

1. 定义项目级路径
   - `PROJECT_ROOT`
   - `PROJECT_CATALOG_DIR`
   - `LICENSE_CATALOG_DIR`
   - `CHAT_UPLOAD_DIR`
   - `SESSION_STORE`
2. 定义模型与能力映射
   - 哪些 LLM 可选
   - 哪些 embedding 模型可选
   - 某个模型是否支持图片输入、是否支持 thinking
3. 初始化 Streamlit 页面
   - 页面标题
   - 全局 CSS
4. 调用 `init_session_state(...)`
   - 初始化会话状态
5. 渲染侧边栏和三个主 Tab
   - `projects`
   - `licenses`
   - `chat`

也就是说，`app.py` 只负责“装配应用”，不承担复杂业务逻辑。

## 5. 三个主 Tab 分别负责什么

### 5.1 Chat Tab

文件：`ui_tabs/chat_tab.py`

这是 Agent 主交互区，负责：

1. 展示历史消息
2. 接收用户输入
3. 可选上传图片附件
4. 控制是否开启深度思考模式
5. 调用 `st.session_state.agent.chat(...)`
6. 实时展示 thought / reasoning / tool result / final answer
7. 把消息和任务记录写入 session store

这是项目里“动态行为最多”的页面。

### 5.2 Projects Tab

文件：`ui_tabs/projects_tab.py`

它不是实时解析 PPT，而是读取已经持久化好的项目目录数据：

1. 从 `project_catalog/index.json` 读取项目索引
2. 再去 `project_catalog/projects/<id>.json` 读取详情
3. 如果存在同名 Markdown，就优先展示 Markdown
4. 如果没有 Markdown，就回退到 JSON 中的结构化字段

所以这个 Tab 更像一个“静态内容浏览器”。

### 5.3 Licenses Tab

文件：`ui_tabs/licenses_tab.py`

它负责：

1. 从 `license_catalog/index.json` 读取软件索引
2. 加载每个软件的 License 详情 JSON
3. 根据到期日期计算状态
   - 可用
   - 即将到期
   - 不可用
4. 用卡片方式展示

这个 Tab 的逻辑比较独立，和 Agent 聊天主链路耦合不高。

## 6. 侧边栏是整个应用的控制中心

文件：`ui_tabs/sidebar.py`

它负责把“运行配置”装进当前 Streamlit 会话中。

主要功能：

1. 认证模式切换
   - 手动输入 API Key
   - VIP 登录
2. 模型选择
   - LLM 模型
   - Embedding 模型
3. 应用配置
   - 点击后真正构建 `rag_engine` 和 `agent`
4. 文档上传
   - 上传 PDF
   - 调用 `rag_engine.process_file(...)`
5. 统计信息
   - Embedding token 用量
   - 当前 session id
   - 最近 task id
6. 清空知识库

重点理解一点：

侧边栏里填完参数，并不会自动生效；必须点击“应用配置”，才会调用 `build_agent(...)` 初始化运行时对象。

## 7. 运行时状态：`st.session_state` 存了什么

文件：`core/runtime.py`

这个文件负责初始化应用运行过程中最关键的状态。

当前默认字段包括：

1. `messages`
   - 当前页面会话中的聊天消息列表
2. `rag_engine`
   - 当前使用的 RAG 引擎实例
3. `agent`
   - 当前使用的 LabAgent 实例
4. `session_id`
   - 当前页面运行时对应的持久化会话 ID
5. `task_id`
   - 最近一次发送消息对应的任务 ID
6. `selected_project_id`
   - Projects Tab 当前选中的项目
7. `pending_chat_image_path`
   - 待发送图片路径
8. `reasoning_mode`
   - 是否开启深度思考
9. `vip_authenticated` / `vip_profile`
   - VIP 登录相关状态

理解这个文件后，你会明白：

这个项目的大部分“前端状态管理”并不是 React 式 store，而是直接依赖 `Streamlit session_state`。

## 8. Agent 是怎么创建出来的

文件：`services/chat_service.py`

`build_agent(...)` 做了 4 件事：

1. 创建 `RAGEngine`
2. 创建 `PermissionManager`
3. 创建 `ToolRegistry`
4. 读取系统提示词并实例化 `LabAgent`

这里也定义了当前运行时允许的权限集合：

1. `READ_ONLY`
2. `NETWORK`
3. `EXEC`

所以当前版本里，手写数字识别工具是允许执行本地推理脚本的。

## 9. Agent 主逻辑：`agent_core.py`

`LabAgent` 是项目的核心。

### 9.1 初始化阶段

构造函数中做了这些事：

1. 创建 OpenAI 客户端
2. 保存当前 LLM 模型名
3. 创建高德天气适配器 `AMapMCPAdapter`
4. 注入系统提示词
5. 向 `tool_registry` 注册工具
   - `retrieve_document`
   - `recognize_handwritten_digit`
   - `get_amap_weather`
6. 生成 OpenAI tools schema

### 9.2 一次聊天请求的真实流程

`LabAgent.chat(...)` 的流程可以概括为：

1. 把 `system prompt` 和历史 `messages` 拼成 `full_messages`
2. 第一次调用 `client.chat.completions.create(...)`
3. 如果模型返回 `tool_calls`
   - 逐个执行工具
   - 把工具结果作为 `role="tool"` 追加回消息列表
   - 再发起第二次模型调用
4. 如果没有工具调用
   - 直接输出回答
5. 把回答按 chunk 切片，逐步 `yield` 给前端

也就是说，这里实现的是一个简化版 ReAct / tool-calling 闭环。

### 9.3 为什么前端能看到“思考中 / 工具调用 / 工具结果”

因为 `chat(...)` 不是直接返回字符串，而是返回一个生成器，分多种事件类型吐给 UI：

1. `thought`
2. `reasoning`
3. `tool_exec`
4. `tool_result`
5. `answer_chunk`
6. `error`

`ui_tabs/chat_tab.py` 再根据这些事件更新 `st.status(...)` 和聊天消息区域。

## 10. RAG 引擎：`rag_engine.py`

这个文件负责“把 PDF 变成可检索知识库”。

### 10.1 文档处理流程

`process_file(...)` 的步骤是：

1. 用 `pypdf.PdfReader` 读取 PDF
2. 提取每页文本并拼接
3. 按固定窗口切块
   - `chunk_size = 1000`
   - `overlap = 100`
4. 调用 embedding 接口生成向量
5. 写入向量库
   - 优先 `Chroma`
   - 回退到本地 `vector_store.json`

### 10.2 检索流程

`retrieve(...)` 会根据当前后端分两种方式：

1. `chroma`
   - 直接调用 collection query
2. `memory`
   - 手动计算余弦相似度

### 10.3 这个类还顺手做了什么

1. 记录 embedding token 使用量
2. 提供 `clear_db()` 清空知识库
3. 提供 `get_embedding_usage()` 给侧边栏展示统计

## 11. 工具系统

工具相关文件：

1. `config/tools.json`
2. `core/tool_registry.py`
3. `core/permissions.py`
4. `agent_core.py`

它们的职责分工很清楚：

### 11.1 `config/tools.json`

定义工具的外部描述：

1. 工具名
2. 工具说明
3. 参数 schema

这份文件主要是给 LLM 看的。

### 11.2 `core/tool_registry.py`

负责：

1. 从 JSON 读取工具定义
2. 注册工具执行函数
3. 生成 OpenAI 兼容 tool schema
4. 执行工具前先过权限检查

### 11.3 `core/permissions.py`

这里的权限系统很轻量，本质上只是一个运行时白名单：

1. `READ_ONLY`
2. `NETWORK`
3. `FILE_WRITE`
4. `EXEC`

如果工具权限不在允许集合里，就不会执行。

## 12. 聊天消息从输入到回答的完整链路

这一段是对原先 chat 文档的保留和扩展。

### 12.1 用户发送消息时

在 `ui_tabs/chat_tab.py` 中：

1. `st.chat_input(...)` 接收用户输入
2. `start_task(...)` 创建任务记录
3. 组装 `user_message`
4. 写入 `st.session_state.messages`
5. 同步写入 `session_store.append_message(...)`

如果附带图片：

1. 先把图片保存到 `uploads/chat_images/`
2. 再转成 `data URL`
3. 作为多模态 `content` 发送给模型

### 12.2 调用 Agent 时

前端把这些参数传入：

1. `messages`
2. `reasoning_mode`
3. `supports_thinking`
4. `session_store`
5. `session_id`
6. `task_id`

### 12.3 Agent 内部第一次请求

会把消息拼成：

```python
full_messages = [{"role": "system", "content": self.system_prompt}] + messages
```

然后发给模型，并允许自动选择工具：

```python
response = self.client.chat.completions.create(
    model=self.llm_model,
    messages=full_messages,
    tools=self.tools,
    tool_choice="auto",
    stream=False,
    **extra_params,
)
```

### 12.4 如果模型决定调工具

则会：

1. 读取 `tool_calls`
2. 执行对应工具
3. 把结果封装成 `role="tool"` 消息
4. 再次调用模型生成最终回答

### 12.5 回到前端后

前端会：

1. 把中间状态写到 `st.status(...)`
2. 把最终文本逐段展示
3. 成功时写入 assistant 消息
4. 调用 `finish_task(..., status="completed")`
5. 失败时写入 `failed`

## 13. 会话和任务是怎么持久化的

文件：`core/session_store.py`

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

### 13.1 session 的实际含义

当前代码里：

1. 一个 Streamlit 页面运行时会生成一个 `session_id`
2. 同一页面内的 rerun 会复用这个 `session_id`
3. 硬刷新、开新页、运行时重建，通常会产生新 `session_id`

所以可以近似理解为：

“一个页面运行周期，对应一个持久化 session 文件。”

## 14. 非聊天页面的数据来源

### 14.1 项目介绍数据

来自：

1. `project_catalog/index.json`
2. `project_catalog/projects/*.json`
3. `project_catalog/*.md`
4. `project_catalog/media/...`

这说明 `Projects Tab` 是“读已有资料”，不是现场解析源 PPT。

### 14.2 License 数据

来自：

1. `license_catalog/index.json`
2. `license_catalog/licenses/*.json`
3. 对应 logo 图片

## 15. 这个项目当前最值得注意的设计点

从学习角度，我建议你重点看这几个设计选择：

### 15.1 用 `Streamlit` 做多页面业务壳

优点是上手快、开发成本低，缺点是状态边界比较隐式，很多逻辑依赖 rerun 行为。

### 15.2 Agent 与 UI 分层还算清楚

`ui_tabs/chat_tab.py` 不直接做 LLM 细节，真正的模型调用放在 `agent_core.py`，这点是合理的。

### 15.3 工具系统是“配置 + 注册 + 权限”三段式

这是这个项目里比较适合继续扩展的地方。以后再加新工具，通常只要补：

1. `config/tools.json`
2. 执行函数
3. 注册代码

### 15.4 RAG 是简化版，但结构完整

已经具备：

1. 文档解析
2. 切块
3. embedding
4. 向量存储
5. 检索

所以它非常适合教学和继续迭代。

## 16. 建议你的阅读顺序

如果你的目标是“自己真正学会这个项目”，建议按下面顺序：

1. 先读 `app.py`
   - 理清程序入口和三个 Tab
2. 再读 `core/runtime.py`
   - 搞清楚状态存在什么地方
3. 再读 `ui_tabs/sidebar.py`
   - 理解配置如何变成运行时对象
4. 再读 `services/chat_service.py`
   - 理解 agent 初始化链路
5. 再读 `agent_core.py`
   - 理解聊天主闭环
6. 再读 `rag_engine.py`
   - 理解知识库处理
7. 最后读 `projects_tab.py` / `licenses_tab.py`
   - 理解另外两个业务页面

## 17. 一句话总结

`myLabAgent` 本质上是一个“以聊天 Agent 为核心，同时挂载项目展示与 License 展示两个辅助页面”的 Streamlit 应用。

如果你只盯着 `chat_tab`，你看到的是“问答链路”；
如果把整个项目连起来看，你看到的是“一个带状态管理、工具调用、RAG、内容展示和持久化的完整小应用”。

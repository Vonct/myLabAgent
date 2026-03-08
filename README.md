# DocAgent 演示项目：文档阅读与智能问答 Agent 框架

这是一个基于 OpenAI SDK + Qwen 兼容接口构建的教学级 Demo 项目，旨在演示一个现代 AI Agent 框架的核心工作流程，包括 RAG（检索增强生成）、Tool Use（工具调用）和多轮对话管理。

## 📁 目录说明

- `app.py`: 基于 Streamlit 的 Web 界面实现，负责 UI 渲染和对话状态管理。
- `agent_core.py`: **核心 Agent 逻辑**，实现了 ReAct 模式（思考 -> 行动 -> 观察 -> 再思考）。
- `rag_engine.py`: **RAG 引擎**，负责 PDF 解析、文本分块、Qwen Embedding 向量化与 Chroma 检索。
- `requirements.txt`: 项目所需的 Python 依赖包。
- `vip_config.example.json`: VIP 本地登录配置样例（复制为 `vip_config.json` 后生效）。

## 🚀 核心功能模块解析

### 1. 文档解析与向量化 (RAG Engine)
在 `rag_engine.py` 中，我们使用：
- `pypdf`: 将 PDF 物理内容转换为字符串。
- `OpenAI SDK + Qwen Embedding`: 将文本片段转换为高维向量。
- `ChromaDB`: 持久化存储向量索引，支持基于余弦相似度的语义检索。

### 2. 工具调用能力 (Tool Use)
在 `agent_core.py` 中，我们为 LLM 注册了 `retrieve_document` 函数。
- **决策机制**：当 LLM 发现用户的提问涉及特定事实（例如“文档中提到的 XX 方案是什么？”）时，它会自动生成 `tool_calls` 请求。
- **执行闭环**：Agent 拦截该请求，调用本地 `rag_engine` 检索，并将结果回填给 LLM。

### 3. 对话记忆管理
利用 `streamlit` 的 `session_state` 维护 `messages` 数组。
- 每一轮对话都会将 `(role, content)` 对追加到历史中，并随请求一起发送给 OpenAI，从而实现具备上下文感知的多轮交流。

### 4. 推理过程可视化
在 `app.py` 中，利用 `st.status` 组件动态展示 Agent 的中间状态：
- 思考中（Thought）
- 调用工具（Action）
- 观察结果（Observation）
- 生成最终回答（Final Answer）

### 5. 项目介绍选项卡
- 顶部新增“项目介绍”Tab，用于展示实验室项目卡片。
- 页面只读取 `doc_agent_demo/project_catalog` 下的持久化项目数据。
- 点击卡片后优先展示对应 Markdown 详情（含图片），无 Markdown 时回退章节视图。
- 新增项目时先离线解析并入库，再在网页展示。

## 🛠️ 如何运行

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   python -m pip install -r requirements.txt
   ```
2. 启动应用：
   ```bash
   streamlit run app.py
   python -m streamlit run app.py
   ```
3. 在侧边栏选择模型并输入 DashScope API Key。
4. 点击 `Apply 配置` 使配置生效。
5. 上传 PDF 文档并点击“开始解析”。
6. 开始提问。
7. 切换到顶部“项目介绍”选项卡可查看实验室项目卡片与详情。

## 📚 项目介绍数据入库

1. 使用脚本将 PPT 解析后写入后端目录：
   ```bash
   python doc_agent_demo/scripts/build_project_catalog.py --pptx your_project_slides.pptx --catalog doc_agent_demo/project_catalog --project-id your_project_id --category 你的项目分类 --display-order 1
   ```
2. 生成结果：
   - `doc_agent_demo/project_catalog/index.json`
   - `doc_agent_demo/project_catalog/projects/<project_id>.json`
   - `doc_agent_demo/project_catalog/media/<project_id>/`（自动抽取的图片资源）
3. 网页端只读取上述目录，不在访问时临时解析 PPT。

## 🔐 VIP 本地登录（调试模式）

1. 复制 `vip_config.example.json` 为 `vip_config.json`。
2. 在 `vip_config.json` 中填写用户名、密码哈希、API Key 与模型配置。
3. 启动后在侧边栏切换为“VIP登录”并输入账号密码。

密码哈希可用以下方式生成：
```bash
python -c "import hashlib; print(hashlib.sha256('你的密码'.encode()).hexdigest())"
```

## 🔢 手写数字识别的跨电脑配置

数字识别工具会按以下顺序查找 Python 解释器：
- 当前运行应用的 Python
- 项目目录下 `.venv`

推荐两台电脑统一做法：
1. 在项目根目录创建并使用同名环境（推荐 `.venv`）。
2. 在该环境安装依赖：`pip install -r requirements.txt`。
3. 先用当前应用 Python 运行，若失败会自动回退到项目 `.venv`，两者都不可用会提示检查依赖。

## ⚠️ 注意事项
- 当前支持 LLM 模型为 `qwen3.5-plus`，Embedding 模型为 `text-embedding-v4`，通过下拉列表选择后点击 `Apply 配置` 生效。
- 确保您的 API Key 余额充足，且网络环境可正常访问阿里云百炼兼容接口。
- `vip_config.json` 内含敏感信息，请勿提交到公共仓库。

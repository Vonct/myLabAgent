# myLabAgent

`myLabAgent` 是一个基于 `OpenAI SDK 兼容接口` 的实验室 Agent 项目，当前主链路已经切换到 `Responses API`，同时支持两种交互入口：

1. `Web`，基于 `Streamlit`
2. `CLI`，基于 `argparse + rich`

两个入口共享同一套 Agent runtime、RAG、工具系统和 session 持久化能力。

## 目录说明

核心文件和目录：

- `app.py`：Web 入口，负责 Streamlit 页面装配
- `cli.py`：CLI 入口，支持单轮命令和多轮 REPL
- `agent_core.py`：核心 Agent loop，负责模型调用和 tool-calling 闭环
- `services/agent_factory.py`：共享 runtime 工厂
- `services/session_service.py`：session 高层封装
- `core/session_store.py`：session JSON 落盘
- `rag_engine.py`：PDF 解析、切块、embedding、向量检索
- `core/tool_registry.py`：工具注册与权限检查
- `core/skill_loader.py`：本地 skill 发现与按需加载
- `config/tools.json`：工具 schema 定义
- `TECH_INTERACTION.md`：长期维护视角的技术说明

## 当前能力

### 1. 聊天问答
- 多轮对话
- OpenAI 兼容 `responses.create(...)` 调用
- 工具调用闭环
- 基础任务与 session 持久化

### 2. RAG 检索增强
- PDF 文本提取
- 文本切块
- Embedding 向量化
- Chroma 或本地 memory backend 检索

### 3. 工具系统
当前已接入工具：
- `retrieve_document`
- `recognize_handwritten_digit`
- `get_amap_weather`
- `load_skill`

### 4. Skill 机制
本地 skill 存放在：

```text
.agent_skills/skills/<skill_name>/SKILL.md
```

运行时只先暴露 skill metadata，模型需要时再通过 `load_skill(name)` 按需加载完整正文，避免把所有 skill 全文一开始塞进上下文。

## 运行架构

可以简单理解为三层：

1. `Client Layer`
   - Web: `app.py`, `ui_tabs/`
   - CLI: `cli.py`, `cli_repl.py`, `cli_render.py`
2. `Shared Runtime Layer`
   - `agent_core.py`
   - `services/agent_factory.py`
   - `services/session_service.py`
3. `Knowledge / Persistence Layer`
   - `rag_engine.py`
   - `core/session_store.py`
   - `project_catalog/`
   - `license_catalog/`
   - `vector_store.json` / `chroma_db/`

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

## Web 用法

启动方式：

```bash
python -m streamlit run app.py
```

Web 端当前提供：
- 项目介绍 Tab
- License 看板 Tab
- LabAgent 聊天 Tab
- 侧边栏模型与知识库配置

## CLI 用法

查看帮助：

```bash
python cli.py --help
```

进入多轮 REPL：

```bash
python cli.py chat
```

单轮提问：

```bash
python cli.py ask "解释当前项目结构"
```

恢复历史 session：

```bash
python cli.py resume <session_id>
```

列出最近 session：

```bash
python cli.py session-list
```

在 REPL 中可用的内置命令：
- `/help`
- `/session`
- `/models`：从 `vip_config.json` 读取可选模型，方向键移动，空格选中，回车确认
- `/skills`
- `/add2lib <pdf路径>`：把本地 PDF 按和 Web 端一致的流程导入知识库
- `/exit`

CLI 支持的常用参数：
- `--model`
- `--base-url`
- `--api-key`
- `--embedding-model`
- `--embedding-base-url`
- `--embedding-api-key`
- `--profile`
- `--sandbox`
- `--reasoning`
- `--max-tool-rounds`

## 配置来源

当前运行配置优先级大致是：

1. 命令行参数
2. 环境变量
3. `vip_config.json`
4. 代码默认值

如果你使用本地 VIP 配置：

1. 复制 `vip_config.example.json` 为 `vip_config.json`
2. 填入模型 API Key 和 base URL
3. CLI 可通过 `--profile <username>` 选择 profile
4. Web 可通过侧边栏登录和切换配置

## Session 持久化

session 会保存到：

```text
app_data/sessions/<session_id>.json
```

每个 session 文件当前包含：
- `session_id`
- `created_at`
- `updated_at`
- `messages`
- `tasks`

## 权限模型

当前工具权限等级：
- `READ_ONLY`
- `NETWORK`
- `FILE_WRITE`
- `EXEC`

共享 runtime 之上又定义了运行模式：
- `read-only`
- `workspace-write`
- `full-access`

CLI 目前通过 `--sandbox` 选择运行模式。

## 推荐维护方式

后续维护时，优先遵守这个边界：

- Web 变化放在 `app.py`、`ui_tabs/`、`core/runtime.py`
- CLI 变化放在 `cli.py`、`cli_repl.py`、`cli_render.py`
- Agent 能力变化放在 `agent_core.py`、`services/agent_factory.py`、`core/*`

如果你要继续往 `Claude Code / OpenCode` 方向演进，建议下一步优先补：
- 文件读取工具
- 目录浏览工具
- 文本搜索工具
- 文件写入工具
- shell 执行工具

## 相关文档

- [TECH_INTERACTION.md](D:\tongjiLabAgent\myLabAgent\TECH_INTERACTION.md)

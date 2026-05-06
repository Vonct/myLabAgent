# LangChain / LangGraph Learning

这个目录放两个最小 demo，用来理解 Agent 里的两种常见工程形态：

- `langchain_react_demo.py`: 用 LangChain 的高层 `create_agent` 写一个 ReAct tool loop。
- `langgraph_plan_execute_demo.py`: 用 LangGraph 显式写一个 Plan-and-Execute 状态图。

## 概念速记

`CoT` 是模型侧推理范式，回答前先产生中间推理。它不等于完整 Agent。

`ReAct` 是 Agent loop：模型决定是否调用工具，runtime 执行工具，把 observation 回填给模型，再继续循环。

`Plan-and-Execute` 是任务编排：先由 Planner 生成计划，再由 Executor 按步骤执行，必要时 replan。Planner 和 Executor 通常可以共用同一个底层模型，只是 system prompt、tool set 和 output schema 不同。

## 安装

```bash
pip install -U langchain langchain-openai langgraph
```

如果使用 OpenAI 模型：

```bash
export OPENAI_API_KEY="你的 key"
```

也可以用项目根目录的 `.env`，这样不用每次在终端输入环境变量：

```bash
cp langchain_learning/.env.example .env
```

然后编辑 `.env`：

```bash
LABAGENT_LEARNING_MODEL=your-model-name
LABAGENT_LEARNING_BASE_URL=https://your-server.example.com/v1
LABAGENT_LEARNING_API_KEY=your-key
LABAGENT_LEARNING_PROVIDER=openai
LABAGENT_LEARNING_USE_RESPONSES_API=false
```

`provider` 是 LangChain 用来选择模型适配器的字段。对 OpenAI-compatible 服务，通常保持 `openai` 即可；真正决定请求打到哪里的，是 `LABAGENT_LEARNING_BASE_URL`。

## 运行

```bash
python langchain_learning/langchain_react_demo.py
python langchain_learning/langgraph_plan_execute_demo.py
```

你可以通过环境变量换模型：

```bash
export LABAGENT_LEARNING_MODEL="gpt-5.4-mini"
```

如果你想接自己的 OpenAI-compatible 服务：

```bash
export LABAGENT_LEARNING_MODEL="your-model-name"
export LABAGENT_LEARNING_BASE_URL="https://your-server.example.com/v1"
export LABAGENT_LEARNING_API_KEY="your-key"
export LABAGENT_LEARNING_PROVIDER="openai"
```

大多数 OpenAI-compatible 服务实现的是 Chat Completions API。只有你确定自己的服务支持 OpenAI Responses API 时，才打开：

```bash
export LABAGENT_LEARNING_USE_RESPONSES_API="true"
```

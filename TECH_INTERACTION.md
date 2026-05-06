# myLabAgent 技术交互说明

这份文档记录项目里容易影响后续维护的 Agent loop、工具协议和持久化约定。

## 长期记忆机制

项目现在有三层记忆/知识来源：

- `messages`：当前 session 的完整 user/assistant transcript。
- `memories`：当前 session 内每个 task 的摘要卡片，用于短期任务回放。
- `long_term_memory`：跨 session 的用户偏好、工作流偏好、项目事实和约束记忆。

长期记忆不混入文档 RAG 的 `docs` collection，而是使用独立的 `long_term_memories` collection。默认路径：

```text
app_data/long_term_memory/chroma_db/
```

如果 Chroma 不可用，会回退到：

```text
app_data/long_term_memory/long_term_memories.json
```

### 每轮开始：召回并注入

每轮调用主 Agent 前，`agent_core.py` 会确定性构造长期记忆检索 query，而不是额外调用 LLM 生成 query。

query 由两部分组成：

```text
Current user request:
<latest user message>

Recent conversation context:
<recent 2-6 user/assistant messages, truncated>
```

这样可以处理“继续”“那你改”“为什么”这类依赖上下文的短 prompt。构造完成后：

1. 用 query 做 embedding。
2. 从 `long_term_memories` 检索 top-k。
3. 过滤 scope，只允许 `global` 或当前项目的 `project` 记忆进入。
4. 以一段短上下文注入主 Agent：

```text
Relevant long-term user/project memory:
1. [preference/project] 用户偏好先解释根因，再进行代码修改。
2. [workflow/project] myLabAgent 内部 canonical message 保持 type:text，外部 Responses API 前做格式转换。
```

控制参数：

- `LABAGENT_ENABLE_LONG_TERM_MEMORY=1`：是否启用长期记忆，默认启用。
- `LABAGENT_LONG_MEMORY_TOP_K=4`：每轮最多注入几条。
- `LABAGENT_LONG_MEMORY_QUERY_MESSAGES=6`：构造 query 时看最近几条消息。
- `LABAGENT_LONG_MEMORY_QUERY_CHARS=1600`：query 最近上下文最大字符数。

### 每轮结束：提取并沉淀

长期记忆不是主 Agent 的 tool，也不是每轮强行写一条。每轮完成后，外围流程调用 `record_long_term_memory(...)`，用一个独立 extractor 判断本轮是否值得沉淀。

extractor 输入：

```text
User prompt
Assistant answer
Tools used
Existing related long-term memories
```

extractor 输出 JSON：

```json
{
  "memories": [
    {
      "kind": "preference",
      "scope": "project",
      "text": "用户偏好先解释根因，再进行代码修改。",
      "confidence": 0.9,
      "evidence": "用户先询问调用失败原因，再要求修改。"
    }
  ]
}
```

只有满足条件的候选记忆才会 upsert：

- `kind` 只能是 `preference`、`workflow`、`project_fact`、`constraint`。
- `scope` 只能是 `global` 或 `project`。
- `confidence >= LABAGENT_LONG_MEMORY_MIN_CONFIDENCE`，默认 `0.72`。
- 不记录一次性任务、临时事实、天气、密钥、账号、私密标识。
- 通过 `scope + project_id + kind + normalized text` 生成稳定 id，重复内容会覆盖更新，而不是无限新增。

### 具体 session 例子

假设有一个 session：

```text
User: 为什么调用失败了？
Assistant: 根因是 session 历史里 assistant content 使用了 type:text，但 Responses API 需要 input_text。

User: 为什么你更建议继续 type:text 而不是直接换成 input_text？
Assistant: 因为 type:text 是项目内部 canonical 格式，input_text 是 Responses API wire format，建议只在适配层转换。

User: 行吧，那你改
Assistant: 已在 agent_core.py 的 _prepare_messages_for_responses 前增加转换。
```

第三轮结束后，extractor 可能生成：

```json
{
  "kind": "workflow",
  "scope": "project",
  "text": "myLabAgent 内部 canonical message 应保持 type:text，外部 Responses API 前转换为 input_text。",
  "confidence": 0.91,
  "evidence": "用户接受了保留内部格式、适配层转换的方案。"
}
```

之后新 session 里用户说：

```text
那这个 content 格式以后怎么处理？
```

长期记忆 query 会拼上最近上下文后检索，召回上面的 workflow 记忆，并注入主 Agent。主 Agent 因此能知道：这个项目的设计偏好是“内部 canonical 稳定，外部 API 边界转换”，而不需要用户重新解释。

## 图片生成与编辑工具

当前图片能力通过普通 tool-calling 接入主 Agent，而不是把图片模型作为主对话模型直接切换使用。

### 工具划分

- `generate_image`：用于从完整图片 prompt 生成新图。
- `edit_image`：用于编辑上一张生成图或指定源图片。

主 Agent 负责理解用户意图并整理 tool 入参。比如用户说“生成一张实验室风格封面图”，Agent 应该把上下文补全成独立可理解的图片 prompt 后调用 `generate_image`；用户继续说“背景改为黑色”，Agent 应调用 `edit_image`，而不是把这句话当成全新文生图 prompt。

### 图片资产

图片工具返回的结果会同时包含可展示图片和可持久化资产信息：

```json
{
  "type": "generated_image",
  "image_id": "img_...",
  "path": "app_data/generated_images/YYYY_MM_DD/img_....png",
  "image_url": "data:image/png;base64,...",
  "prompt": "...",
  "operation": "generate",
  "model": "openai/gpt-5.4-image-2",
  "provider": "openrouter",
  "api_mode": "responses"
}
```

`image_url` 用于当轮 UI/API 展示，不写入 session JSON，避免 session 文件膨胀。`path`、`image_id`、`prompt` 等轻量字段会写入 session 的 `generated_images`。

### “上一张图”的解析

`core/session_store.py` 提供：

- `append_generated_image(...)`：保存生成图片资产。
- `get_latest_generated_image(...)`：返回当前 session 最近一张生成图片。

在 `agent_core.py` 的工具执行阶段，如果模型调用 `edit_image` 但没有传 `source_image_path`，Agent 会自动注入当前 session 的最近图片资产。这样用户无需知道上一张图的路径，也可以说“把背景改为黑色”“刚才那张改成横版”等。

### 图片回填

图片 tool 的返回 JSON 会被 `_extract_generated_image_asset(...)` 识别。识别成功后：

- 写入 `generated_images` 资产列表。
- 把 `image_url` 追加到本轮 assistant canonical message 的 `image_url` content part。
- `/chat` 和 `/miniprogram/chat` API 响应会通过 `images` 字段返回图片 URL。

Streamlit UI 已经能渲染 canonical message 中的 `image_url`，所以工具生成的图片可以在聊天窗口展示。

## OpenRouter 图片调用

图片服务位于 `image_generation_service.py`，默认使用 OpenRouter 的 Responses 兼容端点：

```text
POST https://openrouter.ai/api/v1/responses
model = openai/gpt-5.4-image-2
```

默认配置：

- `LABAGENT_IMAGE_API_KEY` 或 `OPENROUTER_API_KEY`
- `LABAGENT_IMAGE_MODEL=openai/gpt-5.4-image-2`
- `LABAGENT_IMAGE_BASE_URL=https://openrouter.ai/api/v1`
- `LABAGENT_IMAGE_API_MODE=responses`

`aspect_ratio` 是本项目 tool 层的便利字段，也是部分 OpenRouter 图片配置里的抽象字段；它不是 OpenAI GPT Image 2 的原生参数名。更贴近 OpenAI 官方图片参数的是 `size`，例如 `1024x1024`、`1536x1024`、`1024x1536`。当前实现会在未显式传 `size` 时，把常见 `aspect_ratio` 映射为 `size`：

- `1:1` -> `1024x1024`
- `16:9` -> `1536x1024`
- `9:16` -> `1024x1536`

如果 OpenRouter 的 Responses 兼容层对该图片模型不稳定，可以切换：

```bash
export LABAGENT_IMAGE_API_MODE=chat_completions
```

此时会调用：

```text
POST https://openrouter.ai/api/v1/chat/completions
modalities = ["image", "text"]
```

## 主模型调用适配层

主 Agent 内部仍然保持 Responses 风格的 canonical input：

- 普通对话：`{"role": "user", "content": [{"type": "input_text", "text": "..."}]}`
- 工具调用：`{"type": "function_call", "name": "...", "arguments": "...", "call_id": "..."}`
- 工具结果：`{"type": "function_call_output", "call_id": "...", "output": "..."}`

真正发给模型前统一经过 `core/model_adapter.py`。默认 `api_mode=responses` 时，适配器直接调用 `client.responses.create(...)`；当模型或供应商只支持 OpenAI Chat Completions 兼容接口时，将 `api_mode` 设置为 `chat_completions`，适配器会在边界层转换：

- `input_text` / `output_text` / `text` 合并为 Chat message content。
- `input_image` / `image_url` 转为 Chat Completions 的多模态 content part。
- Responses 风格 function tool schema 转为 `{"type":"function","function":...}`。
- `function_call` / `function_call_output` 转为 assistant `tool_calls` 和 tool message。
- Chat Completions 返回值再规范化成带 `output` / `output_text` / `usage` 的轻量 Response 对象，供现有 Agent loop 继续解析。

这样上层 tool loop、长期记忆 extractor、session 持久化都不需要知道底层到底走 `/responses` 还是 `/chat/completions`。配置入口：

```bash
export LABAGENT_API_MODE=chat_completions
# 或 CLI:
python cli.py ask --api-mode chat_completions "nihao"
```

VIP 配置中可以按模型指定：

```json
{
  "llm_models": {
    "mimo-v2.5-pro": {
      "api_key": "sk-...",
      "base_url": "https://example.com/v1",
      "api_mode": "chat_completions"
    }
  }
}
```

## OpenAI Responses API 结论

OpenAI 官方图片文档确认，GPT Image 2 / GPT Image 系列可以通过 Responses API 使用图片生成能力。因此项目设计优先采用 Responses 形态；OpenRouter 侧保留 Chat Completions 兼容模式只是为了供应商兼容兜底，不是主设计方向。

## 权限与持久化边界

`generate_image` 和 `edit_image` 注册为 `FILE_WRITE` 权限，因为它们会把图片落盘到：

```text
app_data/generated_images/YYYY_MM_DD/
```

图片 base64 不进入 session 持久化；session 只保存轻量资产 metadata。工具调用轨迹仍记录在 `tasks[*].tool_events`，其中只保留 `output_preview`，避免完整图片数据污染任务日志。

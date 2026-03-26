# OpenAI API Diff: Chat Completions vs Responses

这份文档面向当前 `myLabAgent` 项目，整理 `Chat Completions API` 与 `Responses API` 的主要区别，重点参考本次迁移和前面问答里反复讨论过的问题。

主要参考：

- [Chat Completions API Reference](https://platform.openai.com/docs/api-reference/chat/create-chat-completion)
- [Responses vs Chat Completions](https://platform.openai.com/docs/guides/responses-vs-chat-completions)
- [Function Calling Guide](https://platform.openai.com/docs/guides/function-calling?api-mode=responses)

## 1. 一句话区别

- `Chat Completions` 以 `messages` 为中心，核心抽象是“聊天消息”。
- `Responses` 以 `input/output items` 为中心，核心抽象是“结构化输入项和输出项”，更适合 agent、tool calling、多模态和复杂状态续接。

对当前项目来说，可以粗略理解为：

- 旧版：`chat.completions.create(messages=[...])`
- 新版：`responses.create(input=[...], instructions=...)`

## 2. 输入结构区别

### 2.1 Chat Completions

典型输入：

```python
completion = client.chat.completions.create(
    model="gpt-4.1",
    messages=[
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": "介绍一下 Responses API"}
    ]
)
```

特点：

- 核心字段是 `messages`
- 系统提示词通常直接放在 `role="system"` 消息里
- 多轮历史一般由客户端自己维护并重复传入

### 2.2 Responses

典型输入：

```python
response = client.responses.create(
    model="gpt-5",
    instructions="你是一个助手",
    input=[
        {"role": "user", "content": "介绍一下 Responses API"}
    ]
)
```

特点：

- 核心字段是 `input`
- 系统提示词更推荐放在 `instructions`
- `input` 不只支持普通 message，还支持 `function_call_output` 等 typed items

## 3. role/content 是什么

`role/content` 不是 LLM 的“底层唯一输入方式”，而是当前 OpenAI SDK/API 提供的一种上层协议。

更准确地说：

- 底层模型处理的是 token 序列
- SDK/API 为了表达多轮对话、系统提示、工具调用，设计了 `role/content` 或 typed item 的结构

因此：

- `{"role": "user", "content": "你好"}` 是协议允许的 message
- `{"role": "vonct", "content": "i'm whom"}` 这种 Python dict 语法本身能写，但 API 大概率不会接受，因为 `role` 不是自由字段，而是受限枚举

## 4. 图片 + 文本输入示例

在当前项目里，用户同时发送图片和文字时，内部消息会接近：

```python
[
    {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64,iVBORw0KGgoAAA..."
                }
            },
            {
                "type": "text",
                "text": "请识别图片里的内容"
            }
        ]
    }
]
```

在 `Responses API` 中可直接作为 `input`：

```python
response = client.responses.create(
    model="gpt-5",
    instructions="你是图像理解助手，请用中文回答。",
    input=[
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAA..."}
                },
                {
                    "type": "text",
                    "text": "请识别图片里的内容"
                }
            ]
        }
    ]
)
```

## 5. 输出结构区别

### 5.1 Chat Completions

典型输出读取方式：

```python
text = completion.choices[0].message.content
```

核心返回结构偏向单条 assistant message：

```python
{
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": "这是回答文本"
            }
        }
    ]
}
```

### 5.2 Responses

典型输出读取方式：

```python
text = response.output_text
```

或者遍历 `response.output`：

```python
{
    "id": "resp_123",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "这是回答文本"
                }
            ]
        }
    ],
    "output_text": "这是回答文本"
}
```

关键区别：

- `Chat Completions` 重点看 `choices[0].message`
- `Responses` 重点看 `output[]`
- `Responses` 的 `output[]` 里可能混合：
  - `message`
  - `reasoning`
  - `function_call`
  - 其他 typed items

所以不能简单理解成“返回只是在原来外面多了一个 `type`”，而是输出模型从“单消息中心”变成了“多输出项中心”。

## 6. token 统计字段区别

### Chat Completions

常见字段：

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`

### Responses

常见字段：

- `input_tokens`
- `output_tokens`
- `total_tokens`

当前项目在 `agent_core.py` 中做了兼容处理，新旧字段都尝试读取。

## 7. 工具调用区别

这是两者差异最大的部分之一。

### 7.1 Chat Completions 的工具调用

工具定义常见形态：

```python
tools=[
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询天气",
            "parameters": {...}
        }
    }
]
```

模型发出工具调用后，通常从这里读取：

```python
tool_call = completion.choices[0].message.tool_calls[0]
func_name = tool_call.function.name
arguments = tool_call.function.arguments
```

工具执行结果需要回填成一条 `role="tool"` 消息：

```python
{
    "tool_call_id": tool_call.id,
    "role": "tool",
    "name": func_name,
    "content": tool_output,
}
```

### 7.2 Responses 的工具调用

工具定义更扁平：

```python
tools=[
    {
        "type": "function",
        "name": "get_weather",
        "description": "查询天气",
        "parameters": {...}
    }
]
```

模型返回的工具请求在 `response.output` 中，以 `type="function_call"` 出现：

```python
{
    "type": "function_call",
    "name": "get_weather",
    "arguments": "{\"city\":\"上海\"}",
    "call_id": "call_123"
}
```

工具执行结果不再用 `role="tool"` 回填，而是直接传 typed item：

```python
{
    "type": "function_call_output",
    "call_id": "call_123",
    "output": tool_output,
}
```

这说明：

- `role="tool"` 属于旧的聊天消息风格
- `function_call_output` 属于 `Responses API` 的 typed item 风格

## 8. 为什么项目里还会看到 role == tool

这是一个很容易混淆的点。

当前项目里：

- 给 `Responses API` 继续回传工具结果时，使用的是 `function_call_output`
- 但项目内部的历史消息和 session 存储，仍然保留了旧的聊天消息模型，因此历史里仍可能存在：

```python
{
    "role": "tool",
    "name": "get_weather",
    "tool_call_id": "...",
    "content": "..."
}
```

所以：

- `role="tool"` 是项目内部历史消息的兼容格式
- `function_call_output` 是当前 `Responses` 请求链里真正用于续接工具结果的协议格式

两者不是同一层。

## 9. previous_response_id 是什么

`previous_response_id` 可以理解为：把当前请求接到上一轮 response 上，形成一条服务端维护的 continuation 链。

例如：

```python
r1 = client.responses.create(...)
r2 = client.responses.create(
    input=[{"type": "function_call_output", ...}],
    previous_response_id=r1.id
)
```

它的作用是：

- 让一次 agent 执行过程中的后续调用接续上一轮结果
- 特别适合工具调用闭环

## 10. previous_response_id 会不会让你失去上下文控制权

会失去一部分，但不是全部。

### 10.1 失去的控制

如果完全依赖 `previous_response_id`，你不容易：

- 手工裁剪历史
- 删掉某一轮
- 重排历史顺序
- 自己控制上下文压缩策略

### 10.2 仍然保留的控制

你仍然可以控制：

- 每轮发什么新输入
- 每轮是否继续这条链
- 什么时候断链
- 每轮传什么 `instructions`

### 10.3 当前项目的做法

当前项目是“优先 `previous_response_id` + 本地回退”的混合模式：

- 长期会话历史仍由本地 `st.session_state.messages` 和 `session_store` 管理
- 一次 `agent.chat(...)` 内部出现多轮工具调用时，优先使用 `previous_response_id` 续接
- 如果兼容层返回里拿不到 `response.id`，回退到本地 transcript 重放（把必要 typed items 再次放进 `input`）

这意味着：

- 产品级会话控制权仍在本地
- 工具链路优先由 `Responses` 服务端 continuation 维护
- 遇到兼容层差异时仍有可用兜底

## 11. instructions 为什么仍然要每轮显式传

官方文档说明：使用 `previous_response_id` 时，上一轮的 `instructions` 不会自动继承。

这意味着，如果你希望系统提示稳定生效，就需要每次请求都显式传：

```python
client.responses.create(
    model="gpt-5",
    instructions=self.system_prompt,
    input=...,
    previous_response_id=...
)
```

所以：

- 创建 agent 实例时保存 `system_prompt`
- 每次真正发请求时再把它作为 `instructions` 传入

两者不冲突。

## 12. 当前项目里的 `_prepare_messages_for_responses(...)` 在做什么

这个函数不是在构造 `function_call_output`，而是在做：

`项目内部消息结构 -> Responses API 可接受的输入消息`

它主要做三件事：

1. 跳过 `system`
   - 因为系统提示现在放在 `instructions`
2. 保留 `user / assistant` 历史消息，跳过 `tool`
   - 工具结果续接使用 `function_call_output` typed item，而不是把 `role="tool"` 回传给 `Responses API`
3. 规范化 `content`
   - 兼容纯文本
   - 兼容图片 + 文本数组

所以这个函数的职责是“整理用户/助手历史消息”，不是“构造工具续接 typed item”。

## 13. 为什么有时工具都跑完了，但最后没返回文本

在当前项目里，如果工具都执行成功，但最终显示：

`模型本轮没有返回可见文本，请重试或切换模型。`

最可能的原因不是工具失败，而是：

- 模型通过兼容层返回了 response
- 也产生了 token
- 但当前代码对 `response.output` 的解析逻辑，没命中 provider 实际返回的文本字段结构

在使用 OpenAI 兼容层时尤其要注意：

- OpenAI 原生 `Responses API` 的结构是一种规范
- 第三方兼容服务可能行为接近，但不保证字段完全一致

## 14. 迁移判断

如果场景是：

- 简单多轮聊天
- 没有复杂工具链
- 已经有大量 `messages` 逻辑

那么 `Chat Completions` 仍然够用。

如果场景是：

- agent loop
- 多轮工具调用
- 多模态输入输出
- reasoning 模型
- 需要更丰富的输出项结构

那么 `Responses API` 更合适。

对当前 `myLabAgent` 项目来说，迁到 `Responses API` 是合理方向，但需要继续加强兼容层返回结构的解析鲁棒性。

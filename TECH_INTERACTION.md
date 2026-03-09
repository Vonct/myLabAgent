# myLabAgent Technical Interaction Notes

This document focuses on runtime behavior in `chat_tab`, especially context flow, SDK message assembly, and session/task logging.

## 1. Trigger Path After Sending Prompt

When a user types in Chat tab and sends:

1. `ui_tabs/chat_tab.py`
- `st.chat_input(...)` receives `prompt` (line ~94)
- `start_task(session_store, prompt)` creates a task record (line ~95)
- Build `user_message` and append to `st.session_state.messages` (lines ~105-112)
- Persist the same user message with `session_store.append_message(...)` (line ~112)

2. Still in `ui_tabs/chat_tab.py`
- Call `st.session_state.agent.chat(...)` with:
  - `messages=st.session_state.messages`
  - `reasoning_mode`
  - `supports_thinking`
  - `session_store`
  - `session_id`
  - `task_id`
  (lines ~128-135)

3. `agent_core.py::DocumentAgent.chat(...)`
- Build `full_messages = [{"role": "system", "content": self.system_prompt}] + messages` (line ~197)
- First SDK call: `client.chat.completions.create(...)` with `tools=self.tools` and `tool_choice="auto"` (lines ~204-211)
- If tool calls exist:
  - Execute each tool via `tool_registry.execute(...)` (line ~223)
  - Append tool result back into `full_messages` as `role="tool"` (lines ~235-241)
  - Persist tool events via `session_store.append_tool_event(...)` (lines ~225-234)
  - Second SDK call with updated `full_messages` (lines ~244-249)
- If no tool call:
  - Return initial model output directly

4. Back to `ui_tabs/chat_tab.py`
- Stream chunks to UI status panel/message panel
- On success:
  - Append assistant message to `st.session_state.messages`
  - Persist assistant message via `session_store.append_message(...)`
  - Mark task done via `session_store.finish_task(..., status="completed")`
- On error:
  - `session_store.finish_task(..., status="failed")`

## 2. Final Message Payload Sent To SDK

### First model call payload
From `agent_core.py`:

```python
full_messages = [{"role": "system", "content": self.system_prompt}] + messages

response = self.client.chat.completions.create(
    model=self.llm_model,
    messages=full_messages,
    tools=self.tools,
    tool_choice="auto",
    stream=False,
    **extra_params,
)
```

`messages` comes from `st.session_state.messages`, and each user turn in chat tab is one of:

- Text only:
```python
{"role": "user", "content": "..."}
```

- Multimodal image+text:
```python
{
  "role": "user",
  "content": [
    {"type": "image_url", "image_url": {"url": "data:..."}},
    {"type": "text", "text": "..."}
  ]
}
```

### Second model call payload (tool path only)
After tool execution, `full_messages` is extended with:

- assistant tool call message (`initial_msg`)
- one or more `role="tool"` messages

Then second SDK call uses this augmented `full_messages`.

## 3. Tool/Permission Context

- Tool definitions loaded from `config/tools.json`
- Registry in `core/tool_registry.py`
- Permission gate in `core/permissions.py`
- Agent registers current tools during init:
  - `retrieve_document` -> `READ_ONLY`
  - `recognize_handwritten_digit` -> `EXEC`
  - `get_amap_weather` -> `NETWORK`

## 4. Session/Task Logging Semantics

Storage path:
- `myLabAgent/app_data/sessions/<session_id>.json`

Data shape (`core/session_store.py`):
- `session_id`, `created_at`, `updated_at`
- `messages`: all persisted user/assistant turns in this session
- `tasks`: each send action creates one task with
  - `task_id`, `prompt`, `status`, `tool_events`, `result`

### Your question: "Does each page before refresh count as one session?"
Practical behavior in current code:

- One Streamlit runtime session (one browser tab runtime) gets one `session_id`.
- During reruns in the same runtime session, same `session_id` is reused.
- A hard refresh/new tab/new runtime creates a new `session_id` and a new JSON file.
- So yes: in normal usage, one page runtime (before hard refresh / reconnect) maps to one session file containing full persisted history for that runtime.

## 5. Quick Code Map

- Chat send entry: `ui_tabs/chat_tab.py` (~94)
- Task start: `ui_tabs/chat_tab.py` (~95)
- Persist user msg: `ui_tabs/chat_tab.py` (~112)
- Agent call: `ui_tabs/chat_tab.py` (~128-135)
- SDK message assembly: `agent_core.py` (~197)
- First SDK call: `agent_core.py` (~204-211)
- Tool execution + tool event log: `agent_core.py` (~223, ~225-234)
- Second SDK call (tool path): `agent_core.py` (~244-249)
- Persist assistant msg + finish task: `ui_tabs/chat_tab.py` (~160-162)
- Session storage implementation: `core/session_store.py`

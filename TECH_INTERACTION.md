# myLabAgent 交互技术说明

这份文档用于长期维护 `myLabAgent` 的页面交互结构，帮助你快速理解每个模块在做什么、数据怎么流动、改动时该看哪里。

## 推荐阅读顺序

1. 先看 `app.py`：理解启动流程、配置面板、全局状态。
2. 再看 `ui_tabs/projects_tab.py`：理解项目卡片和详情展示链路。
3. 再看 `ui_tabs/licenses_tab.py`：理解 License 看板卡片、状态灯、目录数据关系。
4. 最后看 `ui_tabs/chat_tab.py`：理解聊天输入、图片附件、Tool 调用结果展示。

## 模块职责

### `app.py`

- 定义全局常量（目录、模型列表、上传目录）。
- 处理侧边栏配置（API Key、VIP 登录、文档上传、向量库统计）。
- 初始化 `st.session_state`。
- 应用全局样式（Apple 风格 + 微动画）。
- 创建三个主选项卡，并把渲染委托给子模块。
- 在 VIP 模式下支持按 LLM 模型映射不同 API Key。

### `ui_tabs/projects_tab.py`

- 读取 `project_catalog/index.json` 和 `project_catalog/projects/*.json`。
- 渲染项目卡片网格。
- 渲染项目详情（优先 Markdown，其次 JSON 结构化字段）。
- 处理 Markdown 内本地图片引用。

### `ui_tabs/licenses_tab.py`

- 读取 `license_catalog/index.json` 与 `license_catalog/licenses/*.json`。
- 渲染软件 License 卡片（左侧图标、中部 License 列表、右上角状态灯）。
- 根据 `expired_date` 计算状态灯：可用 / 即将到期 / 不可用。
- 缺少图标或日期格式异常时做降级展示，避免页面报错。

### `ui_tabs/chat_tab.py`

- 渲染问答界面与消息流。
- 管理聊天图片附件（上传、预览、移除），位置在输入框上方。
- 把图片路径拼进用户问题，让模型按问题语义决定是否使用图片信息。
- 消费 `agent.chat(...)` 的流式事件并回显（thought/tool/result/answer）。
- 若未配置 `AMAP_MAPS_API_KEY`，展示天气工具不可用提示。

## 页面交互主链路

## 1) 启动阶段

- 运行 `python -m streamlit run app.py` 后，`app.py` 初始化会话状态并渲染侧边栏。
- 未配置 API Key 时，项目介绍仍可访问；问答页仅提示不可输入。

## 2) 项目介绍链路

- `projects_tab.load_projects(...)` 读取索引与项目元数据。
- 点击卡片“查看详情”后，保存 `selected_project_id` 到 `session_state`。
- 详情页优先加载与 `source.file` 同名的 `.md`，否则回退到 JSON 的 `detail/sections`。

## 3) 文档问答链路

- 侧边栏点击 **Apply 配置** 后初始化 `RAGEngine` 和 `DocumentAgent`。
- 聊天区输入问题后写入 `session_state.messages`。
- 如有图片附件，路径会注入到文本提示中，供模型在相关问题下使用。
- `agent.chat(...)` 流式返回事件，前端按事件类型更新思考面板与回答文本。

## 4) License 看板链路

- `licenses_tab.load_software_licenses(...)` 读取索引并按 `id` 加载详情文件。
- 卡片数据来自 `licenses/<software_id>.json`，并叠加 `index.json` 中的排序与分类。
- `compute_license_status(...)` 以当天日期为基准计算右上角状态灯：
  - 存在未过期 License：可用（绿）
  - 存在 30 天内到期 License：即将到期（黄）
  - 全部过期或无有效日期：不可用（红）

## 核心状态字段（`st.session_state`）

- `messages`: 聊天消息历史。
- `rag_engine`: 向量化与检索引擎实例。
- `agent`: 文档助手实例。
- `current_runtime_signature`: 当前生效配置签名。
- `selected_project_id`: 当前选中的项目卡片 ID。
- `pending_chat_image_path` / `pending_chat_image_name`: 待发送图片附件。

## 数据目录约定

- `project_catalog/index.json`: 项目列表入口。
- `project_catalog/projects/<project_id>.json`: 卡片结构化内容。
- `project_catalog/<name>.md`: 项目详情 Markdown（可选，优先级更高）。
- `project_catalog/media/<project_id>/`: 项目图片资源目录。
- `license_catalog/index.json`: 软件 License 列表入口（控制启用、排序、分类）。
- `license_catalog/licenses/<software_id>.json`: 单个软件 License 详情。
- `license_catalog/media/`: 软件图标目录。

## License 模板如何修改

### 先改入口：`license_catalog/index.json`

- 在 `softwares` 数组里新增或编辑软件项。
- 关键字段：
  - `id`: 唯一标识，必须与详情文件名一致。
  - `name`: 展示名称。
  - `enabled`: 是否显示在看板中。
  - `display_order`: 卡片排序（数字越小越靠前）。
  - `category`: 分类文案。

### 再改详情：`license_catalog/licenses/<id>.json`

- 文件名必须等于 `index.json` 里的 `id`，例如 `id=matlab` 对应 `licenses/matlab.json`。
- 关键字段：
  - `name`: 软件名称（可与 index 一致）。
  - `logo`: 图标相对路径，例如 `media/matlab.png`。
  - `licenses`: License 列表，支持多个条目。
  - `licenses[].license_name`: License 名称。
  - `licenses[].expired_date`: 到期日期，格式必须是 `YYYY-MM-DD`。

### `index.json` 和 `licenses/` 的关系

- `index.json` 负责“有哪些软件要展示、展示顺序是什么、是否启用”。
- `licenses/<id>.json` 负责“每个软件展示什么内容（logo、License 明细、到期时间）”。
- 页面渲染时会先读 `index.json`，再按每个 `id` 去找同名详情文件；找不到详情文件则跳过该软件。

## VIP 多模型配置

VIP 配置支持每个用户声明可用模型池，并在模型节点内配置 `api_key/base_url`：

- `llm_models.<llm_model>.api_key`
- `llm_models.<llm_model>.base_url`
- `embedding_models.<embedding_model>.api_key`
- `embedding_models.<embedding_model>.base_url`
- `embedding_model`（可选默认 Embedding 模型）

VIP 登录后才会展示模型下拉框，候选项来自当前用户的 `llm_models` 与 `embedding_models`。

手动输入模式下，页面按你选择的模型读取代码内预置 URL，只需要填写 LLM/Embedding API Key。

## 常见改动入口

- 想改卡片排版：看 `ui_tabs/projects_tab.py`。
- 想改 License 卡片和状态灯：看 `ui_tabs/licenses_tab.py`。
- 想改聊天流程或附件行为：看 `ui_tabs/chat_tab.py`。
- 想改全局视觉风格与微动画：看 `app.py` 的 `<style>`。
- 想加新项目：改 `project_catalog/index.json` + 新建 `projects/<id>.json`（可选 `.md` 和 `media`）。
- 想加新软件 License：改 `license_catalog/index.json` + 新建 `licenses/<id>.json`（可选 `media` 图标）。

## 维护约定

- 新增页面级逻辑时，优先放入 `ui_tabs/` 下对应模块，避免 `app.py` 继续膨胀。
- 新增用户可感知交互时，同时更新本文件对应章节。
- 若修改了数据目录或状态字段命名，必须同步更新“数据目录约定”和“核心状态字段”。

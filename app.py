import streamlit as st
import os
import json
import hashlib
from pathlib import Path
from rag_engine import RAGEngine
from agent_core import DocumentAgent
from io import BytesIO
from ui_tabs.chat_tab import render_chat_tab
from ui_tabs.projects_tab import render_projects_tab

VIP_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "vip_config.json")
SUPPORTED_LLM_MODELS = ["qwen3.5-plus","MiniMax-M2.5"]
SUPPORTED_EMBEDDING_MODELS = ["text-embedding-v4"]
DEFAULT_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
PRESET_LLM_BASE_URLS = {
    "qwen3.5-plus": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "MiniMax-M2.5": "https://api.minimaxi.com/v1",
}
PRESET_EMBEDDING_BASE_URLS = {
    "text-embedding-v4": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}
PROJECT_CATALOG_DIR = Path(__file__).resolve().parent / "project_catalog"
PROJECTS_DIR = PROJECT_CATALOG_DIR / "projects"
PROJECT_INDEX_FILE = PROJECT_CATALOG_DIR / "index.json"
CHAT_UPLOAD_DIR = Path(__file__).resolve().parent / "uploads" / "chat_images"


def load_vip_config(file_path: str):
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    users = data.get("users", []) if isinstance(data, dict) else []
    return {u.get("username"): u for u in users if u.get("username")}


def verify_vip_user(user: dict, password: str):
    if not user:
        return False
    plain = user.get("password_plain")
    if plain is not None:
        return password == plain
    expected_hash = user.get("password_sha256")
    if not expected_hash:
        return False
    pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return pwd_hash == expected_hash


def resolve_model_base_url(model_name: str, preset_base_urls: dict, default_base_url: str):
    return preset_base_urls.get(model_name, default_base_url)


def _normalize_model_pool(raw_pool):
    normalized = {}
    if not isinstance(raw_pool, dict):
        return normalized
    for model_name, model_config in raw_pool.items():
        if isinstance(model_config, dict):
            normalized[model_name] = {
                "api_key": model_config.get("api_key", ""),
                "base_url": model_config.get("base_url", ""),
            }
        elif isinstance(model_config, str):
            normalized[model_name] = {"api_key": model_config, "base_url": ""}
    return normalized


def resolve_vip_model_pools(profile: dict):
    llm_pool = _normalize_model_pool(profile.get("llm_models"))
    embedding_pool = _normalize_model_pool(profile.get("embedding_models"))
    if not llm_pool:
        legacy_llm_keys = profile.get("llm_api_keys_by_model", {})
        if isinstance(legacy_llm_keys, dict):
            for model_name, api_key in legacy_llm_keys.items():
                llm_pool[model_name] = {
                    "api_key": api_key,
                    "base_url": resolve_model_base_url(model_name, PRESET_LLM_BASE_URLS, DEFAULT_LLM_BASE_URL),
                }
    if not embedding_pool:
        legacy_embedding_keys = profile.get("embedding_api_keys_by_model", {})
        if isinstance(legacy_embedding_keys, dict):
            for model_name, api_key in legacy_embedding_keys.items():
                embedding_pool[model_name] = {
                    "api_key": api_key,
                    "base_url": resolve_model_base_url(model_name, PRESET_EMBEDDING_BASE_URLS, DEFAULT_EMBEDDING_BASE_URL),
                }
    return llm_pool, embedding_pool

# 页面配置
st.set_page_config(
    page_title="Agent 文档阅读框架演示",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 样式美化
st.markdown("""
<style>
    /* 全局字体与背景 */
    html, body, [data-testid="stAppViewContainer"] {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
        background-color: #ffffff;
        color: #1d1d1f;
    }
    
    /* 侧边栏玻璃拟态 */
    [data-testid="stSidebar"] {
        background-color: rgba(245, 245, 247, 0.8) !important;
        backdrop-filter: blur(20px);
        border-right: 1px solid rgba(0, 0, 0, 0.1);
    }
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] .stTextInput > div > div > input,
    [data-testid="stSidebar"] [data-baseweb="input"] > div {
        background: rgba(255, 255, 255, 0.82) !important;
        border: 1px solid rgba(0, 0, 0, 0.12) !important;
        border-radius: 12px !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) !important;
        transition: border-color 0.24s ease, box-shadow 0.24s ease, transform 0.24s ease !important;
    }
    [data-testid="stSidebar"] [data-baseweb="select"] > div:focus-within,
    [data-testid="stSidebar"] .stTextInput > div > div > input:focus {
        border-color: rgba(0, 122, 255, 0.45) !important;
        box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.12) !important;
        transform: translateY(-1px);
    }
    [data-testid="stSidebar"] .stRadio > div[role="radiogroup"] {
        background: rgba(255, 255, 255, 0.76);
        border: 1px solid rgba(0, 0, 0, 0.08);
        border-radius: 12px;
        padding: 4px;
        gap: 4px;
    }
    [data-testid="stSidebar"] .stRadio label {
        border-radius: 10px;
        padding: 6px 10px;
        transition: background-color 0.22s ease, transform 0.22s ease;
    }
    [data-testid="stSidebar"] .stRadio label:hover {
        background: rgba(0, 122, 255, 0.08);
        transform: translateY(-1px);
    }
    
    /* 聊天气泡样式 */
    .stChatMessage {
        border-radius: 18px !important;
        padding: 12px 16px !important;
        margin-bottom: 12px !important;
        border: none !important;
        animation: messageSlideIn 0.34s ease-out;
    }
    
    /* 用户气泡 - Apple Blue */
    [data-testid="stChatMessageUser"] {
        background-color: #007aff !important;
        color: white !important;
    }
    [data-testid="stChatMessageUser"] p {
        color: white !important;
    }
    
    /* 助手气泡 - Light Gray */
    [data-testid="stChatMessageAssistant"] {
        background-color: #f2f2f7 !important;
        color: #1d1d1f !important;
    }
    
    /* 卡片圆角 */
    [data-testid="stVerticalBlock"] div[style*="border"] {
        border-radius: 16px !important;
        border: 1px solid rgba(0, 0, 0, 0.1) !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05) !important;
        padding: 20px !important;
        background-color: white !important;
        transition: transform 0.28s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.28s ease, border-color 0.28s ease !important;
        animation: cardFadeIn 0.55s ease-out;
    }
    [data-testid="stVerticalBlock"] div[style*="border"]:hover {
        transform: translateY(-6px) scale(1.01);
        box-shadow: 0 18px 34px rgba(15, 23, 42, 0.16) !important;
        border-color: rgba(0, 122, 255, 0.28) !important;
    }
    
    /* 按钮样式 */
    .stButton button {
        border-radius: 12px !important;
        border: none !important;
        background-color: #f2f2f7 !important;
        color: #007aff !important;
        font-weight: 600 !important;
        transition: all 0.2s ease !important;
    }
    .stButton button:hover {
        background-color: #e5e5ea !important;
        transform: scale(1.03) translateY(-2px);
    }
    .stButton button[kind="primary"] {
        background-color: #007aff !important;
        color: white !important;
    }
    
    /* 输入框置底微调 */
    [data-testid="stChatInput"] {
        bottom: 20px !important;
        border-radius: 24px !important;
        border: 1px solid rgba(0, 0, 0, 0.1) !important;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05) !important;
        transition: box-shadow 0.22s ease, border-color 0.22s ease !important;
    }
    [data-testid="stChatInput"]:focus-within {
        border-color: rgba(0, 122, 255, 0.45) !important;
        box-shadow: 0 10px 22px rgba(0, 122, 255, 0.12) !important;
    }

    /* 状态栏 */
    .status-box {
        background-color: #f2f2f7;
        border: none;
        border-radius: 12px;
        padding: 12px;
        margin-bottom: 12px;
        color: #86868b;
    }

    [data-testid="stMarkdownContainer"] h1 {
        font-size: 2.1rem;
        line-height: 1.25;
        letter-spacing: -0.02em;
        margin-top: 0.4rem;
        margin-bottom: 0.9rem;
    }
    [data-testid="stMarkdownContainer"] h2 {
        font-size: 1.35rem;
        line-height: 1.35;
        letter-spacing: -0.01em;
        margin-top: 1.1rem;
        margin-bottom: 0.55rem;
    }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li {
        font-size: 1.02rem;
        line-height: 1.75;
    }
    [data-testid="stTabs"] button {
        transition: transform 0.24s ease, color 0.24s ease, background-color 0.24s ease !important;
    }
    [data-testid="stTabs"] button:hover {
        transform: translateY(-2px) scale(1.03);
        color: #007aff !important;
        background-color: rgba(0, 122, 255, 0.08) !important;
    }
    [data-testid="stImage"] img {
        border-radius: 14px;
        transition: transform 0.32s ease, box-shadow 0.32s ease;
    }
    [data-testid="stImage"] img:hover {
        transform: scale(1.015);
        box-shadow: 0 16px 30px rgba(15, 23, 42, 0.14);
    }
    @keyframes cardFadeIn {
        0% { opacity: 0; transform: translateY(10px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    @keyframes messageSlideIn {
        0% { opacity: 0; transform: translateY(8px); }
        100% { opacity: 1; transform: translateY(0); }
    }
</style>
""", unsafe_allow_html=True)

# 1. 初始化 Session State (状态管理)
if "messages" not in st.session_state:
    st.session_state.messages = []
if "rag_engine" not in st.session_state:
    st.session_state.rag_engine = None
if "agent" not in st.session_state:
    st.session_state.agent = None
if "current_runtime_signature" not in st.session_state:
    st.session_state.current_runtime_signature = None
if "vip_authenticated" not in st.session_state:
    st.session_state.vip_authenticated = False
if "vip_username" not in st.session_state:
    st.session_state.vip_username = ""
if "vip_profile" not in st.session_state:
    st.session_state.vip_profile = None
if "applied_config" not in st.session_state:
    st.session_state.applied_config = None
if "selected_project_id" not in st.session_state:
    st.session_state.selected_project_id = None
if "pending_chat_image_path" not in st.session_state:
    st.session_state.pending_chat_image_path = None
if "pending_chat_image_name" not in st.session_state:
    st.session_state.pending_chat_image_name = ""
if "auth_mode" not in st.session_state:
    st.session_state.auth_mode = "手动输入"

# 2. 侧边栏：API Key 和 文件上传
with st.sidebar:
    st.title("⚙️ 配置与控制台")

    auth_mode = st.radio("认证方式", ["手动输入", "VIP登录"], key="auth_mode", horizontal=True)

    selected_llm_model = ""
    selected_embedding_model = ""
    effective_llm_api_key = ""
    effective_llm_base_url = DEFAULT_LLM_BASE_URL
    effective_embedding_api_key = ""
    effective_embedding_base_url = DEFAULT_EMBEDDING_BASE_URL

    if auth_mode == "手动输入":
        selected_llm_model = st.selectbox("LLM 模型", options=SUPPORTED_LLM_MODELS, index=0, key="manual_llm_model")
        selected_embedding_model = st.selectbox("Embedding 模型", options=SUPPORTED_EMBEDDING_MODELS, index=0, key="manual_embedding_model")
        effective_llm_base_url = resolve_model_base_url(selected_llm_model, PRESET_LLM_BASE_URLS, DEFAULT_LLM_BASE_URL)
        effective_embedding_base_url = resolve_model_base_url(
            selected_embedding_model,
            PRESET_EMBEDDING_BASE_URLS,
            DEFAULT_EMBEDDING_BASE_URL
        )
        effective_llm_api_key = st.text_input("LLM API Key", type="password")
        effective_embedding_api_key = st.text_input("Embedding API Key", type="password")
        st.session_state.vip_authenticated = False
        st.session_state.vip_username = ""
        st.session_state.vip_profile = None
    else:
        users = load_vip_config(VIP_CONFIG_PATH)
        username = st.text_input("VIP用户名", value=st.session_state.vip_username)
        password = st.text_input("VIP密码", type="password")
        login_col, logout_col = st.columns(2)
        if login_col.button("VIP登录"):
            user = users.get(username)
            if verify_vip_user(user, password):
                st.session_state.vip_authenticated = True
                st.session_state.vip_username = username
                st.session_state.vip_profile = user
                st.success("VIP登录成功。")
            else:
                st.error("用户名或密码错误。")
        if logout_col.button("退出VIP"):
            st.session_state.vip_authenticated = False
            st.session_state.vip_username = ""
            st.session_state.vip_profile = None
        if st.session_state.vip_authenticated and st.session_state.vip_profile:
            profile = st.session_state.vip_profile
            st.caption(f"当前VIP：{st.session_state.vip_username}")
            llm_pool, embedding_pool = resolve_vip_model_pools(profile)
            llm_options = list(llm_pool.keys())
            embedding_options = list(embedding_pool.keys())
            if llm_options:
                selected_llm_model = st.selectbox("LLM 模型", options=llm_options, index=0, key="vip_llm_model")
                selected_llm_conf = llm_pool.get(selected_llm_model, {})
                effective_llm_api_key = selected_llm_conf.get("api_key", "")
                effective_llm_base_url = selected_llm_conf.get("base_url") or resolve_model_base_url(
                    selected_llm_model,
                    PRESET_LLM_BASE_URLS,
                    DEFAULT_LLM_BASE_URL
                )
            else:
                st.warning("当前 VIP 账号未配置可用 LLM 模型。")
            if embedding_options:
                default_embedding_index = 0
                preferred_embedding = profile.get("embedding_model", "")
                if preferred_embedding in embedding_options:
                    default_embedding_index = embedding_options.index(preferred_embedding)
                selected_embedding_model = st.selectbox(
                    "Embedding 模型",
                    options=embedding_options,
                    index=default_embedding_index,
                    key="vip_embedding_model"
                )
                selected_embedding_conf = embedding_pool.get(selected_embedding_model, {})
                effective_embedding_api_key = selected_embedding_conf.get("api_key", "")
                effective_embedding_base_url = selected_embedding_conf.get("base_url") or resolve_model_base_url(
                    selected_embedding_model,
                    PRESET_EMBEDDING_BASE_URLS,
                    DEFAULT_EMBEDDING_BASE_URL
                )
            else:
                st.warning("当前 VIP 账号未配置可用 Embedding 模型。")
        else:
            st.warning("请先完成VIP登录。")
            # st.stop() <-- REMOVED GLOBAL STOP

    pending_config = (
        effective_llm_base_url,
        selected_llm_model,
        selected_embedding_model,
        effective_llm_api_key,
        effective_embedding_base_url,
        effective_embedding_api_key
    )

    if not effective_llm_api_key:
        if auth_mode == "VIP登录":
            if st.session_state.vip_authenticated:
                st.warning(f"请在 VIP 配置中填写 LLM Key：llm_models.{selected_llm_model}.api_key。")
        else:
            st.warning("请先输入 LLM API Key。")
    if not effective_embedding_api_key:
        if auth_mode == "VIP登录":
            if st.session_state.vip_authenticated:
                st.warning(f"请在 VIP 配置中填写 Embedding Key：embedding_models.{selected_embedding_model}.api_key。")
        else:
            st.warning("请先输入 Embedding API Key。")
        # st.stop()  <-- REMOVED GLOBAL STOP

    if st.button("Apply 配置"):
        try:
            st.session_state.rag_engine = RAGEngine(
                effective_embedding_api_key,
                effective_embedding_base_url,
                selected_embedding_model
            )
            st.session_state.agent = DocumentAgent(
                effective_llm_api_key,
                st.session_state.rag_engine,
                effective_llm_base_url,
                selected_llm_model
            )
            st.session_state.current_runtime_signature = pending_config
            st.session_state.applied_config = pending_config
            st.success("配置已生效。")
        except Exception as e:
            st.error(f"引擎初始化失败: {e}")
            st.stop()

    if st.session_state.current_runtime_signature != pending_config:
        st.info("检测到配置变更，请点击 Apply 配置 生效。")

    if not st.session_state.agent or not st.session_state.rag_engine:
        if effective_llm_api_key and effective_embedding_api_key:
             st.warning("请先点击 Apply 配置 初始化引擎。")
        # st.stop() <-- REMOVED GLOBAL STOP

    st.markdown("---")
    st.subheader("📁 文档管理")
    uploaded_files = st.file_uploader(
        "上传 PDF 文档", 
        type=["pdf"], 
        accept_multiple_files=True,
        help="上传文档后，Agent 将自动对其进行解析和向量化。"
    )
    
    if uploaded_files:
        if not st.session_state.rag_engine:
             st.error("请先配置并初始化引擎（Apply 配置）以使用解析功能。")
        elif st.button("开始解析文档"):
            with st.spinner("正在处理文档..."):
                for uploaded_file in uploaded_files:
                    # 将上传的文件转为 BytesIO
                    file_bytes = BytesIO(uploaded_file.read())
                    # 调用 RAG 引擎处理
                    result = st.session_state.rag_engine.process_file(file_bytes, uploaded_file.name)
                    st.success(result)
    
    st.markdown("---")
    if st.session_state.rag_engine:
        usage = st.session_state.rag_engine.get_embedding_usage()
        st.subheader("📊 Embedding Token统计")
        st.caption(
            f"本次上传：输入 {usage['last']['input_tokens']}，总计 {usage['last']['total_tokens']} | "
            f"累计：输入 {usage['total']['input_tokens']}，总计 {usage['total']['total_tokens']}"
        )
        st.markdown("---")
        if st.button("🗑️ 清空知识库"):
            st.session_state.rag_engine.clear_db()
            st.success("知识库已重置。")

tab_projects, tab_chat = st.tabs(["🧪 项目介绍", "🤖 文档问答"])
chat_ready = bool(effective_llm_api_key and st.session_state.agent)
with tab_projects:
    render_projects_tab(PROJECT_CATALOG_DIR, PROJECT_INDEX_FILE, PROJECTS_DIR)
with tab_chat:
    render_chat_tab(chat_ready, CHAT_UPLOAD_DIR)

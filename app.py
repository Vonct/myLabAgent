import os
from pathlib import Path

import streamlit as st

from core.runtime import init_session_state
from core.session_store import SessionStore
from ui_tabs.chat_tab import render_chat_tab
from ui_tabs.licenses_tab import render_licenses_tab
from ui_tabs.projects_tab import render_projects_tab
from ui_tabs.sidebar import render_sidebar

PROJECT_ROOT = Path(__file__).resolve().parent
VIP_CONFIG_PATH = PROJECT_ROOT / "vip_config.json"
SUPPORTED_LLM_MODELS = ["qwen3.5-plus", "MiniMax-M2.5"]
SUPPORTED_EMBEDDING_MODELS = ["text-embedding-v4"]
MODEL_CAPABILITIES = {
    "qwen3.5-plus": {"supports_image_input": True, "supports_thinking": True},
    "MiniMax-M2.5": {"supports_image_input": False, "supports_thinking": False},
    "kimi-k2.5": {"supports_image_input": True, "supports_thinking": True},
}
DEFAULT_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
PRESET_LLM_BASE_URLS = {
    "qwen3.5-plus": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "MiniMax-M2.5": "https://api.minimaxi.com/v1",
    "kimi-k2.5": "https://api.moonshot.cn/v1",
}
PRESET_EMBEDDING_BASE_URLS = {
    "text-embedding-v4": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}
PROJECT_CATALOG_DIR = PROJECT_ROOT / "project_catalog"
PROJECTS_DIR = PROJECT_CATALOG_DIR / "projects"
PROJECT_INDEX_FILE = PROJECT_CATALOG_DIR / "index.json"
LICENSE_CATALOG_DIR = PROJECT_ROOT / "license_catalog"
LICENSES_DIR = LICENSE_CATALOG_DIR / "licenses"
LICENSE_INDEX_FILE = LICENSE_CATALOG_DIR / "index.json"
CHAT_UPLOAD_DIR = PROJECT_ROOT / "uploads" / "chat_images"
SESSION_STORE = SessionStore(PROJECT_ROOT / "app_data" / "sessions")

st.set_page_config(
    page_title="LabAgent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
html, body, [data-testid="stAppViewContainer"] {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    background: linear-gradient(180deg, #f6f8fb 0%, #ffffff 40%);
    color: #1d1d1f;
}
[data-testid="stSidebar"] {
    background-color: rgba(245, 245, 247, 0.92) !important;
    backdrop-filter: blur(20px);
    border-right: 1px solid rgba(0, 0, 0, 0.08);
}
.stChatMessage {
    border-radius: 18px !important;
    padding: 12px 16px !important;
    margin-bottom: 12px !important;
}
[data-testid="stChatMessageUser"] {
    background-color: #007aff !important;
    color: white !important;
}
[data-testid="stChatMessageAssistant"] {
    background-color: #f2f2f7 !important;
}
.stButton button {
    border-radius: 12px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

init_session_state(SESSION_STORE)
sidebar_state = render_sidebar(
    VIP_CONFIG_PATH,
    MODEL_CAPABILITIES,
    SUPPORTED_LLM_MODELS,
    SUPPORTED_EMBEDDING_MODELS,
    PRESET_LLM_BASE_URLS,
    DEFAULT_LLM_BASE_URL,
    PRESET_EMBEDDING_BASE_URLS,
    DEFAULT_EMBEDDING_BASE_URL,
    PROJECT_ROOT,
)

has_amap_api_key = bool(os.environ.get("AMAP_MAPS_API_KEY", "").strip())
tab_projects, tab_licenses, tab_chat = st.tabs(["🚀 项目介绍", "📋 License 看板", "🤖 LabAgent"])

with tab_projects:
    render_projects_tab(PROJECT_CATALOG_DIR, PROJECT_INDEX_FILE, PROJECTS_DIR)
with tab_licenses:
    render_licenses_tab(LICENSE_CATALOG_DIR, LICENSE_INDEX_FILE, LICENSES_DIR)
with tab_chat:
    render_chat_tab(
        sidebar_state["chat_ready"],
        CHAT_UPLOAD_DIR,
        supports_image_input=sidebar_state["supports_image_input"],
        supports_thinking=sidebar_state["supports_thinking"],
        has_amap_api_key=has_amap_api_key,
        session_store=SESSION_STORE,
    )

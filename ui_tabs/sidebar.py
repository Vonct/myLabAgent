from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import streamlit as st

from core.runtime import (
    load_vip_config,
    resolve_llm_capabilities,
    resolve_model_base_url,
    resolve_vip_model_pools,
    verify_vip_user,
)
from services.chat_service import build_agent


def render_sidebar(
    vip_config_path: Path,
    model_capabilities: dict,
    supported_llm_models: list[str],
    supported_embedding_models: list[str],
    preset_llm_base_urls: dict,
    default_llm_base_url: str,
    preset_embedding_base_urls: dict,
    default_embedding_base_url: str,
    project_root: Path,
):
    with st.sidebar:
        st.title("配置与控制台")

        auth_mode = st.radio("认证方式", ["手动输入", "VIP登录"], key="auth_mode", horizontal=True)

        selected_llm_model = ""
        selected_embedding_model = ""
        selected_llm_capabilities = {"supports_image_input": False, "supports_thinking": False}
        selected_llm_extra_body_for_thinking = None
        effective_llm_api_key = ""
        effective_llm_base_url = default_llm_base_url
        effective_embedding_api_key = ""
        effective_embedding_base_url = default_embedding_base_url

        if auth_mode == "手动输入":
            selected_llm_model = st.selectbox("LLM 模型", options=supported_llm_models, index=0, key="manual_llm_model")
            selected_embedding_model = st.selectbox(
                "Embedding 模型",
                options=supported_embedding_models,
                index=0,
                key="manual_embedding_model",
            )
            selected_llm_capabilities = resolve_llm_capabilities(selected_llm_model, model_capabilities)
            effective_llm_base_url = resolve_model_base_url(selected_llm_model, preset_llm_base_urls, default_llm_base_url)
            effective_embedding_base_url = resolve_model_base_url(
                selected_embedding_model,
                preset_embedding_base_urls,
                default_embedding_base_url,
            )
            effective_llm_api_key = st.text_input("LLM API Key", type="password")
            effective_embedding_api_key = st.text_input("Embedding API Key", type="password")
            st.session_state.vip_authenticated = False
            st.session_state.vip_username = ""
            st.session_state.vip_profile = None
        else:
            users = load_vip_config(vip_config_path)
            username = st.text_input("VIP 用户名", value=st.session_state.vip_username)
            password = st.text_input("VIP 密码", type="password")
            login_col, logout_col = st.columns(2)
            if login_col.button("VIP 登录"):
                user = users.get(username)
                if verify_vip_user(user, password):
                    st.session_state.vip_authenticated = True
                    st.session_state.vip_username = username
                    st.session_state.vip_profile = user
                    st.success("VIP 登录成功。")
                else:
                    st.error("用户名或密码错误。")
            if logout_col.button("退出 VIP"):
                st.session_state.vip_authenticated = False
                st.session_state.vip_username = ""
                st.session_state.vip_profile = None

            if st.session_state.vip_authenticated and st.session_state.vip_profile:
                profile = st.session_state.vip_profile
                st.caption(f"当前 VIP：{st.session_state.vip_username}")
                llm_pool, embedding_pool = resolve_vip_model_pools(
                    profile,
                    model_capabilities,
                    preset_llm_base_urls,
                    default_llm_base_url,
                    preset_embedding_base_urls,
                    default_embedding_base_url,
                )
                llm_options = list(llm_pool.keys())
                embedding_options = list(embedding_pool.keys())

                if llm_options:
                    selected_llm_model = st.selectbox("LLM 模型", options=llm_options, index=0, key="vip_llm_model")
                    selected_llm_conf = llm_pool.get(selected_llm_model, {})
                    selected_llm_capabilities = resolve_llm_capabilities(
                        selected_llm_model,
                        model_capabilities,
                        selected_llm_conf,
                    )
                    selected_llm_extra_body_for_thinking = selected_llm_conf.get("extra_body_forThinking")
                    effective_llm_api_key = selected_llm_conf.get("api_key", "")
                    effective_llm_base_url = selected_llm_conf.get("base_url") or resolve_model_base_url(
                        selected_llm_model,
                        preset_llm_base_urls,
                        default_llm_base_url,
                    )
                else:
                    st.warning("当前 VIP 账号没有可用的 LLM 模型。")

                if embedding_options:
                    default_embedding_index = 0
                    preferred_embedding = profile.get("embedding_model", "")
                    if preferred_embedding in embedding_options:
                        default_embedding_index = embedding_options.index(preferred_embedding)
                    selected_embedding_model = st.selectbox(
                        "Embedding 模型",
                        options=embedding_options,
                        index=default_embedding_index,
                        key="vip_embedding_model",
                    )
                    selected_embedding_conf = embedding_pool.get(selected_embedding_model, {})
                    effective_embedding_api_key = selected_embedding_conf.get("api_key", "")
                    effective_embedding_base_url = selected_embedding_conf.get("base_url") or resolve_model_base_url(
                        selected_embedding_model,
                        preset_embedding_base_urls,
                        default_embedding_base_url,
                    )
                else:
                    st.warning("当前 VIP 账号没有可用的 Embedding 模型。")
            else:
                st.warning("请先完成 VIP 登录。")

        pending_config = (
            effective_llm_base_url,
            selected_llm_model,
            selected_embedding_model,
            effective_llm_api_key,
            json.dumps(selected_llm_extra_body_for_thinking, ensure_ascii=False, sort_keys=True)
            if isinstance(selected_llm_extra_body_for_thinking, dict)
            else "",
            effective_embedding_base_url,
            effective_embedding_api_key,
        )

        if not effective_llm_api_key:
            st.warning("请先配置 LLM API Key。")
        if not effective_embedding_api_key:
            st.warning("请先配置 Embedding API Key。")

        if st.button("应用配置"):
            try:
                rag_engine, agent = build_agent(
                    effective_llm_api_key,
                    effective_llm_base_url,
                    selected_llm_model,
                    selected_llm_extra_body_for_thinking,
                    effective_embedding_api_key,
                    effective_embedding_base_url,
                    selected_embedding_model,
                    project_root,
                )
                st.session_state.rag_engine = rag_engine
                st.session_state.agent = agent
                st.session_state.current_runtime_signature = pending_config
                st.session_state.applied_config = pending_config
                st.success("配置已生效。")
            except Exception as exc:
                st.error(f"引擎初始化失败：{exc}")
                st.stop()

        if st.session_state.current_runtime_signature != pending_config:
            st.info("检测到配置变更，请点击“应用配置”使其生效。")

        if not st.session_state.agent or not st.session_state.rag_engine:
            if effective_llm_api_key and effective_embedding_api_key:
                st.warning("请先点击“应用配置”初始化引擎。")

        st.markdown("---")
        st.subheader("文档管理")
        uploaded_files = st.file_uploader(
            "上传文档",
            type=["pdf", "txt", "md", "docx"],
            accept_multiple_files=True,
            help="支持 PDF、TXT、Markdown、DOCX，上传后会进入知识库并完成向量化。",
        )

        if uploaded_files:
            if not st.session_state.rag_engine:
                st.error("请先应用配置后再解析文档。")
            elif st.button("开始解析文档"):
                with st.spinner("正在处理文档..."):
                    for uploaded_file in uploaded_files:
                        file_bytes = BytesIO(uploaded_file.read())
                        result = st.session_state.rag_engine.process_file(file_bytes, uploaded_file.name)
                        if result.startswith("[ERROR]"):
                            st.error(result)
                        else:
                            st.success(result)

        st.markdown("---")
        if st.session_state.rag_engine:
            usage = st.session_state.rag_engine.get_embedding_usage()
            backend = getattr(st.session_state.rag_engine, "backend", "unknown")
            backend_init_error = getattr(st.session_state.rag_engine, "backend_init_error", "")
            backend_runtime_error = getattr(st.session_state.rag_engine, "backend_runtime_error", "")
            st.subheader("Embedding Token 统计")
            st.caption(
                f"本次上传：输入 {usage['last']['input_tokens']}，总计 {usage['last']['total_tokens']} | "
                f"累计：输入 {usage['total']['input_tokens']}，总计 {usage['total']['total_tokens']}"
            )
            st.caption(f"RAG backend: {backend}")
            if backend == "memory" and backend_init_error:
                st.caption(f"RAG init fallback: {backend_init_error}")
            if backend_runtime_error:
                st.caption(f"RAG runtime fallback: {backend_runtime_error}")
            st.caption(f"RAG log: {project_root / 'app_data' / 'rag_engine.log'}")
            st.caption(f"会话 ID：{st.session_state.session_id}")
            if st.session_state.task_id:
                st.caption(f"最近任务 ID：{st.session_state.task_id}")
            st.markdown("---")
            if st.button("清空知识库"):
                st.session_state.rag_engine.clear_db()
                st.success("知识库已重置。")

    chat_ready = bool(effective_llm_api_key and st.session_state.agent)
    return {
        "chat_ready": chat_ready,
        "supports_image_input": selected_llm_capabilities["supports_image_input"],
        "supports_thinking": selected_llm_capabilities["supports_thinking"],
    }

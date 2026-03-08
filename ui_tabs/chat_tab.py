import hashlib
from pathlib import Path

import streamlit as st


def render_chat_tab(chat_ready: bool, chat_upload_dir: Path):
    st.title("🤖 智能文档问答 Agent")
    st.caption("基于 OpenAI SDK + Qwen 兼容接口实现 | 支持 RAG、Tool Use、多轮对话")
    if not chat_ready:
        st.info("💡 请先在侧边栏配置 API Key 并点击 Apply 初始化，即可开始对话。")
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0
    
    message_container = st.container()
    with message_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message.get("display_content", message["content"]))
                image_path = message.get("image_path")
                if image_path and Path(image_path).exists():
                    with st.expander("🖼️ 查看图片附件", expanded=False):
                        st.image(image_path, width="stretch")

    attachment_col, toggle_col = st.columns([5, 1])
    with toggle_col:
        reasoning_mode = st.toggle("🧠 深度思考", value=st.session_state.get("reasoning_mode", False), key="reasoning_mode_toggle")
        st.session_state.reasoning_mode = reasoning_mode
    with attachment_col:
        with st.expander("📎 添加图片附件", expanded=False):
            uploaded_chat_image = st.file_uploader(
                "上传图片",
                type=["png", "jpg", "jpeg", "bmp", "webp"],
                accept_multiple_files=False,
                key=f"chat_image_uploader_{st.session_state.uploader_key}",
                label_visibility="collapsed",
            )
            if uploaded_chat_image is not None:
                chat_upload_dir.mkdir(parents=True, exist_ok=True)
                image_bytes = uploaded_chat_image.getvalue()
                suffix = Path(uploaded_chat_image.name).suffix.lower() or ".png"
                image_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
                saved_image_path = chat_upload_dir / f"{image_hash}{suffix}"
                if not saved_image_path.exists():
                    with open(saved_image_path, "wb") as fw:
                        fw.write(image_bytes)
                st.session_state.pending_chat_image_path = str(saved_image_path)
                st.session_state.pending_chat_image_name = uploaded_chat_image.name
    active_image_path = st.session_state.pending_chat_image_path
    if active_image_path and Path(active_image_path).exists():
        with st.expander("🖼️ 待发送图片预览", expanded=True):
            col_img, col_btn = st.columns([1, 4])
            with col_img:
                st.image(active_image_path, width="stretch")
            with col_btn:
                st.caption(f"文件名: {st.session_state.pending_chat_image_name}")
                def remove_image():
                    st.session_state.pending_chat_image_path = None
                    st.session_state.pending_chat_image_name = ""
                    st.session_state.uploader_key += 1
                
                st.button("❌ 移除图片", key="remove_pending_chat_image", on_click=remove_image)
    chat_placeholder = "请输入您关于文档的问题..." if chat_ready else "请先完成配置后再开始提问"
    if prompt := st.chat_input(chat_placeholder, disabled=not chat_ready):
        send_image_path = st.session_state.pending_chat_image_path
        user_content_for_model = prompt
        # 如果上传了图片
        if send_image_path and Path(send_image_path).exists():
            
            user_content_for_model = (
                f"{prompt}\n\n"
                f"用户附带了一张图片，图片路径为：{send_image_path}\n"
                "如果问题与图片相关，请结合图片内容进行回答。"
            )
        st.session_state.messages.append(
            {
                "role": "user",
                "content": user_content_for_model,
                "display_content": prompt,
                "image_path": send_image_path,
            }
        )
        with message_container:
            with st.chat_message("user"):
                st.markdown(prompt)
                if send_image_path and Path(send_image_path).exists():
                    with st.expander("🖼️ 查看图片附件", expanded=False):
                        st.image(send_image_path, width="stretch")
            st.session_state.pending_chat_image_path = None
            st.session_state.pending_chat_image_name = ""
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                thought_container = st.status("🤔 Agent 正在思考...", expanded=True)
                try:
                    # 获取当前思考模式状态
                    is_reasoning_mode = st.session_state.get("reasoning_mode", False)
                    response_generator = st.session_state.agent.chat(st.session_state.messages, reasoning_mode=is_reasoning_mode)
                    for chunk in response_generator:
                        chunk_type = chunk.get("type")
                        if chunk_type == "thought":
                            thought_container.write(chunk["content"])
                        elif chunk_type == "reasoning":
                            thought_container.markdown(f"**🧠 深度思考过程**:\n\n{chunk['content']}")
                        elif chunk_type == "tool_exec":
                            thought_container.write(f"🔧 **调用工具**: `{chunk['tool']}`")
                            thought_container.code(f"Input: {chunk['input']}", language="json")
                        elif chunk_type == "tool_result":
                            thought_container.write("✅ **工具返回结果** (部分展示):")
                            preview = chunk["output"][:200] + "..." if len(chunk["output"]) > 200 else chunk["output"]
                            thought_container.text(preview)
                            thought_container.update(label="检索完成，正在生成回答...", state="running")
                        elif chunk_type == "answer_chunk":
                            full_response += chunk["content"]
                            message_placeholder.markdown(full_response + "▌")
                        elif chunk_type == "error":
                            thought_container.update(label="发生错误", state="error")
                            st.error(f"Agent 遇到问题: {chunk['content']}")
                    thought_container.update(label="处理完成", state="complete", expanded=False)
                    message_placeholder.markdown(full_response)
                    st.session_state.messages.append({"role": "assistant", "content": full_response})
                except Exception as e:
                    st.error(f"系统错误: {e}")

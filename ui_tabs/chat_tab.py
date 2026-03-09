import base64
import hashlib
import mimetypes
from pathlib import Path

import streamlit as st

from services.chat_service import start_task


def _image_path_to_data_url(image_path: str):
    path_obj = Path(image_path)
    if not path_obj.exists():
        return None
    mime_type, _ = mimetypes.guess_type(str(path_obj))
    mime_type = mime_type or "image/png"
    with open(path_obj, "rb") as fr:
        encoded = base64.b64encode(fr.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def render_chat_tab(chat_ready: bool, chat_upload_dir: Path, supports_image_input: bool, supports_thinking: bool, has_amap_api_key: bool, session_store):
    st.title("LabChat Agent")
    st.caption("基于 OpenAI SDK 兼容接口实现，支持 RAG、工具调用、多轮对话与任务持久化。")
    if not chat_ready:
        st.info("请先在左侧配置 API Key 并点击“应用配置”，然后再开始对话。")
    if not has_amap_api_key:
        st.warning("未检测到环境变量 AMAP_MAPS_API_KEY，天气工具暂不可用。")

    message_container = st.container()
    with message_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message.get("display_content", message["content"]))
                image_path = message.get("image_path")
                if image_path and Path(image_path).exists():
                    with st.expander("查看图片附件", expanded=False):
                        st.image(image_path, width="stretch")

    attachment_col, toggle_col = st.columns([5, 1])
    with toggle_col:
        if not supports_thinking:
            st.session_state.reasoning_mode = False
        reasoning_mode = st.toggle(
            "🧠 深度思考",
            value=st.session_state.get("reasoning_mode", False),
            key="reasoning_mode_toggle",
            disabled=not supports_thinking,
        )
        st.session_state.reasoning_mode = reasoning_mode
    with attachment_col:
        if supports_image_input:
            with st.expander("添加图片附件", expanded=False):
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
        else:
            st.session_state.pending_chat_image_path = None
            st.session_state.pending_chat_image_name = ""
            st.caption("当前模型不支持图片输入。")

    active_image_path = st.session_state.pending_chat_image_path
    if active_image_path and Path(active_image_path).exists():
        with st.expander("待发送图片预览", expanded=True):
            col_img, col_btn = st.columns([1, 4])
            with col_img:
                st.image(active_image_path, width="stretch")
            with col_btn:
                st.caption(f"文件名：{st.session_state.pending_chat_image_name}")

                def remove_image():
                    st.session_state.pending_chat_image_path = None
                    st.session_state.pending_chat_image_name = ""
                    st.session_state.uploader_key += 1

                st.button("移除图片", key="remove_pending_chat_image", on_click=remove_image)

    chat_placeholder = "请输入你关于文档或实验室资料的问题..." if chat_ready else "请先完成配置后再开始提问。"
    if prompt := st.chat_input(chat_placeholder, disabled=not chat_ready):
        task_id = start_task(session_store, prompt)
        send_image_path = st.session_state.pending_chat_image_path
        user_content_for_model = prompt
        if send_image_path and Path(send_image_path).exists() and supports_image_input:
            image_data_url = _image_path_to_data_url(send_image_path)
            if image_data_url:
                user_content_for_model = [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": prompt},
                ]
        user_message = {
            "role": "user",
            "content": user_content_for_model,
            "display_content": prompt,
            "image_path": send_image_path,
        }
        st.session_state.messages.append(user_message)
        session_store.append_message(st.session_state.session_id, user_message)

        with message_container:
            with st.chat_message("user"):
                st.markdown(prompt)
                if send_image_path and Path(send_image_path).exists():
                    with st.expander("查看图片附件", expanded=False):
                        st.image(send_image_path, width="stretch")
            st.session_state.pending_chat_image_path = None
            st.session_state.pending_chat_image_name = ""
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                thought_container = st.status("Agent 正在处理...", expanded=True)
                try:
                    is_reasoning_mode = st.session_state.get("reasoning_mode", False) and supports_thinking
                    response_generator = st.session_state.agent.chat(
                        st.session_state.messages,
                        reasoning_mode=is_reasoning_mode,
                        supports_thinking=supports_thinking,
                        session_store=session_store,
                        session_id=st.session_state.session_id,
                        task_id=task_id,
                    )
                    for chunk in response_generator:
                        chunk_type = chunk.get("type")
                        if chunk_type == "thought":
                            thought_container.write(chunk["content"])
                        elif chunk_type == "reasoning":
                            thought_container.markdown(f"**深度思考过程：**\n\n{chunk['content']}")
                        elif chunk_type == "tool_exec":
                            thought_container.write(f"调用工具：`{chunk['tool']}`")
                            thought_container.code(chunk["input"], language="json")
                        elif chunk_type == "tool_result":
                            preview = chunk["output"][:200] + "..." if len(chunk["output"]) > 200 else chunk["output"]
                            thought_container.write("工具返回结果：")
                            thought_container.text(preview)
                            thought_container.update(label="工具执行完成，正在生成答案...", state="running")
                        elif chunk_type == "answer_chunk":
                            full_response += chunk["content"]
                            message_placeholder.markdown(full_response + "▌")
                        elif chunk_type == "error":
                            thought_container.update(label="处理失败", state="error")
                            session_store.finish_task(st.session_state.session_id, task_id, chunk["content"], status="failed")
                            st.error(f"Agent 遇到问题: {chunk['content']}")
                    thought_container.update(label="处理完成", state="complete", expanded=False)
                    message_placeholder.markdown(full_response)
                    assistant_message = {"role": "assistant", "content": full_response}
                    st.session_state.messages.append(assistant_message)
                    session_store.append_message(st.session_state.session_id, assistant_message)
                    session_store.finish_task(st.session_state.session_id, task_id, full_response)
                except Exception as e:
                    session_store.finish_task(st.session_state.session_id, task_id, str(e), status="failed")
                    st.error(f"系统错误: {e}")

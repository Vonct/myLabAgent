import base64
import hashlib
import mimetypes
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from services.chat_service import start_task


def _image_path_to_data_url(image_path: str):
    path_obj = Path(image_path)
    if not path_obj.exists():
        return None
    mime_type, _ = mimetypes.guess_type(str(path_obj))
    mime_type = mime_type or 'image/png'
    with open(path_obj, 'rb') as fr:
        encoded = base64.b64encode(fr.read()).decode('utf-8')
    return f'data:{mime_type};base64,{encoded}'


def _inject_paste_image_bridge(chat_input_key: str):
    components.html(
        f"""
        <script>
        (() => {{
          const parentWindow = window.parent;
          const bridgeKey = 'labagent-paste-bridge-{chat_input_key}';
          if (parentWindow[bridgeKey]) return;
          parentWindow[bridgeKey] = true;

          const doc = parentWindow.document;

          const isWithinChatInput = (node) => {{
            if (!node || !node.closest) return false;
            return Boolean(
              node.closest('.st-key-{chat_input_key}') ||
              node.closest('[data-testid="stChatInput"]')
            );
          }};

          const findFileInput = () => {{
            const selectors = [
              '.st-key-{chat_input_key} input[type="file"]',
              '[data-testid="stChatInput"] input[type="file"]',
              'input[type="file"][accept*="png"]',
              'input[type="file"][accept*="jpg"]',
              'input[type="file"][accept*="jpeg"]',
              'input[type="file"][accept*="webp"]',
              'input[type="file"][accept*="bmp"]'
            ];
            const found = [];
            selectors.forEach((selector) => {{
              doc.querySelectorAll(selector).forEach((node) => found.push(node));
            }});
            return found.filter((node) => !node.disabled).at(-1) || null;
          }};

          doc.addEventListener('paste', (event) => {{
            const active = doc.activeElement;
            const target = event.target;
            if (!isWithinChatInput(active) && !isWithinChatInput(target)) {{
              return;
            }};

            const items = Array.from(event.clipboardData?.items || []);
            const imageItem = items.find((item) => item.type && item.type.startsWith('image/'));
            if (!imageItem) return;

            const fileInput = findFileInput();
            if (!fileInput) return;

            const sourceFile = imageItem.getAsFile();
            if (!sourceFile) return;

            const extension = (sourceFile.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
            const pastedFile = new File(
              [sourceFile],
              `pasted-image-${{Date.now()}}.${{extension}}`,
              {{ type: sourceFile.type }}
            );

            const transfer = new DataTransfer();
            transfer.items.add(pastedFile);

            try {{
              fileInput.files = transfer.files;
            }} catch (error) {{
              console.warn('Failed to assign pasted image to file input', error);
              return;
            }}

            fileInput.dispatchEvent(new Event('input', {{ bubbles: true, composed: true }}));
            fileInput.dispatchEvent(new Event('change', {{ bubbles: true, composed: true }}));
            event.preventDefault();
          }}, true);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def _save_chat_image(uploaded_file, chat_upload_dir: Path) -> tuple[str, str]:
    chat_upload_dir.mkdir(parents=True, exist_ok=True)
    image_bytes = uploaded_file.getvalue()
    suffix = Path(uploaded_file.name).suffix.lower() or '.png'
    image_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
    saved_image_path = chat_upload_dir / f'{image_hash}{suffix}'
    if not saved_image_path.exists():
        with open(saved_image_path, 'wb') as fw:
            fw.write(image_bytes)
    return str(saved_image_path), uploaded_file.name


def _render_chat_toolbar(supports_image_input: bool, supports_thinking: bool) -> bool:
    if not supports_thinking:
        st.session_state.reasoning_mode = False

    left_col, right_col = st.columns([0.78, 0.22], vertical_alignment='center')
    with left_col:
        if supports_image_input:
            st.caption('支持点击附件，或先聚焦输入框后按 Ctrl+V 直接粘贴截图。')
        else:
            st.caption('当前模型不支持图片输入。')
    with right_col:
        reasoning_mode = st.toggle(
            '🧠 深度思考',
            value=st.session_state.get('reasoning_mode', False),
            key='reasoning_mode_toggle',
            disabled=not supports_thinking,
        )
    st.session_state.reasoning_mode = reasoning_mode
    return reasoning_mode


def render_chat_tab(
    chat_ready: bool,
    chat_upload_dir: Path,
    supports_image_input: bool,
    supports_thinking: bool,
    has_amap_api_key: bool,
    session_store,
):
    st.title('LabChat Agent')
    st.caption('基于 OpenAI SDK 兼容接口实现，支持 RAG、工具调用、多轮对话与任务持久化。')
    if not chat_ready:
        st.info('请先在左侧配置 API Key 并点击“应用配置”，然后再开始对话。')
    if not has_amap_api_key:
        st.warning('未检测到环境变量 AMAP_MAPS_API_KEY，天气工具暂不可用。')

    message_container = st.container()
    with message_container:
        for message in st.session_state.messages:
            with st.chat_message(message['role']):
                st.markdown(message.get('display_content', message['content']))
                image_path = message.get('image_path')
                if image_path and Path(image_path).exists():
                    with st.expander('查看图片附件', expanded=False):
                        st.image(image_path, width='stretch')

    chat_input_key = 'chat_input_main'
    _render_chat_toolbar(supports_image_input=supports_image_input, supports_thinking=supports_thinking)
    if supports_image_input:
        _inject_paste_image_bridge(chat_input_key)

    chat_placeholder = (
        '请输入你关于文档或实验室资料的问题...'
        if chat_ready
        else '请先完成配置后再开始提问。'
    )
    submission = st.chat_input(
        chat_placeholder,
        key=chat_input_key,
        accept_file=supports_image_input,
        file_type=['png', 'jpg', 'jpeg', 'bmp', 'webp'],
        disabled=not chat_ready,
    )
    if submission:
        if supports_image_input:
            prompt = submission.text
            uploaded_files = submission.files
        else:
            prompt = submission
            uploaded_files = []

        send_image_path = None
        send_image_name = ''
        if uploaded_files:
            send_image_path, send_image_name = _save_chat_image(uploaded_files[0], chat_upload_dir)

        user_content_for_model = prompt
        if send_image_path and Path(send_image_path).exists() and supports_image_input:
            image_data_url = _image_path_to_data_url(send_image_path)
            if image_data_url:
                user_content_for_model = [{'type': 'image_url', 'image_url': {'url': image_data_url}}]
                if prompt.strip():
                    user_content_for_model.append({'type': 'text', 'text': prompt})

        display_content = prompt.strip() or '（发送了一张图片）'
        task_prompt = prompt.strip() or f'[image] {send_image_name or Path(send_image_path).name}'
        task_id = start_task(session_store, task_prompt)
        user_message = {
            'role': 'user',
            'content': user_content_for_model,
            'display_content': display_content,
            'image_path': send_image_path,
        }
        st.session_state.messages.append(user_message)
        session_store.append_message(st.session_state.session_id, user_message)

        with message_container:
            with st.chat_message('user'):
                st.markdown(display_content)
                if send_image_path and Path(send_image_path).exists():
                    with st.expander('查看图片附件', expanded=False):
                        st.image(send_image_path, width='stretch')

            with st.chat_message('assistant'):
                message_placeholder = st.empty()
                full_response = ''
                thought_container = st.status('Agent 正在处理...', expanded=True)
                try:
                    is_reasoning_mode = st.session_state.get('reasoning_mode', False) and supports_thinking
                    response_generator = st.session_state.agent.chat(
                        st.session_state.messages,
                        reasoning_mode=is_reasoning_mode,
                        supports_thinking=supports_thinking,
                        session_store=session_store,
                        session_id=st.session_state.session_id,
                        task_id=task_id,
                    )
                    for chunk in response_generator:
                        chunk_type = chunk.get('type')
                        if chunk_type == 'thought':
                            thought_container.write(chunk['content'])
                        elif chunk_type == 'reasoning':
                            thought_container.markdown(f"**深度思考过程：**\n\n{chunk['content']}")
                        elif chunk_type == 'tool_exec':
                            thought_container.write(f"调用工具：`{chunk['tool']}`")
                            thought_container.code(chunk['input'], language='json')
                        elif chunk_type == 'tool_result':
                            preview = chunk['output'][:200] + '...' if len(chunk['output']) > 200 else chunk['output']
                            thought_container.write('工具返回结果：')
                            thought_container.text(preview)
                            thought_container.update(label='工具执行完成，正在生成答案...', state='running')
                        elif chunk_type == 'answer_chunk':
                            full_response += chunk['content']
                            message_placeholder.markdown(full_response + '▌')
                        elif chunk_type == 'error':
                            thought_container.update(label='处理失败', state='error')
                            session_store.finish_task(
                                st.session_state.session_id,
                                task_id,
                                chunk['content'],
                                status='failed',
                            )
                            st.error(f"Agent 遇到问题: {chunk['content']}")
                    thought_container.update(label='处理完成', state='complete', expanded=False)
                    message_placeholder.markdown(full_response)
                    assistant_message = {'role': 'assistant', 'content': full_response}
                    st.session_state.messages.append(assistant_message)
                    session_store.append_message(st.session_state.session_id, assistant_message)
                    session_store.finish_task(st.session_state.session_id, task_id, full_response)
                except Exception as e:
                    session_store.finish_task(st.session_state.session_id, task_id, str(e), status='failed')
                    st.error(f'系统错误: {e}')

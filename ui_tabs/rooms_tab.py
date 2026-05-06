from __future__ import annotations

import streamlit as st

from core.canonical_message import extract_message_text
from core.room_store import RoomStore
from services.room_service import BOT_NAME, build_room_agent_messages, mentions_bot, strip_bot_mention
from services.session_service import SessionService


def _render_room_message(message: dict) -> None:
    role = 'assistant' if message.get('role') == 'assistant' else 'user'
    name = str(message.get('name', '') or ('bot' if role == 'assistant' else 'user'))
    content = str(message.get('content', '') or '')
    with st.chat_message(role):
        st.caption(name)
        st.markdown(content or '（空消息）')


def _run_room_bot(
    *,
    room_store: RoomStore,
    room_id: str,
    trigger_message: dict,
    session_store,
    supports_thinking: bool,
) -> None:
    room = room_store.load_room(room_id)
    if room is None:
        st.error('Room 不存在。')
        return

    agent_session_id = room_store.ensure_agent_session(room_id, session_store)
    session_service = SessionService(session_store)
    active_prompt = strip_bot_mention(str(trigger_message.get('content', '') or '')) or str(trigger_message.get('content', '') or '')
    session_service.append_user_message_with_name(
        agent_session_id,
        active_prompt,
        name=str(trigger_message.get('name', '') or 'room_user'),
    )
    task = session_store.start_task(agent_session_id, active_prompt)
    agent_messages = build_room_agent_messages(room, trigger_message=trigger_message)

    full_response = ''
    assistant_payload = None
    errored = False
    status = st.status('Room bot 正在处理...', expanded=True)
    for event in st.session_state.agent.chat(
        agent_messages,
        reasoning_mode=st.session_state.get('reasoning_mode', False) and supports_thinking,
        supports_thinking=supports_thinking,
        session_store=session_store,
        session_id=agent_session_id,
        task_id=task.task_id,
    ):
        event_type = event.get('type')
        if event_type == 'thought':
            status.write(event.get('content', ''))
        elif event_type == 'tool_exec':
            status.write(f"调用工具：`{event.get('tool', '')}`")
            status.code(event.get('input', ''), language='json')
        elif event_type == 'tool_result':
            output = str(event.get('output', '') or '')
            status.text(output[:300] + ('...' if len(output) > 300 else ''))
        elif event_type == 'answer_chunk':
            full_response += str(event.get('content', '') or '')
        elif event_type == 'final_message':
            assistant_payload = event.get('content')
        elif event_type == 'error':
            errored = True
            full_response = str(event.get('content', '') or '')

    final_text = extract_message_text({'content': assistant_payload}) or full_response.strip()
    task_status = 'failed' if errored else 'completed'
    if assistant_payload is not None:
        session_service.append_assistant_message(agent_session_id, assistant_payload)
    elif final_text:
        session_service.append_assistant_message(agent_session_id, final_text)
    session_store.finish_task(agent_session_id, task.task_id, final_text, status=task_status)
    task_record = session_store.get_task(agent_session_id, task.task_id) or {}
    session_service.append_memory_card(
        agent_session_id,
        task_id=task.task_id,
        prompt=active_prompt,
        answer=final_text,
        tool_events=task_record.get('tool_events', []),
        has_image=False,
        status=task_status,
    )
    st.session_state.agent.record_long_term_memory(
        prompt=active_prompt,
        answer=final_text,
        tool_events=task_record.get('tool_events', []),
        session_id=agent_session_id,
        task_id=task.task_id,
        status=task_status,
    )
    room_store.append_message(
        room_id,
        role='assistant',
        name=BOT_NAME,
        content=final_text or '（模型没有返回可见文本）',
        mentions_bot=False,
    )
    status.update(label='Room bot 处理完成', state='complete', expanded=False)


def render_rooms_tab(
    *,
    chat_ready: bool,
    supports_thinking: bool,
    room_store: RoomStore,
    session_store,
) -> None:
    st.title('Room Chat')
    st.caption('普通消息只进入 room；包含 @bot 的消息会触发 Agent，并把最近 room 上下文作为参考材料。')

    rooms = room_store.list_rooms()
    create_col, pick_col = st.columns([0.35, 0.65], vertical_alignment='bottom')
    with create_col:
        new_room_name = st.text_input('新建 room', placeholder='例如：项目讨论室')
        if st.button('创建 room', disabled=not new_room_name.strip()):
            room = room_store.create_room(new_room_name)
            st.session_state.selected_room_id = room['room_id']
            st.rerun()

    if not rooms:
        room = room_store.create_room('General')
        st.session_state.selected_room_id = room['room_id']
        rooms = room_store.list_rooms()

    room_labels = [f"{room['name']} ({room['message_count']})" for room in rooms]
    room_ids = [room['room_id'] for room in rooms]
    selected_room_id = st.session_state.get('selected_room_id') or room_ids[0]
    selected_index = room_ids.index(selected_room_id) if selected_room_id in room_ids else 0
    with pick_col:
        selected_label = st.selectbox('进入 room', room_labels, index=selected_index)
        st.session_state.selected_room_id = room_ids[room_labels.index(selected_label)]

    room_id = st.session_state.selected_room_id
    room = room_store.load_room(room_id) or rooms[0]
    st.subheader(room.get('name', 'Room'))

    name_default = st.session_state.get('vip_username') or 'milan'
    display_name = st.text_input('你的聊天室昵称', value=st.session_state.get('room_display_name') or name_default)
    st.session_state.room_display_name = display_name.strip() or name_default

    for message in room.get('messages', [])[-80:]:
        if isinstance(message, dict):
            _render_room_message(message)

    if not chat_ready:
        st.info('左侧应用配置后，@bot 才会触发 Agent；普通 room 消息仍可记录。')

    submission = st.chat_input('发送 room 消息；输入 @bot 触发 Agent', key='room_chat_input')
    if not submission:
        return

    content = str(submission or '').strip()
    if not content:
        return

    trigger_bot = mentions_bot(content)
    user_message = room_store.append_message(
        room_id,
        role='user',
        name=st.session_state.room_display_name,
        content=content,
        mentions_bot=trigger_bot,
    )
    if trigger_bot and chat_ready and st.session_state.agent:
        _run_room_bot(
            room_store=room_store,
            room_id=room_id,
            trigger_message=user_message,
            session_store=session_store,
            supports_thinking=supports_thinking,
        )
    elif trigger_bot:
        st.warning('检测到 @bot，但 Agent 尚未初始化。')
    st.rerun()

import json
from datetime import date, datetime
from pathlib import Path

import streamlit as st


def _parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_software_licenses(index_file: Path, licenses_dir: Path):
    if not index_file.exists():
        return []
    with open(index_file, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    software_meta = index_data.get("softwares", []) if isinstance(index_data, dict) else []
    items = []
    for meta in software_meta:
        if not meta.get("enabled", True):
            continue
        software_id = meta.get("id")
        if not software_id:
            continue
        detail_file = licenses_dir / f"{software_id}.json"
        if not detail_file.exists():
            continue
        with open(detail_file, "r", encoding="utf-8") as df:
            detail = json.load(df)
        detail["display_order"] = meta.get("display_order", 9999)
        detail["category"] = meta.get("category", detail.get("category", "未分类"))
        detail["name"] = detail.get("name") or meta.get("name", software_id)
        items.append(detail)
    items.sort(key=lambda x: (x.get("display_order", 9999), x.get("name", "")))
    return items


def compute_license_status(licenses: list):
    today = date.today()
    valid_days = []
    for item in licenses or []:
        expired_raw = str(item.get("expired_date", "")).strip()
        expired_at = _parse_date(expired_raw)
        if expired_at is None:
            continue
        days_left = (expired_at - today).days
        if days_left >= 0:
            valid_days.append(days_left)
    if not valid_days:
        return "unavailable", "不可用", "#ef4444"
    if min(valid_days) <= 30:
        return "expiring", "即将到期", "#f59e0b"
    return "available", "可用", "#22c55e"


def render_status_badge(status_tuple):
    _, label, color = status_tuple
    st.markdown(
        f"""
<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;">
  <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{color};box-shadow:0 0 0 3px {color}33;"></span>
  <span style="font-size:12px;color:#374151;">{label}</span>
</div>
""",
        unsafe_allow_html=True,
    )


def render_licenses_tab(catalog_dir: Path, index_file: Path, licenses_dir: Path):
    col_title, col_action = st.columns([5, 1])
    with col_title:
        st.title("License 看板")
    with col_action:
        if st.button("刷新", key="refresh_licenses"):
            load_software_licenses.clear()
            st.rerun()
    st.caption("卡片显示软件 License 与到期时间，右上角状态灯表示当前可用性。")
    softwares = load_software_licenses(index_file, licenses_dir)
    if not softwares:
        st.info("未找到 License 目录数据，请先完善 license_catalog。")
        return

    cols = st.columns(2)
    for i, software in enumerate(softwares):
        with cols[i % 2]:
            with st.container(border=True, height=320):
                status_tuple = compute_license_status(software.get("licenses", []))
                row1_left, row1_right = st.columns([5, 2])
                with row1_left:
                    st.subheader(software.get("name", "未命名软件"))
                    st.caption(f"分类：{software.get('category', '未分类')}")
                with row1_right:
                    render_status_badge(status_tuple)

                body_left, body_right = st.columns([1, 3])
                with body_left:
                    logo = software.get("logo")
                    logo_path = catalog_dir / logo if logo else None
                    if logo_path and logo_path.exists():
                        st.image(str(logo_path), width=120)
                    else:
                        st.caption("待补充图标")
                with body_right:
                    summary = software.get("summary")
                    if summary:
                        st.write(summary)
                    st.markdown("**License 列表**")
                    licenses = software.get("licenses", [])
                    if not licenses:
                        st.caption("暂无 License 信息")
                    for lic in licenses:
                        lic_name = lic.get("license_name", "未命名 License")
                        expired_date = str(lic.get("expired_date", "未知"))
                        expired_at = _parse_date(expired_date)
                        if expired_at is None:
                            date_text = f"{expired_date}（日期格式无效）"
                        else:
                            date_text = expired_date
                        st.write(f"- {lic_name}")
                        st.caption(f"到期时间：{date_text}")

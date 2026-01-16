import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse

# --- 1. 初始化配置 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

# 固定目的地
DEST_SCHOOL = "东京都新宿区百人町2-24-12 (美都里慕)"
DEST_JUKU = "东京都荒川区西日暮里2-12-5 (尚艺舍)"

@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未找到 API KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 自动选择可用模型
    models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    target = "models/gemini-1.5-flash"
    return genai.GenerativeModel(target if target in models else models[0])

model = init_ai()

# --- 2. 核心逻辑 ---
def get_transit(origin, destination):
    prompt = f"日本交通分析 JSON：起点[{origin}]，终点[{destination}]。返回:{{'mins':整数,'yen':整数,'line':'简述'}}"
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group())
    except: return None

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器")

# 核心修复：如果字段名不匹配，强制重置缓存
if "houses" not in st.session_state:
    st.session_state.houses = []

with st.form("input_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    loc = col1.text_input("🏠 房源位置 (车站名)", placeholder="如: 西川口")
    rent = col2.number_input("💰 月租(円)", value=80000, step=5000)
    if st.form_submit_button("🚀 提交并分析"):
        if loc:
            with st.spinner(f"正在分析 {loc} 的通勤路径..."):
                s_data = get_transit(loc, DEST_SCHOOL)
                j_data = get_transit(loc, DEST_JUKU)
                if s_data and j_data:
                    st.session_state.houses.append({
                        "位置": loc, "房租": rent,
                        "学时": s_data['mins'], "学费": s_data['yen'],
                        "塾时": j_data['mins'], "塾费": j_data['yen'],
                        "路线": s_data['line']
                    })
                    st.rerun()

# --- 4. 报告展示 ---
if st.session_state.houses:
    st.subheader("📊 房源对比报告")
    for h in st.session_state.houses:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 1, 1])
            # 月通勤费 = (学校票价*10次 + 私塾票价*1次) * 4.33周
            m_transit = (h['学费'] * 10 + h['塾费'] * 1) * 4.33
            total = h['房租'] + m_transit + 60000 # 6万生活费基数
            
            with c1:
                st.markdown(f"### {h['位置']}房源")
                st.write(f"📉 **预估月总支出: {int(total):,} 円**")
                st.caption(f"线路概要: {h['路线']}")
            
            # 地图跳转按钮
            base_map = "https://www.google.com/maps/dir/?api=1&travelmode=transit"
            with c2:
                url_s = f"{base_map}&origin={urllib.parse.quote(h['位置'])}&destination={urllib.parse.quote(DEST_SCHOOL)}"
                st.link_button(f"🏫 学校 ({h['学时']}分)", url_s, use_container_width=True)
            with c3:
                url_j = f"{base_map}&origin={urllib.parse.quote(h['位置'])}&destination={urllib.parse.quote(DEST_JUKU)}"
                st.link_button(f"🎨 私塾 ({h['塾时']}分)", url_j, use_container_width=True)
    
    if st.button("🗑️ 清空所有数据"):
        st.session_state.houses = []
        st.rerun()

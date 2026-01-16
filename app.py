
import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse

# --- 1. 初始化配置 ---
# --- 1. 配置与 AI 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

# 固定目的地
@@ -18,8 +18,8 @@
        st.error("🔑 未找到 API KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 自动选择可用模型
    models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    # 优先选择 flash 模型以保证速度
    target = "models/gemini-1.5-flash"
    return genai.GenerativeModel(target if target in models else models[0])

@@ -31,58 +31,92 @@
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group())
        if match:
            return json.loads(match.group())
    except: return None

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器")
st.title("🗼 东京生活成本 AI 计算器 (可编辑版)")

# 核心修复：如果字段名不匹配，强制重置缓存
if "houses" not in st.session_state:
    st.session_state.houses = []
# 初始化数据表
if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源位置", "月房租(円)", "管理费(円)", "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
    ])

with st.form("input_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    loc = col1.text_input("🏠 房源位置 (车站名)", placeholder="如: 西川口")
    rent = col2.number_input("💰 月租(円)", value=80000, step=5000)
    if st.form_submit_button("🚀 提交并分析"):
        if loc:
            with st.spinner(f"正在分析 {loc} 的通勤路径..."):
                s_data = get_transit(loc, DEST_SCHOOL)
                j_data = get_transit(loc, DEST_JUKU)
# A. AI 输入区
with st.expander("🤖 使用 AI 自动添加房源", expanded=True):
    col1, col2, col3 = st.columns([2, 1, 1])
    loc_input = col1.text_input("🏠 输入车站名 (如: 西川口)", placeholder="新大久保, 中野...")
    rent_input = col2.number_input("💰 预估月租", value=80000, step=1000)
    
    if col3.button("🚀 AI 自动填表", use_container_width=True):
        if loc_input:
            with st.spinner(f"AI 正在检索 {loc_input} 的路径..."):
                s_data = get_transit(loc_input, DEST_SCHOOL)
                j_data = get_transit(loc_input, DEST_JUKU)
                if s_data and j_data:
                    st.session_state.houses.append({
                        "位置": loc, "房租": rent,
                        "学时": s_data['mins'], "学费": s_data['yen'],
                        "塾时": j_data['mins'], "塾费": j_data['yen'],
                        "路线": s_data['line']
                    })
                    new_row = pd.DataFrame([{
                        "房源位置": loc_input,
                        "月房租(円)": rent_input,
                        "管理费(円)": 5000,
                        "学时(分)": s_data['mins'],
                        "学费(单程)": s_data['yen'],
                        "塾时(分)": j_data['mins'],
                        "塾费(单程)": j_data['yen'],
                        "线路概要": s_data['line']
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()

# --- 4. 报告展示 ---
if st.session_state.houses:
    st.subheader("📊 房源对比报告")
    for h in st.session_state.houses:
# B. 可编辑表格区
st.subheader("📝 房源数据清单 (可双击修改数字)")
# 使用 data_editor 让用户可以微调数据
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    key="editor"
)
# 同步编辑后的数据到 session_state
st.session_state.df_houses = edited_df

# C. 最终分析报告
if not edited_df.empty:
    st.divider()
    st.subheader("📊 最终对比报告 (含地图)")
    
    for idx, row in edited_df.iterrows():
        # 确保数据为数字类型防止报错
        try:
            rent = float(row["月房租(円)"])
            m_fee = float(row["管理费(円)"])
            s_fare = float(row["学费(单程)"])
            j_fare = float(row["塾费(单程)"])
        except:
            continue

        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 1, 1])
            # 月通勤费 = (学校票价*10次 + 私塾票价*1次) * 4.33周
            m_transit = (h['学费'] * 10 + h['塾费'] * 1) * 4.33
            total = h['房租'] + m_transit + 60000 # 6万生活费基数
            
            # 这里的权重：学校每周5天(10次往返)，私塾每周平均1次
            monthly_transit = (s_fare * 10 + j_fare * 1) * 4.33
            total = rent + m_fee + monthly_transit + 60000 # 6万生活费基数

            with c1:
                st.markdown(f"### {h['位置']}房源")
                st.markdown(f"### **{row['房源位置']} 房源**")
                st.write(f"📉 **预估月总支出: {int(total):,} 円**")
                st.caption(f"线路概要: {h['路线']}")
                st.caption(f"线路: {row['线路概要']} | 月通勤费: {int(monthly_transit):,}")

            # 地图跳转按钮
            # 地图按钮
            base_map = "https://www.google.com/maps/dir/?api=1&travelmode=transit"
            with c2:
                url_s = f"{base_map}&origin={urllib.parse.quote(h['位置'])}&destination={urllib.parse.quote(DEST_SCHOOL)}"
                st.link_button(f"🏫 学校 ({h['学时']}分)", url_s, use_container_width=True)
                url_s = f"{base_map}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(DEST_SCHOOL)}"
                st.link_button(f"🏫 学校 ({row['学时(分)']}min)", url_s, use_container_width=True)
            with c3:
                url_j = f"{base_map}&origin={urllib.parse.quote(h['位置'])}&destination={urllib.parse.quote(DEST_JUKU)}"
                st.link_button(f"🎨 私塾 ({h['塾时']}分)", url_j, use_container_width=True)
    
                url_j = f"{base_map}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(DEST_JUKU)}"
                st.link_button(f"🎨 私塾 ({row['塾时(分)']}min)", url_j, use_container_width=True)

    if st.button("🗑️ 清空所有数据"):
        st.session_state.houses = []
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        st.rerun()


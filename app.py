import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse

# --- 1. 配置与 AI 初始化 ---
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
        if match:
            return json.loads(match.group())
    except: return None

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 (图文增强版)")

# A. 全局计算参数设置
with st.sidebar:
    st.header("⚙️ 计算参数设置")
    base_living = st.number_input("🍔 月固定生活费 (食费/杂费)", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    st.caption("注：0.5 天/周 表示两周去一次。")

# 初始化数据表 (新增：房源名称, 房源图片)
if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片URL", "月房租(円)", "管理费(円)", "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
    ])

# B. AI 输入区
with st.expander("🤖 使用 AI 自动添加房源", expanded=True):
    c1, c2, c3, c4 = st.columns([1.5, 1.5, 1, 1])
    name_input = c1.text_input("🏠 房源名称", placeholder="例如: 阳光公寓 302")
    loc_input = c2.text_input("📍 车站名", placeholder="例如: 西川口")
    rent_input = c3.number_input("💰 预估月租", value=80000, step=1000)
    
    if c4.button("🚀 AI 自动填表", use_container_width=True):
        if loc_input:
            with st.spinner(f"AI 正在检索路径..."):
                s_data = get_transit(loc_input, DEST_SCHOOL)
                j_data = get_transit(loc_input, DEST_JUKU)
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_input if name_input else f"{loc_input}新房源",
                        "房源位置": loc_input,
                        "房源图片URL": "", # 留空给用户手动粘贴
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

# C. 可编辑表格区 (配置图片列预览)
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "房源图片URL": st.column_config.ImageColumn("房源照片", help="请粘贴房源图片的URL地址"),
        "月房租(円)": st.column_config.NumberColumn(format="%d"),
        "管理费(円)": st.column_config.NumberColumn(format="%d"),
    },
    key="editor"
)
st.session_state.df_houses = edited_df

# D. 最终分析报告
if not edited_df.empty:
    st.divider()
    st.subheader("📊 最终对比报告")
    
    for idx, row in edited_df.iterrows():
        try:
            rent = float(row["月房租(円)"])
            m_fee = float(row["管理费(円)"])
            s_fare = float(row["学费(单程)"])
            j_fare = float(row["塾费(单程)"])
        except: continue

        with st.container(border=True):
            # 布局：左侧图片，中间信息，右侧地图
            img_col, info_col, btn_col = st.columns([1.5, 3, 1])
            
            # 计算总额
            monthly_transit = (s_fare * 2 * days_school + j_fare * 2 * days_juku) * 4.33
            total = rent + m_fee + monthly_transit + base_living
            
            with img_col:
                if row["房源图片URL"]:
                    st.image(row["房源图片URL"], use_container_width=True)
                else:
                    st.empty()
                    st.caption("📷 暂无照片 (在上方表格粘贴URL)")
            
            with info_col:
                st.markdown(f"### **{row['房源名称']}** ({row['房源位置']})")
                st.write(f"📉 **预估月总支出: {int(total):,} 円**")
                st.write(f"🏠 房租+管理费: {int(rent+m_fee):,} | 🚇 月通勤费: {int(monthly_transit):,}")
                st.caption(f"路线概要: {row['线路概要']}")
            
            with btn_col:
                base_map = "https://www.google.com/maps/dir/?api=1&travelmode=transit"
                url_s = f"{base_map}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(DEST_SCHOOL)}"
                st.link_button(f"🏫 学校 ({row['学时(分)']}m)", url_s, use_container_width=True)
                
                url_j = f"{base_map}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(DEST_JUKU)}"
                st.link_button(f"🎨 私塾 ({row['塾时(分)']}m)", url_j, use_container_width=True)

    # E. 底部公式说明 (保持不变)
    st.info(f"**总支出公式** = 房租 + 管理费 + [(学校票价×2×{days_school}) + (私塾票价×2×{days_juku})]×4.33 + 生活费({base_living:,}円)")

    if st.button("🗑️ 清空所有数据"):
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        st.rerun()

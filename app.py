import streamlit as st
import pandas as pd
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
from PIL import Image
import io
import base64
import urllib.parse
import re
import json

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide")

# 初始化 Google Sheets 连接
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 API KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    return genai.GenerativeModel("models/gemini-1.5-flash" if "models/gemini-1.5-flash" in models else models[0])

model = init_ai()

# --- 2. 增强工具函数 ---

def compress_and_to_base64(uploaded_file, max_size=(300, 300)):
    """压缩图片并转为 Base64，防止超出 Google Sheets 单元格限制"""
    img = Image.open(uploaded_file)
    img.thumbnail(max_size) # 等比例缩放
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=70) # 压缩质量
    return f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}"

def get_transit(origin, destination):
    prompt = f"日本交通分析 JSON：起点[{origin}]，终点[{destination}]。返回:{{'mins':整数,'yen':整数,'line':'简述'}}"
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group()) if match else None
    except: return None

# --- 3. 云端数据同步逻辑 ---

# 启动时读取云端数据
if "df_houses" not in st.session_state:
    try:
        # ttl=0 保证每次刷新都从云端拉取最新数据
        st.session_state.df_houses = conn.read(ttl=0).dropna(how="all")
    except:
        st.session_state.df_houses = pd.DataFrame(columns=[
            "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
        ])

def sync_to_cloud():
    """将当前内存中的数据物理写入 Google Sheets"""
    conn.update(data=st.session_state.df_houses)
    st.toast("☁️ 已同步至云端 Google 表格")

# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 (云端同步版)")

# A. 侧边栏设置
with st.sidebar:
    st.header("⚙️ 设置")
    dest_school = st.text_input("🏫 学校地址", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("🎨 私塾地址", value="东京都荒川区西日暮里2-12-5")
    st.divider()
    base_living = st.number_input("🍔 月固定生活费", value=60000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)

# B. 录入区
with st.expander("➕ 录入新房源 (数据将自动同步云端)", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns(3)
        name_in = n_col.text_input("🏠 房源名称")
        loc_in = l_col.text_input("📍 车站名")
        rent_in = r_col.number_input("💰 预估月租", value=80000)
    with c2:
        uploaded_file = st.file_uploader("🖼️ 拖入房源照片", type=['jpg','jpeg','png'])

    if st.button("🚀 AI 计算并存入云端", use_container_width=True):
        if loc_in:
            with st.spinner("AI 计算中..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                # 图片压缩处理
                img_data = compress_and_to_base64(uploaded_file) if uploaded_file else ""
                
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in or f"{loc_in}房源",
                        "房源位置": loc_in,
                        "房源图片": img_data,
                        "月房租(円)": rent_in,
                        "管理费(円)": 5000,
                        "学时(分)": s_data['mins'],
                        "学费(单程)": s_data['yen'],
                        "塾时(分)": j_data['mins'],
                        "塾费(单程)": j_data['yen'],
                        "线路概要": s_data['line']
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    sync_to_cloud() # 触发同步
                    st.rerun()

# C. 数据清单表
st.subheader("📝 房源数据清单 (修改后自动保存)")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic",
    use_container_width=True,
    column_config={"房源图片": st.column_config.ImageColumn("预览")},
    key="gsheets_editor"
)

# 检测表格是否有手动改动或删除
if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df
    sync_to_cloud() # 触发同步

# D. 房源开销对比分析报告
if not st.session_state.df_houses.empty:
    st.divider()
    st.subheader("📊 房源开销对比分析报告")
    for idx, row in st.session_state.df_houses.iterrows():
        try:
            # 计算总额
            commute_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
            total_m = float(row["月房租(円)"]) + float(row["管理费(円)"]) + commute_m + base_living
            
            with st.container(border=True):
                i_col, t_col, b_col = st.columns([1, 3, 1])
                with i_col:
                    if row["房源图片"]: st.image(row["房源图片"])
                with t_col:
                    st.markdown(f"### {row['房源名称']}")
                    st.write(f"📉 **预估月支出: {int(total_m):,} 円**")
                    st.caption(f"交通: {row['线路概要']}")
                with b_col:
                    m_api = "https://www.google.com/maps/dir/?api=1"
                    s_url = f"{m_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_school)}&travelmode=transit"
                    st.link_button("🏫 学校地图", s_url, use_container_width=True)
        except: continue

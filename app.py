import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
from PIL import Image
import io

# --- 1. 配置与 AI 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    try:
        # 修复 404: 优先使用最稳定的模型路径名称
        return genai.GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        st.error(f"AI 初始化失败: {e}")
        st.stop()

model = init_ai()

# --- 2. 工具函数 ---
def get_transit(origin, s_dest, j_dest):
    """
    强化版 AI 交通解析：模拟 Google Maps 真实数据返回
    通过一次性请求减少 API 调用次数并提高逻辑一致性
    """
    prompt = f"""
    你现在是 Google Maps 交通 API 专家。请分析以下日本路线并严格返回 JSON。
    起点: {origin}
    目的地1(学校): {s_dest}
    目的地2(私塾): {j_dest}

    必须包含步行时间，返回格式如下：
    {{
        "s_mins": 学校分钟, "s_yen": 学校票价, "s_line": "路线1简述",
        "j_mins": 私塾分钟, "j_yen": 私塾票价, "j_line": "路线2简述"
    }}
    """
    try:
        # 调试：确保起点有效
        if not origin or "车站" in origin:
            return None

        response = model.generate_content(prompt)
        raw_text = response.text
        
        # 实时回显调试：在界面展开查看 AI 到底返回了什么
        with st.expander(f"🔍 AI 原始数据回显 ({origin})"):
            st.code(raw_text)

        # 鲁棒性解析：提取 JSON 核心
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        st.error(f"🚨 交通计算失败: {e}")
        return None

def process_img(uploaded_file):
    """处理图片并压缩，防止 GitHub 或 Session 存储溢出"""
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((400, 400))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器")

with st.sidebar:
    st.header("⚙️ 设置")
    dest_school = st.text_input("🏫 学校地址/车站", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("🎨 私塾地址/车站", value="东京都荒川区西日暮里2-12-5")
    st.divider()
    base_living = st.number_input("🍔 月固定生活费", value=60000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)

if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
        "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路摘要"
    ])

# B. AI 输入区
with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        name_in = st.text_input("🏠 房源名称")
        loc_in = st.text_input("📍 车站名 (例: 西荻窪駅)")
        rent_in = st.number_input("💰 预估月租", value=80000)
    with c2:
        uploaded_file = st.file_uploader("🖼️ 房源照片", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 AI 自动计算并添加", use_container_width=True):
        if loc_in:
            with st.spinner("AI 正在计算最佳路径..."):
                data = get_transit(loc_in, dest_school, dest_juku)
                img_data = process_img(uploaded_file) if uploaded_file else ""
                
                if data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in if name_in else f"{loc_in}房源",
                        "房源位置": loc_in,
                        "房源图片": img_data,
                        "月房租(円)": rent_in,
                        "管理费(円)": 5000,
                        "学时(分)": data['s_mins'],
                        "学费(单程)": data['s_yen'],
                        "塾时(分)": data['j_mins'],
                        "塾费(单程)": data['j_yen'],
                        "线路摘要": f"🏫{data['s_mins']}分 | 🎨{data['j_mins']}分"
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()

# C. 数据展示
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={"房源图片": st.column_config.ImageColumn("预览")},
    key="house_editor_v2"
)
st.session_state.df_houses = edited_df

# D. 报告卡片
if not edited_df.empty:
    st.divider()
    for idx, row in edited_df.iterrows():
        # 计算逻辑保持不变...
        commute_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
        total_m = float(row["月房租(円)"]) + float(row["管理费(円)"]) + commute_m + base_living
        
        with st.container(border=True):
            col1, col2 = st.columns([1, 3])
            with col1:
                if row["房源图片"]: st.image(row["房源图片"])
            with col2:
                st.markdown(f"### {row['房源名称']}")
                st.write(f"💰 **月总预估: {int(total_m):,} 円**")
                st.caption(f"📍 位置: {row['房源位置']} | 🕒 {row['线路摘要']}")

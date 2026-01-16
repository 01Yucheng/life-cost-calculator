import streamlit as st
import pandas as pd
from github import Github
import io
import base64
from PIL import Image
import urllib.parse
import re
import json
import google.generativeai as genai

# --- 1. GitHub 存储类 ---
class GitHubStorage:
    def __init__(self):
        self.g = Github(st.secrets["github"]["token"])
        self.repo = self.g.get_repo(st.secrets["github"]["repo"])
        self.file_path = st.secrets["github"]["file_path"]
        self.branch = st.secrets["github"]["branch"]

    def load_data(self):
        try:
            content = self.repo.get_contents(self.file_path, ref=self.branch)
            return pd.read_csv(io.StringIO(content.decoded_content.decode('utf-8-sig')))
        except:
            return pd.DataFrame(columns=["房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"])

    def save_data(self, df):
        csv_content = df.to_csv(index=False, encoding='utf-8-sig')
        try:
            contents = self.repo.get_contents(self.file_path, ref=self.branch)
            self.repo.update_file(self.file_path, "update data", csv_content, contents.sha, branch=self.branch)
        except:
            self.repo.create_file(self.file_path, "initial data", csv_content, branch=self.branch)

# --- 2. 初始化与 AI 配置 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide")
storage = GitHubStorage()

if "df_houses" not in st.session_state:
    st.session_state.df_houses = storage.load_data()

@st.cache_resource
def init_ai():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel("models/gemini-1.5-flash")

model = init_ai()

# --- 3. 工具函数 ---
def compress_img(uploaded_file):
    img = Image.open(uploaded_file)
    img.thumbnail((300, 300))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"

# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 (GitHub 同步版)")

with st.sidebar:
    st.header("⚙️ 设置")
    dest_school = st.text_input("🏫 学校地址", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("🎨 私塾地址", value="东京都荒川区西日暮里2-12-5")
    base_living = st.number_input("🍔 月固定生活费", value=60000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)

# B. 录入区
with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns(3)
        name_in = n_col.text_input("🏠 房源名称")
        loc_in = l_col.text_input("📍 车站名")
        rent_in = r_col.number_input("💰 预估月租", value=80000)
    with c2:
        uploaded_file = st.file_uploader("🖼️ 房源照片", type=['jpg','jpeg','png'])

    if st.button("🚀 AI 计算并同步至 GitHub", use_container_width=True):
        if loc_in:
            # 此处省略 get_transit 调用逻辑，与之前一致
            # 计算完成后更新数据并保存
            # storage.save_data(st.session_state.df_houses)
            st.rerun()

# C. 房源清单
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(st.session_state.df_houses, num_rows="dynamic", use_container_width=True, key="main_editor")

if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df
    storage.save_data(edited_df) # 实时同步修改到 GitHub
    st.toast("✅ 数据已同步至 GitHub")

# D. 房源对比报告 (修复语法错误 )
if not st.session_state.df_houses.empty:
    st.divider()
    st.subheader("📊 房源对比分析报告")
    for idx, row in st.session_state.df_houses.iterrows():
        try:
            # 计算开销...
            with st.container(border=True):
                # 渲染卡片逻辑，包含地图跳转按钮 
                pass
        except:
            continue

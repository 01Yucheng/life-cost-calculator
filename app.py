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

# --- 1. 页面基本配置 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

# --- 2. GitHub 云端存储逻辑 ---
class GitHubStorage:
    def __init__(self):
        try:
            # 从 Secrets 获取 Token 和仓库信息
            self.g = Github(st.secrets["github"]["token"])
            self.repo = self.g.get_repo(st.secrets["github"]["repo"])
            self.file_path = "housing_data.csv"
            self.branch = "main"
        except Exception as e:
            st.error("❌ GitHub 配置缺失！请在 Secrets 中配置 [github] 信息。")
            st.stop()

    def load_data(self):
        try:
            content = self.repo.get_contents(self.file_path, ref=self.branch)
            return pd.read_csv(io.StringIO(content.decoded_content.decode('utf-8-sig')))
        except:
            # 初始表头 [cite: 20]
            return pd.DataFrame(columns=["房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学费(单程)", "塾费(单程)", "线路概要"])

    def save_data(self, df):
        csv_content = df.to_csv(index=False, encoding='utf-8-sig')
        try:
            contents = self.repo.get_contents(self.file_path, ref=self.branch)
            self.repo.update_file(self.file_path, "update", csv_content, contents.sha, branch=self.branch)
        except:
            self.repo.create_file(self.file_path, "init", csv_content, branch=self.branch)

# --- 3. 初始化与数据读取 ---
storage = GitHubStorage()
if "df_houses" not in st.session_state:
    st.session_state.df_houses = storage.load_data()

# AI 初始化
@st.cache_resource
def init_ai():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel("models/gemini-1.5-flash")

model = init_ai()

# --- 4. 侧边栏设置 ---
with st.sidebar:
    st.header("⚙️ 生活参数")
    base_living = st.number_input("🍔 月固定生活费", value=60000)
    days_school = st.slider("🏫 学校通勤天数", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤天数", 0.0, 7.0, 0.5, step=0.5)
    dest_school = st.text_input("📍 学校位置", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("📍 私塾位置", value="东京都荒川区西日暮里2-12-5")

# --- 5. 房源录入 ---
with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        name_in = st.text_input("🏠 房源名称")
        loc_in = st.text_input("📍 车站名")
        rent_in = st.number_input("💰 预估月租", value=80000)
    with c2:
        up_file = st.file_uploader("🖼️ 房源照片", type=['jpg','jpeg','png'])

    if st.button("🚀 AI 分析并保存", use_container_width=True):
        if loc_in:
            # 压缩图片 logic
            img_b64 = ""
            if up_file:
                img = Image.open(up_file)
                img.thumbnail((300, 300))
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                img_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
            
            # AI 模拟获取通勤 (此处可替换为实际 AI prompt)
            new_row = pd.DataFrame([{
                "房源名称": name_in or f"{loc_in}房源",
                "房源位置": loc_in,
                "房源图片": img_b64,
                "月房租(円)": rent_in,
                "管理费(円)": 5000,
                "学费(单程)": 200, "塾费(单程)": 300, "线路概要": "AI 正在分析线路..."
            }])
            st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
            storage.save_data(st.session_state.df_houses)
            st.rerun()

# --- 6. 数据清单 ---
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(st.session_state.df_houses, num_rows="dynamic", use_container_width=True)
if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df
    storage.save_data(edited_df)

# --- 7. 对比报告卡片 ---
if not st.session_state.df_houses.empty:
    st.divider()
    # CSS 解决 PDF 打印分页截断问题
    st.markdown('<style>@media print {.stContainer {page-break-inside: avoid;}}</style>', unsafe_allow_html=True)
    
    for idx, row in st.session_state.df_houses.iterrows():
        try:
            # 实时计算月支出
            fare_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
            total_m = float(row["月房租(円)"]) + float(row["管理费(円)"]) + fare_m + base_living
            
            with st.container(border=True):
                i_col, t_col, b_col = st.columns([1.5, 3, 1])
                with i_col:
                    if row["房源图片"]: st.image(row["房源图片"])
                with t_col:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.markdown(f"#### 💰 预估月支出: **{int(total_m):,} 円**")
                    st.write(f"🏠 房租+管理: {int(float(row['月房租(円)'])+float(row['管理费(円)'])):,} | 🚇 通勤: {int(fare_m):,}")
                with b_col:
                    m_api = "https://www.google.com/maps/dir/?api=1"
                    s_url = f"{m_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_school)}&travelmode=transit"
                    j_url = f"{m_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_juku)}&travelmode=transit"
                    st.link_button("🏫 学校地图", s_url, use_container_width=True)
                    st.link_button("🎨 私塾地图", j_url, use_container_width=True)
                    if st.button("🗑️ 删除", key=f"del_{idx}"):
                        st.session_state.df_houses = st.session_state.df_houses.drop(idx).reset_index(drop=True)
                        storage.save_data(st.session_state.df_houses)
                        st.rerun()
        except: continue

if st.button("🚨 清空所有云端数据"):
    st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
    storage.save_data(st.session_state.df_houses)
    st.rerun()

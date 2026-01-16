import streamlit as st
import pandas as pd
from github import Github
import io
import base64
from PIL import Image
import urllib.parse
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
            self.repo.update_file(self.file_path, "update housing data", csv_content, contents.sha, branch=self.branch)
        except:
            self.repo.create_file(self.file_path, "initial housing data", csv_content, branch=self.branch)

# --- 2. 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide")
storage = GitHubStorage()

if "df_houses" not in st.session_state:
    st.session_state.df_houses = storage.load_data()

# --- 3. UI 渲染 ---
st.title("🗼 东京生活成本 AI 计算器")

# 侧边栏参数 (天数、生活费等)
with st.sidebar:
    st.header("⚙️ 生活参数")
    base_living = st.number_input("🍔 月固定生活费", value=60000)
    days_school = st.slider("🏫 学校通勤天数", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤天数", 0.0, 7.0, 0.5, step=0.5)
    dest_school = st.text_input("📍 学校位置", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("📍 私塾位置", value="东京都荒川区西日暮里2-12-5")

# C. 房源数据清单
st.subheader("📝 房源数据清单")
# 允许动态删除行，删除后会自动触发 storage.save_data()
edited_df = st.data_editor(st.session_state.df_houses, num_rows="dynamic", use_container_width=True)

if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df
    storage.save_data(edited_df)
    st.toast("☁️ 数据已同步至 GitHub 仓库")

# D. 房源对比报告 (优化打印分页，防止 PDF 缺页)
if not st.session_state.df_houses.empty:
    st.divider()
    st.subheader("📊 房源开销对比分析报告")
    
    # 强制在打印时显示卡片边框
    st.markdown("""
        <style>
        @media print {
            .stContainer { border: 1px solid #ddd !important; break-inside: avoid; margin-bottom: 20px; }
        }
        </style>
    """, unsafe_allow_html=True)

    for idx, row in st.session_state.df_houses.iterrows():
        try:
            # 计算开销逻辑
            commute_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
            total_m = float(row["月房租(円)"]) + float(row["管理费(円)"]) + commute_m + base_living
            
            with st.container(border=True):
                i_col, t_col, b_col = st.columns([1.5, 3, 1])
                with i_col:
                    if row["房源图片"]: st.image(row["房源图片"], use_container_width=True)
                with t_col:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.write(f"📉 **预估月总支出: {int(total_m):,} 円**")
                    st.write(f"🏠 房租+管理: {int(float(row['月房租(円)'])+float(row['管理费(円)'])):,} | 🚇 月通勤: {int(commute_m):,}")
                with b_col:
                    m_api = "https://www.google.com/maps/dir/?api=1"
                    s_url = f"{m_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_school)}&travelmode=transit"
                    st.link_button("🏫 学校地图", s_url, use_container_width=True)
                    # 添加卡片删除按钮
                    if st.button("🗑️ 删除", key=f"btn_del_{idx}"):
                        st.session_state.df_houses = st.session_state.df_houses.drop(idx).reset_index(drop=True)
                        storage.save_data(st.session_state.df_houses)
                        st.rerun()
        except:
            continue

if st.button("🚨 清空所有数据"):
    st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
    storage.save_data(st.session_state.df_houses)
    st.rerun()

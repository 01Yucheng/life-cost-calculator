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

# --- 1. 页面配置 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

# --- 2. GitHub 存储逻辑 ---
class GitHubStorage:
    def __init__(self):
        try:
            self.g = Github(st.secrets["github"]["token"])
            self.repo = self.g.get_repo(st.secrets["github"]["repo"])
            self.file_path = st.secrets["github"].get("file_path", "housing_data.csv")
            self.branch = st.secrets["github"].get("branch", "main")
        except Exception as e:
            st.error(f"GitHub 配置错误: {e}")
            st.stop()

    def load_data(self):
        try:
            content = self.repo.get_contents(self.file_path, ref=self.branch)
            return pd.read_csv(io.StringIO(content.decoded_content.decode('utf-8-sig')))
        except:
            return pd.DataFrame(columns=[
                "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
                "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
            ])

    def save_data(self, df):
        csv_content = df.to_csv(index=False, encoding='utf-8-sig')
        try:
            contents = self.repo.get_contents(self.file_path, ref=self.branch)
            self.repo.update_file(self.file_path, "Update data", csv_content, contents.sha, branch=self.branch)
        except:
            self.repo.create_file(self.file_path, "Initial data", csv_content, branch=self.branch)

# --- 3. 初始化 ---
storage = GitHubStorage()

if "df_houses" not in st.session_state:
    st.session_state.df_houses = storage.load_data()

@st.cache_resource
def init_ai():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel("models/gemini-1.5-flash")

model = init_ai()

# --- 4. 工具函数 ---
def compress_img(uploaded_file):
    if uploaded_file is None: return ""
    img = Image.open(uploaded_file)
    img.thumbnail((400, 400)) # 压缩尺寸
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75) # 降低质量以减小体积
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"

def get_transit(origin, destination):
    prompt = f"日本交通分析 JSON：起点[{origin}]，终点[{destination}]。返回:{{'mins':整数,'yen':整数,'line':'简述'}}"
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group()) if match else None
    except: return None

# --- 5. UI 布局 ---
st.title("🗼 东京生活成本 AI 计算器")

# 侧边栏：参数设置
with st.sidebar:
    st.header("⚙️ 生活参数")
    base_living = st.number_input("🍔 月固定生活费 (伙食/杂项)", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    st.divider()
    dest_school = st.text_input("📍 学校位置", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("📍 私塾位置", value="东京都荒川区西日暮里2-12-5")

# A. 录入区
with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns(3)
        name_in = n_col.text_input("🏠 房源名称")
        loc_in = l_col.text_input("📍 车站名")
        rent_in = r_col.number_input("💰 预估月租", value=80000, step=1000)
    with c2:
        uploaded_file = st.file_uploader("🖼️ 房源照片", type=['jpg','jpeg','png'])

    if st.button("🚀 AI 分析并保存", use_container_width=True):
        if loc_in:
            with st.spinner("AI 正在计算通勤开销..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                img_data = compress_img(uploaded_file)
                
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
                    storage.save_data(st.session_state.df_houses)
                    st.rerun()

# B. 数据清单
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={"房源图片": st.column_config.ImageColumn("预览")},
    key="main_editor"
)

# 自动同步改动
if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df
    storage.save_data(edited_df)
    st.toast("✅ 已同步至 GitHub")

# C. 对比报告 (优化 PDF 导出样式)
if not st.session_state.df_houses.empty:
    st.divider()
    st.subheader("📊 房源开销对比分析报告")
    
    # CSS: 防止打印时卡片被截断
    st.markdown("""
        <style>
        @media print {
            .stContainer { break-inside: avoid; border: 1px solid #eee !important; margin-bottom: 20px !important; }
            .stButton { display: none !important; } /* 打印时不显示按钮 */
        }
        </style>
    """, unsafe_allow_html=True)

    for idx, row in st.session_state.df_houses.iterrows():
        try:
            # 动态计算
            rent_total = float(row["月房租(円)"]) + float(row["管理费(円)"])
            commute_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
            total_m = rent_total + commute_m + base_living
            
            with st.container(border=True):
                i_col, t_col, b_col = st.columns([1.5, 3, 1])
                with i_col:
                    if row["房源图片"]: st.image(row["房源图片"], use_container_width=True)
                with t_col:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.markdown(f"#### 💰 预估月总支出: **{int(total_m):,} 円**")
                    st.write(f"🏠 房租+管理: {int(rent_total):,} | 🚇 月通勤费: {int(commute_m):,}")
                    st.caption(f"线路: {row['线路概要']}")
                with b_col:
                    m_api = "https://www.google.com/maps/dir/?api=1"
                    s_url = f"{m_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_school)}&travelmode=transit"
                    j_url = f"{m_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_juku)}&travelmode=transit"
                    st.link_button("🏫 学校地图", s_url, use_container_width=True)
                    st.link_button("🎨 私塾地图", j_url, use_container_width=True)
                    if st.button("🗑️ 删除", key=f"del_card_{idx}", use_container_width=True):
                        st.session_state.df_houses = st.session_state.df_houses.drop(idx).reset_index(drop=True)
                        storage.save_data(st.session_state.df_houses)
                        st.rerun()
        except: continue

if st.button("🚨 清空所有云端数据"):
    st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
    storage.save_data(st.session_state.df_houses)
    st.rerun()

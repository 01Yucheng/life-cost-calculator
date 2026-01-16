import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
import io
from github import Github

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器 Pro", layout="wide", page_icon="🗼")

# GitHub 配置
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN")
REPO_NAME = st.secrets.get("REPO_NAME")
FILE_PATH = "housing_data.csv"

@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel("models/gemini-1.5-flash")

model = init_ai()

# --- 2. GitHub 存储逻辑 ---
def get_repo():
    g = Github(GITHUB_TOKEN)
    return g.get_repo(REPO_NAME)

def load_data():
    """从 GitHub 加载数据"""
    try:
        repo = get_repo()
        file_contents = repo.get_contents(FILE_PATH)
        data = file_contents.decoded_content.decode('utf-8-sig')
        return pd.read_csv(io.StringIO(data))
    except Exception:
        # 如果文件不存在，创建初始结构
        return pd.DataFrame(columns=[
            "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
            "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
        ])

def save_data(df):
    """保存数据到 GitHub"""
    repo = get_repo()
    csv_content = df.to_csv(index=False, encoding='utf-8-sig')
    try:
        contents = repo.get_contents(FILE_PATH)
        repo.update_file(contents.path, "Update data via App", csv_content, contents.sha)
    except Exception:
        repo.create_file(FILE_PATH, "Initial commit", csv_content)

# --- 3. 工具函数 ---
def get_transit(origin, destination):
    """AI 交通解析"""
    prompt = f"日本交通分析。起点：[{origin}]，终点：[{destination}]。仅返回JSON: {{'mins':整数,'yen':单程票价整数,'line':'路线'}}"
    try:
        response = model.generate_content(prompt)
        clean_text = re.sub(r'```json|```', '', response.text).strip()
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        return json.loads(match.group()) if match else None
    except:
        return None

def img_to_base64(img_file):
    return f"data:image/png;base64,{base64.b64encode(img_file.getvalue()).decode()}"

def get_maps_url(origin, dest):
    return f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(origin)}&destination={urllib.parse.quote(dest)}&travelmode=transit"

# --- 4. 核心逻辑 ---

# 启动时自动同步 GitHub 数据
if "df_houses" not in st.session_state:
    with st.spinner("正在从 GitHub 同步数据..."):
        st.session_state.df_houses = load_data()

# --- 5. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 (GitHub 同步版)")

with st.sidebar:
    st.header("⚙️ 参数设置")
    dest_school = st.text_input("🏫 学校", value="东京都新宿区百人町2-24-12 (美都里慕)")
    dest_juku = st.text_input("🎨 私塾", value="东京都荒川区西日暮里2-12-5 (尚艺舍)")
    st.divider()
    base_living = st.number_input("🍔 月生活费 (固定)", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    
    if st.button("💾 强制保存到 GitHub"):
        save_data(st.session_state.df_houses)
        st.success("数据已同步！")

# A. 录入区
with st.expander("➕ 添加新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1, 1, 1])
        name_in = n_col.text_input("🏠 名称")
        loc_in = l_col.text_input("📍 车站")
        rent_in = r_col.number_input("💰 月租", value=80000)
    with c2:
        uploaded_file = st.file_uploader("🖼️ 照片", type=['jpg','png'])

    if st.button("🚀 AI 计算并添加", use_container_width=True):
        if loc_in:
            with st.spinner("AI 正在解析路径..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                img_data = img_to_base64(uploaded_file) if uploaded_file else ""
                
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in or f"{loc_in}房源",
                        "房源位置": loc_in,
                        "房源图片": img_data,
                        "月房租(円)": rent_in,
                        "管理费(円)": 5000,
                        "学时(分)": s_data['mins'], "学费(单程)": s_data['yen'],
                        "塾时(分)": j_data['mins'], "塾费(单程)": j_data['yen'],
                        "线路概要": s_data['line']
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    save_data(st.session_state.df_houses) # 自动保存
                    st.rerun()

# B. 数据清单
st.subheader("📝 房源管理")
edited_df = st.data_editor(
    st.session_state.df_houses,
    num_rows="dynamic",
    use_container_width=True,
    column_config={"房源图片": st.column_config.ImageColumn("预览")},
    key="main_editor"
)

# 如果编辑了表格，实时保存
if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df
    save_data(edited_df)

# C. 报告生成
if not st.session_state.df_houses.empty:
    st.divider()
    st.subheader("📊 综合开销报告")
    
    for idx, row in st.session_state.df_houses.iterrows():
        try:
            # 计算逻辑
            commute_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
            total_m = float(row["月房租(円)"]) + float(row["管理费(円)"]) + commute_m + base_living
            
            with st.container(border=True):
                img_c, info_c, btn_c = st.columns([1, 2.5, 1])
                with img_c:
                    if row["房源图片"]: st.image(row["房源图片"])
                    else: st.caption("无照片")
                with info_c:
                    st.markdown(f"### {row['房源名称']}")
                    st.write(f"💰 **月总预估: {int(total_m):,} 円**")
                    st.caption(f"🏠 租金: {int(row['月房租(円)']):,} | 🚇 交通: {int(commute_m):,}")
                with btn_c:
                    st.link_button("🏫 学校路线", get_maps_url(row['房源位置'], dest_school), use_container_width=True)
                    st.link_button("🎨 私塾路线", get_maps_url(row['房源位置'], dest_juku), use_container_width=True)
        except: continue

    if st.button("🗑️ 清空所有数据"):
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        save_data(st.session_state.df_houses)
        st.rerun()

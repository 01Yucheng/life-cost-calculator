import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
import io
from github import Github

# --- 1. 核心配置读取 (适配你的 Secrets 结构) ---
try:
    # 适配你提供的 [github] 和 GEMINI_API_KEY 结构
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
    GH_TOKEN = st.secrets.github.token
    GH_REPO = st.secrets.github.repo
    GH_FILE = st.secrets.github.file_path
    GH_BRANCH = st.secrets.github.branch
except Exception as e:
    st.error(f"❌ Secrets 配置读取失败，请检查格式。错误: {e}")
    st.stop()

# --- 2. 初始化 AI ---
@st.cache_resource
def init_ai():
    genai.configure(api_key=GEMINI_KEY)
    return genai.GenerativeModel("models/gemini-1.5-flash")

model = init_ai()

# --- 3. GitHub 存储逻辑 ---
def get_repo():
    g = Github(GH_TOKEN)
    return g.get_repo(GH_REPO)

def load_data_from_gh():
    try:
        repo = get_repo()
        file_content = repo.get_contents(GH_FILE, ref=GH_BRANCH)
        return pd.read_csv(io.StringIO(file_content.decoded_content.decode('utf-8-sig')))
    except:
        # 初始表头
        return pd.DataFrame(columns=[
            "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
            "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
        ])

def save_data_to_gh(df):
    repo = get_repo()
    # 统一转换数据类型，防止 JSON 序列化错误
    csv_content = df.astype(str).to_csv(index=False, encoding='utf-8-sig')
    try:
        contents = repo.get_contents(GH_FILE, ref=GH_BRANCH)
        repo.update_file(contents.path, "Update data", csv_content, contents.sha, branch=GH_BRANCH)
    except:
        repo.create_file(GH_FILE, "Init data", csv_content, branch=GH_BRANCH)

# --- 4. 工具函数 ---
def get_transit(origin, destination):
    prompt = f"日本交通分析。起点：[{origin}]，终点：[{destination}]。返回 JSON: {{'mins':整数,'yen':整数,'line':'简述'}}"
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            # 强化 JSON 解析，处理可能的单引号问题
            res_text = match.group().replace("'", '"')
            return json.loads(res_text)
    except:
        return None

def img_to_base64(img_file):
    if img_file is None: return ""
    return f"data:image/png;base64,{base64.b64encode(img_file.getvalue()).decode()}"

# --- 5. UI 界面逻辑 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide")
st.title("🗼 东京生活成本 AI 计算器 (GitHub 自动保存)")

# 初始化数据
if "df_houses" not in st.session_state:
    st.session_state.df_houses = load_data_from_gh()

# 侧边栏设置
with st.sidebar:
    st.header("⚙️ 设置")
    dest_school = st.text_input("🏫 学校", value="新宿区百人町2-24-12")
    dest_juku = st.text_input("🎨 私塾", value="荒川区西日暮里2-12-5")
    base_living = st.number_input("🍔 月固定生活费", value=60000)
    days_school = st.slider("🏫 学校天数", 1, 7, 5)
    days_juku = st.slider("🎨 私塾天数", 0.0, 7.0, 0.5)
    if st.button("🔄 手动刷新 GitHub 数据"):
        st.session_state.df_houses = load_data_from_gh()
        st.rerun()

# 录入区
with st.expander("➕ 添加新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns(3)
        name_in = n_col.text_input("房源名称")
        loc_in = l_col.text_input("车站名")
        rent_in = r_col.number_input("月租", value=75000)
    with c2:
        up_file = st.file_uploader("拖入照片", type=['png','jpg'])

    if st.button("🚀 计算并同步到 GitHub", use_container_width=True):
        if loc_in:
            with st.spinner("AI 正在计算并上传..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                if s_data and j_data:
                    new_data = {
                        "房源名称": name_in or f"{loc_in}房源",
                        "房源位置": loc_in,
                        "房源图片": img_to_base64(up_file),
                        "月房租(円)": rent_in,
                        "管理费(円)": 5000,
                        "学时(分)": s_data['mins'], "学费(单程)": s_data['yen'],
                        "塾时(分)": j_data['mins'], "塾费(单程)": j_data['yen'],
                        "线路概要": s_data['line']
                    }
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, pd.DataFrame([new_data])], ignore_index=True)
                    save_data_to_gh(st.session_state.df_houses)
                    st.success("同步成功！")
                    st.rerun()

# 数据表格
st.subheader("📋 数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses,
    use_container_width=True,
    num_rows="dynamic",
    column_config={"房源图片": st.column_config.ImageColumn("预览")}
)

# 自动保存表格修改
if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df
    save_data_to_gh(edited_df)

# 分析报告
if not st.session_state.df_houses.empty:
    st.divider()
    for _, row in st.session_state.df_houses.iterrows():
        try:
            # 计算总额
            c_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
            total = float(row["月房租(円)"]) + float(row["管理费(円)"]) + c_m + base_living
            
            with st.container(border=True):
                i_c, t_c = st.columns([1, 4])
                with i_c: 
                    if row["房源图片"]: st.image(row["房源图片"])
                with t_c:
                    st.markdown(f"### {row['房源名称']} - **总支出: {int(total):,} 円**")
                    st.write(f"🚇 月通勤: {int(c_m):,} | 🕒 学:{row['学时(分)']}min / 塾:{row['塾时(分)']}min")
        except: continue

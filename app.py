import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
from github import Github, Auth
from io import BytesIO
from PIL import Image

# --- 1. 配置与 AI 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器 Pro", layout="wide", page_icon="🗼")

@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target = "models/gemini-3-flash"
        return genai.GenerativeModel(target if target in models else models[0])
    except Exception as e:
        st.error(f"AI 初始化失败: {e}")
        st.stop()

model = init_ai()

# --- 2. GitHub 数据同步工具 ---
def get_github_repo():
    try:
        auth = Auth.Token(st.secrets["GITHUB_TOKEN"])
        g = Github(auth=auth)
        return g.get_repo(st.secrets["REPO_NAME"])
    except Exception as e:
        st.error(f"GitHub 连接失败，请检查 Secrets 配置: {e}")
        return None

def load_data_from_github():
    cols = [
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
        "初期资金投入", "初期费用明细", "面积", "户型",
        "学时(分)", "学费(单程)", "学定期(月)", 
        "塾时(分)", "塾费(单程)", "塾定期(月)"
    ]
    try:
        repo = get_github_repo()
        if repo:
            file_content = repo.get_contents("house_data.csv")
            df = pd.read_csv(BytesIO(file_content.decoded_content), encoding='utf-8-sig')
            for c in cols:
                if c not in df.columns: df[c] = ""
            num_cols = ["月房租(円)", "管理费(円)", "初期资金投入", "学费(单程)", "学定期(月)", "塾时(分)", "塾费(单程)", "塾定期(月)"]
            for col in num_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            df["房源图片"] = df["房源图片"].fillna("")
            return df[cols]
    except Exception:
        return pd.DataFrame(columns=cols)

def save_data_to_github(df):
    repo = get_github_repo()
    if not repo: return
    csv_string = df.to_csv(index=False, encoding='utf-8-sig')
    try:
        contents = repo.get_contents("house_data.csv")
        repo.update_file(contents.path, "Update data", csv_string, contents.sha)
        return True
    except Exception:
        repo.create_file("house_data.csv", "Initial commit", csv_string)
        return True

# --- 3. 工具函数 ---
def safe_int(val):
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)) or val == "": 
            return 0
        return int(float(val))
    except: return 0

def analyze_house_image(uploaded_file):
    try:
        img = Image.open(uploaded_file)
        prompt = "作为日本不动产专家，从图中提取信息并返回 JSON (name, station, rent, admin, initial_total, area, layout, details)。不含Markdown代码块。"
        response = model.generate_content([prompt, img])
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group()) if match else None
    except: return None

def get_transit(origin, destination):
    if not origin: return {"mins": 0, "yen": 0, "pass": 0}
    prompt = f"从[{origin}]到[{destination}]通勤，返回JSON: {{\"mins\": 整数, \"yen\": 单程, \"pass\": 月定期}}"
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group()) if match else {"mins": 0, "yen": 0, "pass": 0}
    except: return {"mins": 0, "yen": 0, "pass": 0}

# --- 4. UI 界面逻辑 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

# 初始化数据
if "df_houses" not in st.session_state:
    st.session_state.df_houses = load_data_from_github()

with st.sidebar:
    st.header("⚙️ 全局设置")
    dest_school = st.text_input("🏫 学校", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("🎨 私塾", value="东京都荒川区西日暮里2-12-5")
    stay_months = st.slider("📅 居住月数", 1, 48, 24)
    base_living = st.number_input("🍔 月固定生活费", value=60000)
    days_school = st.slider("🏫 学校通勤(天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤(天/周)", 0.0, 7.0, 0.5, step=0.5)
    use_pass_option = st.toggle("🎫 考虑定期券", value=True)
    
    if st.button("🔄 手动同步云端", type="primary"):
        save_data_to_github(st.session_state.df_houses)
        st.success("同步成功")

# 录入区 (唯一)
with st.expander("➕ 录入新房源", expanded=True):
    up_file = st.file_uploader("🖼️ 上传房源图", type=['png', 'jpg', 'jpeg'], key="uploader_main")
    
    if "ai_cache" not in st.session_state:
        st.session_state.ai_cache = {"name": "", "station": "", "rent": 0, "admin": 0, "initial": 0, "details": "", "area": "", "layout": ""}

    if up_file and st.button("🔍 AI 解析图片"):
        with st.spinner("AI 正在解析..."):
            res = analyze_house_image(up_file)
            if res: st.session_state.ai_cache = res

    cache = st.session_state.ai_cache
    c1, c2 = st.columns(2)
    name_in = c1.text_input("🏠 房源名称", value=cache.get("name", ""))
    loc_in = c2.text_input("📍 最近车站", value=cache.get("station", ""))
    
    r1, r2, r3 = st.columns(3)
    rent_in = r1.number_input("💰 月租", value=safe_int(cache.get("rent")))
    adm_in = r2.number_input("🏢 管理费", value=safe_int(cache.get("admin")))
    ini_in = r3.number_input("🔑 初期总额", value=safe_int(cache.get("initial_total") or cache.get("initial")))
    
    det_in = st.text_input("📝 初期明细", value=cache.get("details", ""))

    if st.button("🚀 计算并添加到清单并保存到云端", width="stretch"):
        with st.spinner("正在计算并同步云端..."):
            s_d = get_transit(loc_in, dest_school)
            j_d = get_transit(loc_in, dest_juku)
            img_b64 = f"data:image/png;base64,{base64.b64encode(up_file.getvalue()).decode()}" if up_file else ""
            
            new_row = {
                "房源名称": name_in, "房源位置": loc_in, "房源图片": img_b64,
                "月房租(円)": rent_in, "管理费(円)": adm_in, "初期资金投入": ini_in, 
                "初期费用明细": det_in, "面积": cache.get("area",""), "户型": cache.get("layout",""),
                "学时(分)": s_d.get('mins', 0), "学费(单程)": s_d.get('yen', 0), "学定期(月)": s_d.get('pass', 0),
                "塾时(分)": j_d.get('mins', 0), "塾费(单程)": j_d.get('yen', 0), "塾定期(月)": j_d.get('pass', 0)
            }
            # 立即保存到 GitHub
            current_df = pd.concat([st.session_state.df_houses, pd.DataFrame([new_row])], ignore_index=True)
            save_data_to_github(current_df)
            st.session_state.df_houses = current_df
            st.rerun()

# 数据表格
st.subheader("📝 数据清单")
# 允许用户在表格里修改后自动保存
edited_df = st.data_editor(st.session_state.df_houses, num_rows="dynamic", use_container_width=True, key="editor_v2")
if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df
    save_data_to_github(edited_df)

# 卡片展示
if not st.session_state.df_houses.empty:
    st.divider()
    # 这里的计算逻辑使用你原有的计算平摊和排序代码即可...
    # (篇幅原因省略，逻辑与之前一致)
    st.info("已完成数据持久化，刷新页面将从 GitHub 自动重新加载。")

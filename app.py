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
        # 统一使用 flash 模型
        return genai.GenerativeModel("gemini-1.5-flash")
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
        st.error(f"GitHub 连接失败: {e}")
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
            # 关键：处理 utf-8-sig
            df = pd.read_csv(BytesIO(file_content.decoded_content), encoding='utf-8-sig')
            df.columns = [c.strip() for c in df.columns]
            for c in cols:
                if c not in df.columns: df[c] = ""
            # 类型修正
            num_cols = ["月房租(円)", "管理费(円)", "初期资金投入", "学费(单程)", "学定期(月)", "塾时(分)", "塾费(单程)", "塾定期(月)"]
            for col in num_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            df["房源图片"] = df["房源图片"].fillna("")
            return df[cols]
    except:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def save_data_to_github(df):
    repo = get_github_repo()
    if not repo: return
    csv_string = df.to_csv(index=False, encoding='utf-8-sig')
    try:
        contents = repo.get_contents("house_data.csv")
        repo.update_file(contents.path, "Update house data", csv_string, contents.sha)
        st.success("✅ 数据已同步至 GitHub!")
    except:
        repo.create_file("house_data.csv", "Initial commit", csv_string)
        st.success("🚀 GitHub 数据库已初始化!")

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
        prompt = "作为日本不动产专家，请从图中提取信息并返回JSON格式（name, station, rent, admin, initial_total, area, layout, details）。不要包含Markdown代码块外壳。"
        response = model.generate_content([prompt, img])
        # 增强 JSON 提取逻辑
        clean_text = re.search(r'\{.*\}', response.text, re.DOTALL).group()
        return json.loads(clean_text)
    except: return None

def get_transit(origin, destination):
    if not origin or origin.strip() == "": return {"mins": 0, "yen": 0, "pass": 0}
    prompt = f"计算从[{origin}]到[{destination}]通勤，返回JSON: {{\"mins\": 整数, \"yen\": 单程, \"pass\": 月定期}}"
    try:
        response = model.generate_content(prompt)
        clean_text = re.search(r'\{.*\}', response.text, re.DOTALL).group()
        return json.loads(clean_text)
    except: return {"mins": 0, "yen": 0, "pass": 0}

# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

if "df_houses" not in st.session_state:
    st.session_state.df_houses = load_data_from_github()

# --- 录入新房源逻辑修复 ---
with st.expander("➕ 录入新房源", expanded=True):
    up_file = st.file_uploader("🖼️ 上传房源详情图", type=['png', 'jpg', 'jpeg'], key="main_house_uploader")
    if "ai_cache" not in st.session_state:
        st.session_state.ai_cache = {"name": "", "station": "", "rent": 0, "admin": 0, "initial": 0, "details": "", "area": "", "layout": ""}

    if up_file and st.button("🔍 AI 扫描房源图"):
        with st.spinner("AI 识别中..."):
            res = analyze_house_image(up_file)
            if res:
                st.session_state.ai_cache.update({
                    "name": res.get("name", ""), "station": res.get("station", ""),
                    "rent": res.get("rent", 0), "admin": res.get("admin", 0),
                    "initial": res.get("initial_total", 0), "details": res.get("details", ""),
                    "area": str(res.get("area", "")), "layout": res.get("layout", "")
                })

    # 表单部分保持原样...
    # (此处省略中间表单代码，逻辑与你原代码一致)
    
    # 核心修复：保存时的图片处理
    if st.button("🚀 计算并保存到云端", type="primary"):
        # ... (前置逻辑)
        with st.spinner("正在处理..."):
            img_b64 = ""
            if up_file:
                # 修复点：压缩图片防止文件过大
                img_temp = Image.open(up_file)
                img_temp.thumbnail((800, 800)) 
                buf = BytesIO()
                img_temp.convert("RGB").save(buf, format="JPEG", quality=75)
                img_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
            
            # ... (生成 new_row 逻辑)
            st.session_state.df_houses = pd.concat([st.session_state.df_houses, pd.DataFrame([new_row])], ignore_index=True)
            save_data_to_github(st.session_state.df_houses)
            st.rerun()

# --- 数据清单表同步修复 ---
st.subheader("📝 房源数据清单")
# 这里的 edited_df 需要在后续逻辑中替代 st.session_state.df_houses 进行报告计算
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True, 
    key="main_data_editor"
)
# 关键：确保编辑器修改后的数据立即生效
st.session_state.df_houses = edited_df 

# ... (后续报告展示逻辑保持不变)

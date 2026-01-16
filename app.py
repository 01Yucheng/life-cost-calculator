import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
from github import Github 
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
    # 使用 1.5-flash 模型以支持图片多模态分析
    return genai.GenerativeModel("models/gemini-1.5-flash")

model = init_ai()

# --- 2. GitHub 数据同步工具 ---
def get_github_repo():
    try:
        g = Github(st.secrets["GITHUB_TOKEN"])
        return g.get_repo(st.secrets["REPO_NAME"])
    except Exception as e:
        # 捕获 Token 缺失错误
        st.error(f"GitHub 连接失败: {e}")
        return None

def load_data_from_github():
    try:
        repo = get_github_repo()
        file_content = repo.get_contents("house_data.csv")
        return pd.read_csv(BytesIO(file_content.decoded_content))
    except Exception:
        return pd.DataFrame(columns=[
            "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
            "初期资金投入", "学时(分)", "学费(单程)", "学定期(月)", 
            "塾时(分)", "塾费(单程)", "塾定期(月)", "线路概要"
        ])

# --- 3. 新增：图片解析工具 ---
def analyze_house_image(img_file):
    """提取图片中的房源信息"""
    img = Image.open(img_file)
    prompt = """
    你是不动产专家。请从这张日本房源图中提取以下信息并返回纯 JSON：
    {
      "name": "大楼名称",
      "station": "最近车站名",
      "rent": 租金数字,
      "admin": 管理费数字,
      "initial": 初期费用总计(请加总礼金、押金、保险、清扫费等所有一次性支出)
    }
    如果没有某项请填0。不要输出任何解释文字。
    """
    try:
        response = model.generate_content([prompt, img])
        clean_json = re.sub(r'```json|```', '', response.text).strip()
        return json.loads(clean_json)
    except:
        return None

def get_transit(origin, destination):
    prompt = f"从[{origin}]到[{destination}]通勤，返回JSON: {{\"mins\": 整数, \"yen\": 单程, \"pass_month\": 定期, \"line\": \"路线\"}}"
    try:
        response = model.generate_content(prompt)
        clean_text = re.sub(r'```json|```', '', response.text).strip()
        return json.loads(clean_text)
    except: return None

# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

with st.sidebar:
    st.header("⚙️ 全局设置")
    dest_school = st.text_input("🏫 学校/车站", value="新宿")
    dest_juku = st.text_input("🎨 私塾/车站", value="西日暮里")
    st.divider()
    stay_months = st.slider("📅 预计居住时间 (月)", 1, 48, 24)
    base_living = st.number_input("🍔 月固定基本生活费", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    use_pass_option = st.toggle("🎫 考虑定期券方案", value=True)

if "df_houses" not in st.session_state:
    st.session_state.df_houses = load_data_from_github()

# B. AI 输入区 (新增自动解析功能)
with st.expander("➕ 录入新房源 (支持照片自动识别)", expanded=True):
    up_img = st.file_uploader("📸 上传房源图 (支持 MySoku 截图)", type=['png', 'jpg', 'jpeg'])
    
    # 预设值逻辑
    init_vals = {"name": "", "station": "", "rent": 80000, "admin": 5000, "initial": 0}
    
    if up_img and st.button("🔍 AI 自动分析照片"):
        with st.spinner("AI 正在读取房源数据..."):
            res = analyze_house_image(up_img)
            if res: init_vals.update(res)

    c1, c2 = st.columns([2, 1])
    with c1:
        col_n, col_s = st.columns(2)
        name_in = col_n.text_input("🏠 房源名称", value=init_vals["name"])
        loc_in = col_s.text_input("📍 最近车站", value=init_vals["station"])
        
        col_r, col_a, col_i = st.columns(3)
        rent_in = col_r.number_input("💰 月租", value=int(init_vals["rent"]))
        admin_in = col_a.number_input("🏢 管理费", value=int(init_vals["admin"]))
        initial_in = col_i.number_input("🔑 初期资金投入", value=int(init_vals["initial"]))

    if st.button("🚀 计算并添加", use_container_width=True):
        if loc_in:
            with st.spinner("AI 计算通勤中..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                img_data = f"data:image/png;base64,{base64.b64encode(up_img.getvalue()).decode()}" if up_img else ""
                
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in, "房源位置": loc_in, "房源图片": img_data,
                        "月房租(円)": rent_in, "管理费(円)": admin_in, "初期资金投入": initial_in,
                        "学时(分)": s_data['mins'], "学费(单程)": s_data['yen'], "学定期(月)": s_data.get('pass_month', 0),
                        "塾时(分)": j_data['mins'], "塾费(单程)": j_data['yen'], "塾定期(月)": j_data.get('pass_month', 0)
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()

# C. 数据管理 (安全性增强：处理 NaN)
st.subheader("📝 房源数据清单")
df_safe = st.session_state.df_houses.copy()
# 强制转换所有数值列，防止 int(NaN) 报错
num_cols = ["月房租(円)", "管理费(円)", "初期资金投入", "学费(单程)", "学定期(月)", "塾费(单程)", "塾定期(月)"]
for col in num_cols:
    if col in df_safe.columns:
        df_safe[col] = pd.to_numeric(df_safe[col], errors='coerce').fillna(0)

edited_df = st.data_editor(df_safe, num_rows="dynamic", use_container_width=True)
st.session_state.df_houses = edited_df

# D. 自动排序展示
if not edited_df.empty:
    st.divider()
    st.subheader(f"📊 房源推荐 (按 {stay_months}个月居住平摊排序)")

    report_list = []
    for _, row in edited_df.iterrows():
        try:
            # 通勤计算 (忽略空行)
            if not row["房源名称"]: continue
            s_pay = row["学费(单程)"] * 2 * days_school * 4.33
            s_pass = row["学定期(月)"]
            best_s = min(s_pay, s_pass) if (use_pass_option and s_pass > 0) else s_pay
            
            j_pay = row["塾费(单程)"] * 2 * days_juku * 4.33
            j_pass = row["塾定期(月)"]
            best_j = min(j_pay, j_pass) if (use_pass_option and j_pass > 0) else j_pay
            
            monthly_fixed = row["月房租(円)"] + row["管理费(円)"] + best_s + best_j + base_living
            amort_init = row["初期资金投入"] / (stay_months if stay_months > 0 else 1)
            total = monthly_fixed + amort_init
            
            report_list.append({"data": row, "total": total, "fixed": monthly_fixed, "amort": amort_init})
        except: continue
    
    sorted_reports = sorted(report_list, key=lambda x: x['total'])

    for i, item in enumerate(sorted_reports):
        r = item['data']
        with st.container(border=True):
            c1, c2 = st.columns([1, 4])
            with c1:
                if r["房源图片"]: st.image(r["房源图片"])
            with c2:
                st.markdown(f"### {'🥇 ' if i==0 else ''}{r['房源名称']} ({r['房源位置']})")
                st.write(f"📈 **实际月均支出: {int(item['total']):,} 円**")
                st.write(f"🏠 租金+生活: {int(item['fixed']):,} | 🔑 初期平摊: +{int(item['amort']):,}/月")

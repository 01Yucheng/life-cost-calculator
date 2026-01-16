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
    # 使用支持多模态的 flash 模型
    return genai.GenerativeModel("models/gemini-1.5-flash")

model = init_ai()

# --- 2. GitHub 数据同步 ---
def load_data_from_github():
    try:
        g = Github(st.secrets["GITHUB_TOKEN"])
        repo = g.get_repo(st.secrets["REPO_NAME"])
        file_content = repo.get_contents("house_data.csv")
        return pd.read_csv(BytesIO(file_content.decoded_content))
    except Exception:
        return pd.DataFrame(columns=[
            "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
            "初期资金投入", "学时(分)", "学费(单程)", "学定期(月)", 
            "塾时(分)", "塾费(单程)", "塾定期(月)", "线路概要"
        ])

def save_data_to_github(df):
    try:
        g = Github(st.secrets["GITHUB_TOKEN"])
        repo = g.get_repo(st.secrets["REPO_NAME"])
        csv_string = df.to_csv(index=False, encoding='utf-8-sig')
        contents = repo.get_contents("house_data.csv")
        repo.update_file(contents.path, "Update data", csv_string, contents.sha)
        st.success("✅ 数据已同步至 GitHub!")
    except Exception as e:
        st.error(f"同步失败: {e}")

# --- 3. 工具函数 ---
def analyze_house_image(uploaded_file):
    """利用 AI 分析房源图片并提取 JSON 信息"""
    img = Image.open(uploaded_file)
    prompt = """
    你是一位日本不动产专家。请从这张房源图中提取以下信息并返回 JSON 格式：
    {
      "name": "房源名称/大楼名",
      "station": "最近的车站名",
      "rent": 月租金数字,
      "admin_fee": 管理费数字,
      "initial_total": 初期投入总额(礼金+押金+中介费+清扫费等所有开支的总和)
    }
    注意：只返回 JSON，不要任何解释。如果某项不确定，请填 0。
    """
    response = model.generate_content([prompt, img])
    try:
        clean_text = re.sub(r'```json|```', '', response.text).strip()
        return json.loads(clean_text)
    except:
        return None

def get_transit(origin, destination):
    prompt = f"从[{origin}]到[{destination}]通勤，返回JSON: {{\"mins\": 整数, \"yen\": 单程票价, \"pass_month\": 定期券, \"line\": \"路线\"}}"
    try:
        response = model.generate_content(prompt)
        clean_text = re.sub(r'```json|```', '', response.text).strip()
        return json.loads(clean_text)
    except:
        return None

# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

with st.sidebar:
    st.header("⚙️ 全局设置")
    dest_school = st.text_input("🏫 学校/车站", value="新宿")
    dest_juku = st.text_input("🎨 私塾/车站", value="西日暮里")
    stay_months = st.slider("📅 预计居住时间 (月)", 1, 48, 24)
    base_living = st.number_input("🍔 月固定基本生活费", value=60000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5)
    use_pass_option = st.toggle("🎫 考虑定期券方案", value=True)
    
    if st.button("💾 保存到 GitHub", type="primary"):
        save_data_to_github(st.session_state.df_houses)

if "df_houses" not in st.session_state:
    st.session_state.df_houses = load_data_from_github()

# B. AI 输入区
with st.expander("➕ 录入新房源 (支持 AI 图片识别)", expanded=True):
    uploaded_file = st.file_uploader("🖼️ 上传房源详情图", type=['png', 'jpg', 'jpeg'])
    
    c1, c2 = st.columns([2, 1])
    # 自动填充逻辑
    ai_data = {"name": "", "station": "", "rent": 80000, "admin_fee": 5000, "initial_total": 0}
    
    if uploaded_file and st.button("🔍 AI 自动分析照片"):
        with st.spinner("AI 正在解析房源参数..."):
            res = analyze_house_image(uploaded_file)
            if res: ai_data.update(res)

    with c1:
        n_col, l_col = st.columns(2)
        name_in = n_col.text_input("🏠 房源名称", value=ai_data["name"])
        loc_in = l_col.text_input("📍 最近车站", value=ai_data["station"])
        
        r_col, a_col, i_col = st.columns(3)
        rent_in = r_col.number_input("💰 月租(円)", value=int(ai_data["rent"]))
        admin_in = a_col.number_input("🏢 管理费", value=int(ai_data["admin_fee"]))
        initial_in = i_col.number_input("🔑 初期资金投入", value=int(ai_data["initial_total"]))

    if st.button("🚀 计算通勤并添加", use_container_width=True):
        if loc_in:
            with st.spinner("计算通勤路径..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                img_str = f"data:image/png;base64,{base64.b64encode(uploaded_file.getvalue()).decode()}" if uploaded_file else ""
                
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in, "房源位置": loc_in, "房源图片": img_str,
                        "月房租(円)": rent_in, "管理费(円)": admin_in, "初期资金投入": initial_in,
                        "学时(分)": s_data['mins'], "学费(单程)": s_data['yen'], "学定期(月)": s_data.get('pass_month', 0),
                        "塾时(分)": j_data['mins'], "塾费(单程)": j_data['yen'], "塾定期(月)": j_data.get('pass_month', 0)
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()

# C. 数据清单管理
st.subheader("📝 房源数据清单")
# 预处理数据防止 NaN 导致转换 int 报错
df_edit = st.session_state.df_houses.copy()
for col in ["月房租(円)", "管理费(円)", "初期资金投入", "学费(单程)", "学定期(月)", "塾费(单程)", "塾定期(月)"]:
    if col in df_edit.columns:
        df_edit[col] = pd.to_numeric(df_edit[col], errors='coerce').fillna(0)

edited_df = st.data_editor(df_edit, num_rows="dynamic", use_container_width=True)
st.session_state.df_houses = edited_df

# D. 自动排序报告
if not edited_df.empty:
    st.divider()
    st.subheader(f"📊 房源推荐 (按 {stay_months}个月居住平摊排序)")

    report_list = []
    for _, row in edited_df.iterrows():
        try:
            # 通勤费逻辑
            s_pay = row["学费(单程)"] * 2 * days_school * 4.33
            s_pass = row["学定期(月)"]
            best_s = min(s_pay, s_pass) if (use_pass_option and s_pass > 0) else s_pay
            
            j_pay = row["塾费(单程)"] * 2 * days_juku * 4.33
            j_pass = row["塾定期(月)"]
            best_j = min(j_pay, j_pass) if (use_pass_option and j_pass > 0) else j_pay
            
            monthly_fixed = row["月房租(円)"] + row["管理费(円)"] + best_s + best_j + base_living
            amortized_init = row["初期资金投入"] / (stay_months if stay_months > 0 else 1)
            total = monthly_fixed + amortized_init
            
            report_list.append({"data": row, "total": total, "fixed": monthly_fixed, "amortized": amortized_init})
        except: continue
    
    sorted_reports = sorted(report_list, key=lambda x: x['total'])

    for i, item in enumerate(sorted_reports):
        r = item['data']
        with st.container(border=True):
            c_img, c_txt = st.columns([1, 4])
            with c_img:
                if r["房源图片"]: st.image(r["房源图片"])
            with c_txt:
                st.markdown(f"### {'🥇 ' if i==0 else ''}{r['房源名称']} ({r['房源位置']})")
                st.write(f"📈 **实际月均总支出: {int(item['total']):,} 円**")
                st.write(f"🏠 租金+通勤+生活: {int(item['fixed']):,} | 🔑 初期平摊: +{int(item['amortized']):,}/月")

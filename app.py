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
@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 缺失 API KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # 修复 404 错误：改用更通用的模型调用字符串
    return genai.GenerativeModel("gemini-1.5-flash"

model = init_ai()

# --- 2. 工具函数 (新增图片解析) ---
def analyze_house_image(uploaded_file):
    """提取房源图片中的关键信息"""
    try:
        img = Image.open(uploaded_file)
        prompt = """
        你是一位日本不动产专家。请从这张房源详情图中提取以下信息并以 JSON 格式返回：
        {
          "name": "房源/公寓名称",
          "station": "最近的车站",
          "rent": 租金数字,
          "admin": 管理费数字,
          "initial": 前期投入总计(礼金+押金+保证会社+保险+清扫费等之和)
        }
        注意：仅返回 JSON，不确定则填 0 或空字符串。
        """
        response = model.generate_content([prompt, img])
        clean_text = re.sub(r'```json|```', '', response.text).strip()
        return json.loads(clean_text)
    except Exception as e:
        st.warning(f"图片解析失败: {e}")
        return None

def get_transit(origin, destination):
    prompt = f"从[{origin}]到[{destination}]通勤，仅返回 JSON: {{\"mins\": 整数, \"yen\": 单程, \"pass\": 月定期, \"line\": \"路线\"}}"
    try:
        response = model.generate_content(prompt)
        return json.loads(re.sub(r'```json|```', '', response.text).strip())
    except: return None

# --- 3. UI 逻辑 ---
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

if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
        "初期资金投入", "学时(分)", "学费(单程)", "学定期(月)", 
        "塾时(分)", "塾费(单程)", "塾定期(月)"
    ])

# B. AI 输入区
with st.expander("➕ 录入新房源 (支持照片识别)", expanded=True):
    up_file = st.file_uploader("🖼️ 上传房源详情图", type=['png', 'jpg', 'jpeg'])
    
    # 初始化输入框默认值
    if "ai_val" not in st.session_state:
        st.session_state.ai_val = {"name": "", "station": "", "rent": 80000, "admin": 5000, "initial": 0}

    if up_file and st.button("🔍 AI 自动分析照片内容"):
        with st.spinner("AI 正在读取资料..."):
            res = analyze_house_image(up_file)
            if res: st.session_state.ai_val = res

    c1, c2 = st.columns(2)
    name_in = c1.text_input("🏠 房源名称", value=st.session_state.ai_val.get("name", ""))
    loc_in = c2.text_input("📍 最近车站", value=st.session_state.ai_val.get("station", ""))
    
    r1, r2, r3 = st.columns(3)
    rent_in = r1.number_input("💰 月租", value=int(st.session_state.ai_val.get("rent", 0)))
    adm_in = r2.number_input("🏢 管理费", value=int(st.session_state.ai_val.get("admin", 0)))
    ini_in = r3.number_input("🔑 初期资金投入", value=int(st.session_state.ai_val.get("initial", 0)))

    if st.button("🚀 计算通勤并添加到清单", use_container_width=True):
        with st.spinner("解析路径中..."):
            s_d = get_transit(loc_in, dest_school)
            j_d = get_transit(loc_in, dest_juku)
            img_b64 = f"data:image/png;base64,{base64.b64encode(up_file.getvalue()).decode()}" if up_file else ""
            if s_d and j_d:
                new_data = pd.DataFrame([{
                    "房源名称": name_in, "房源位置": loc_in, "房源图片": img_b64,
                    "月房租(円)": rent_in, "管理费(円)": adm_in, "初期资金投入": ini_in,
                    "学时(分)": s_d['mins'], "学费(单程)": s_d['yen'], "学定期(月)": s_d.get('pass', 0),
                    "塾时(分)": j_d['mins'], "塾费(单程)": j_d['yen'], "塾定期(月)": j_d.get('pass', 0)
                }])
                st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_data], ignore_index=True)
                st.rerun()

# C. 数据清单与排序展示 (含报错修复逻辑)
st.subheader("📝 房源数据清单")
# 数据预清洗：强制转换数值，处理空行导致的 ValueError
for col in ["月房租(円)", "管理费(円)", "初期资金投入", "学费(单程)", "学定期(月)", "塾费(单程)", "塾定期(月)"]:
    st.session_state.df_houses[col] = pd.to_numeric(st.session_state.df_houses[col], errors='coerce').fillna(0)

edited_df = st.data_editor(st.session_state.df_houses, num_rows="dynamic", use_container_width=True)
st.session_state.df_houses = edited_df

if not edited_df.empty:
    st.divider()
    st.subheader(f"📊 综合成本排序 (居住 {stay_months} 个月)")
    
    report_list = []
    for _, row in edited_df.iterrows():
        try:
            if not row["房源名称"]: continue
            # 基础成本计算
            commute = (row["学费(单程)"] * 2 * days_school + row["塾费(单程)"] * 2 * days_juku) * 4.33
            monthly_base = row["月房租(円)"] + row["管理费(円)"] + commute + base_living
            amortized_init = row["初期资金投入"] / (stay_months if stay_months > 0 else 1)
            total = monthly_base + amortized_init
            
            report_list.append({"data": row, "total": total, "base": monthly_base, "amort": amortized_init})
        except: continue

    # 按总支出升序排列
    sorted_data = sorted(report_list, key=lambda x: x['total'])
    
    for i, item in enumerate(sorted_data):
        r = item['data']
        with st.container(border=True):
            col_img, col_txt = st.columns([1, 4])
            with col_img:
                if r["房源图片"]: st.image(r["房源图片"])
            with col_txt:
                st.markdown(f"### {'🥇 ' if i==0 else ''}{r['房源名称']} ({r['房源位置']})")
                st.write(f"📈 **实际月均总支出: {int(item['total']):,}(円)**")
                st.write(f"🏠 固定月开销: {int(item['base']):,} | 🔑 初期分摊: +{int(item['amort']):,}/月")


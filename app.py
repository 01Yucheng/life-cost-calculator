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
            self.file_path = "housing_data.csv"
        except Exception as e:
            st.error("❌ GitHub 配置错误，请检查 Secrets")
            st.stop()

    def load_data(self):
        try:
            content = self.repo.get_contents(self.file_path)
            return pd.read_csv(io.StringIO(content.decoded_content.decode('utf-8-sig')))
        except:
            return pd.DataFrame(columns=["房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学费(单程)", "塾费(单程)", "通勤时间"])

    def save_data(self, df):
        csv_content = df.to_csv(index=False, encoding='utf-8-sig')
        try:
            contents = self.repo.get_contents(self.file_path)
            self.repo.update_file(self.file_path, "update", csv_content, contents.sha)
        except:
            self.repo.create_file(self.file_path, "init", csv_content)

# --- 3. AI 初始化 (修复 404 关键点) ---
storage = GitHubStorage()
if "df_houses" not in st.session_state:
    st.session_state.df_houses = storage.load_data()

@st.cache_resource
def init_ai():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 针对 v1beta 报错的终极对策：尝试不带 models/ 前缀
    return genai.GenerativeModel("gemini-1.5-flash")

model = init_ai()

# --- 4. 功能函数 ---
def process_and_compress_img(uploaded_file):
    """解决 PNG OSError 并压缩图片"""
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((400, 400))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"

def get_ai_commute(loc, s_dest, j_dest):
    """模拟 Google Maps 逻辑获取数据并显示回显"""
    prompt = f"""
    你现在是 Google Maps 交通 API。请分析日本通勤数据：
    起点: {loc}
    终点1: {s_dest}
    终点2: {j_dest}
    必须返回 JSON 格式: {{"s_yen":整数,"j_yen":整数,"s_mins":整数,"j_mins":整数}}
    """
    try:
        res = model.generate_content(prompt)
        raw_text = res.text
        
        # 调试回显：让你在界面上直接看到 AI 吐了什么数据
        with st.expander("🔍 AI 原始数据调试 (点击展开)"):
            st.code(raw_text)
            
        # 提取 JSON 内容
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        raise ValueError("AI 未返回有效 JSON")
    except Exception as e:
        st.error(f"🚨 交通计算失败: {str(e)}") # 这里会显示 404 等具体错误
        return {"s_yen": 200, "j_yen": 200, "s_mins": 99, "j_mins": 99}

# --- 5. UI: 输入与设置 ---
with st.sidebar:
    st.header("⚙️ 生活参数")
    base_living = st.number_input("🍔 月固定生活费", value=60000)
    days_school = st.slider("🏫 学校通勤天数", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤天数", 0.0, 7.0, 0.5, step=0.5)
    dest_school = st.text_input("📍 学校位置", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("📍 私塾位置", value="东京都荒川区西日暮里2-12-5")

with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        name_in = st.text_input("🏠 房源名称")
        loc_in = st.text_input("📍 车站名 (例: 西荻窪駅)")
        rent_in = st.number_input("💰 预估月租", value=80000)
    with c2:
        up_file = st.file_uploader("🖼️ 房源照片", type=['jpg','jpeg','png'])

    if st.button("🚀 AI 分析并保存", use_container_width=True):
        if loc_in:
            with st.spinner("正在检索交通数据..."):
                commute = get_ai_commute(loc_in, dest_school, dest_juku)
                img_data = process_and_compress_img(up_file) if up_file else ""
                
                # 拼接时间字符串显示在卡片上
                time_info = f"🏫至学校 {commute['s_mins']}分 | 🎨至私塾 {commute['j_mins']}分"
                
                new_row = pd.DataFrame([{
                    "房源名称": name_in or f"{loc_in}房源",
                    "房源位置": loc_in,
                    "房源图片": img_data,
                    "月房租(円)": rent_in,
                    "管理费(円)": 5000,
                    "学费(单程)": commute['s_yen'],
                    "塾费(单程)": commute['j_yen'],
                    "通勤时间": time_info
                }])
                st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                storage.save_data(st.session_state.df_houses)
                st.rerun()

# --- 6. 数据列表 ---
st.subheader("📝 房源数据清单")
st.data_editor(st.session_state.df_houses, use_container_width=True)

if st.button("🚨 清空所有数据"):
    st.session_state.df_houses = pd.DataFrame(columns=["房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学费(单程)", "塾费(单程)", "通勤时间"])
    storage.save_data(st.session_state.df_houses)
    st.rerun()

# --- 7. 对比报告 ---
if not st.session_state.df_houses.empty:
    st.divider()
    st.subheader("📊 房源对比报告")
    for idx, row in st.session_state.df_houses.iterrows():
        try:
            fare_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
            total_m = float(row["月房租(円)"]) + float(row["管理费(円)"]) + fare_m + base_living
            
            with st.container(border=True):
                i_col, t_col, b_col = st.columns([1.5, 3, 1.2])
                with i_col:
                    if row["房源图片"]: st.image(row["房源图片"])
                with t_col:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.markdown(f"#### 💰 月支出: **{int(total_m):,} 円**")
                    st.write(f"🏠 房租: {int(float(row['月房租(円)'])+float(row['管理费(円)'])):,} | 🚇 月通勤费: {int(fare_m):,}")
                    st.write(f"🕒 **{row['通勤时间']}**") # 实时显示分钟数
                with b_col:
                    m_api = "https://www.google.com/maps/dir/?api=1"
                    s_url = f"{m_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_school)}&travelmode=transit"
                    j_url = f"{m_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_juku)}&travelmode=transit"
                    st.link_button("🏫 学校地图", s_url, use_container_width=True)
                    st.link_button("🎨 私塾地图", j_url, use_container_width=True)
                    if st.button("🗑️ 删除", key=f"del_{idx}", use_container_width=True):
                        st.session_state.df_houses = st.session_state.df_houses.drop(idx).reset_index(drop=True)
                        storage.save_data(st.session_state.df_houses)
                        st.rerun()
        except: continue

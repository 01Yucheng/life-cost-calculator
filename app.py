import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
from github import Github
from io import BytesIO

# --- 1. 初始化与配置 ---
st.set_page_config(page_title="东京生活成本 AI 计算器 Pro", layout="wide", page_icon="🗼")

# 初始化 Gemini
@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel("gemini-1.5-flash")

model = init_ai()

# --- 2. GitHub 云端存储逻辑 ---
def get_github_repo():
    try:
        g = Github(st.secrets["GITHUB_TOKEN"])
        return g.get_repo(st.secrets["REPO_NAME"])
    except Exception as e:
        st.error(f"GitHub 连接失败: {e}")
        return None

def load_data_from_github():
    try:
        repo = get_github_repo()
        file_content = repo.get_contents("house_data.csv")
        return pd.read_csv(BytesIO(file_content.decoded_content))
    except Exception:
        # 如果文件不存在，返回初始化的空表
        return pd.DataFrame(columns=[
            "房源名称", "最近车站", "房源图片", "月房租", "管理费", 
            "学时", "学费", "学定期", "塾时", "塾费", "塾定期", "路线"
        ])

def save_data_to_github(df):
    repo = get_github_repo()
    if not repo: return
    csv_string = df.to_csv(index=False, encoding='utf-8-sig')
    try:
        contents = repo.get_contents("house_data.csv")
        repo.update_file(contents.path, "Update data via Streamlit", csv_string, contents.sha)
        st.toast("✅ 数据已同步至 GitHub!", icon="☁️")
    except Exception:
        repo.create_file("house_data.csv", "Initial commit", csv_string)
        st.toast("🚀 GitHub 数据库初始化成功!", icon="✨")

# --- 3. 工具函数 ---
def get_transit_ai(origin, destination):
    prompt = (
        f"作为日本交通专家，分析从[{origin}]到[{destination}]的通勤。"
        f"只返回一个 JSON 对象: {{\"mins\": 整数, \"yen\": 单程票价, \"pass_month\": 一个月定期券价格, \"line\": \"路线名\"}}"
        f"不要输出任何额外文字。"
    )
    try:
        response = model.generate_content(prompt)
        # 调试信息：如果没反应，先看看 AI 到底说了什么
        # st.write(f"AI Response: {response.text}") 
        
        clean_text = re.sub(r'```json|```', '', response.text).strip()
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        else:
            st.error(f"AI 返回格式错误: {response.text}")
            return None
    except Exception as e:
        st.error(f"AI 调用失败: {str(e)}")
        return None

def img_to_base64(img_file):
    return f"data:image/png;base64,{base64.b64encode(img_file.getvalue()).decode()}"

def get_google_maps_url(origin, dest):
    return f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(origin)}&destination={urllib.parse.quote(dest)}&travelmode=transit"

# --- 4. 页面逻辑与数据加载 ---
if "df_houses" not in st.session_state:
    st.session_state.df_houses = load_data_from_github()

st.title("🗼 东京生活成本 AI 计算器 Pro")

# --- A. 侧边栏配置 ---
with st.sidebar:
    st.header("⚙️ 全局配置")
    dest_school = st.text_input("🏫 学校地址/车站", value="新宿駅")
    dest_juku = st.text_input("🎨 私塾地址/车站", value="西日暮里駅")
    st.divider()
    base_living = st.number_input("🍔 月固定生活费", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 1.0, step=0.5)
    
    st.divider()
    use_pass_option = st.toggle("🎫 自动计算定期券 (最优选)", value=True)
    
    st.subheader("☁️ 云端同步")
    if st.button("💾 保存到 GitHub", use_container_width=True, type="primary"):
        save_data_to_github(st.session_state.df_houses)
    if st.button("🔄 刷新云端数据", use_container_width=True):
        st.session_state.df_houses = load_data_from_github()
        st.rerun()

# --- B. 输入区 ---
with st.expander("➕ 添加新房源", expanded=True):
    col1, col2, col3, col4 = st.columns([2, 2, 1, 2])
    name_in = col1.text_input("房源名称")
    loc_in = col2.text_input("最近车站 (例如: 中野駅)")
    rent_in = col3.number_input("月租", value=75000, step=1000)
    file_in = col4.file_uploader("房源照片", type=['jpg', 'png'])

    if st.button("🚀 AI 分析并添加", use_container_width=True):
        if loc_in:
            with st.spinner("AI 正在计算通勤方案..."):
                s_data = get_transit_ai(loc_in, dest_school)
                j_data = get_transit_ai(loc_in, dest_juku)
                img_data = img_to_base64(file_in) if file_in else ""
                
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in if name_in else f"{loc_in}公寓",
                        "最近车站": loc_in,
                        "房源图片": img_data,
                        "月房租": rent_in,
                        "管理费": 5000,
                        "学时": s_data['mins'],
                        "学费": s_data['yen'],
                        "学定期": s_data['pass_month'],
                        "塾时": j_data['mins'],
                        "塾费": j_data['yen'],
                        "塾定期": j_data['pass_month'],
                        "路线": s_data['line']
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()

# --- C. 数据表格 ---
st.subheader("📝 房源清单")
edited_df = st.data_editor(
    st.session_state.df_houses,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "房源图片": st.column_config.ImageColumn("预览"),
        "月房租": st.column_config.NumberColumn(format="%d 円"),
    }
)
st.session_state.df_houses = edited_df

# --- D. 对比分析报告 ---
if not edited_df.empty:
    st.divider()
    st.subheader("📊 综合对比报告")
    
    for idx, row in edited_df.iterrows():
        # 通勤逻辑计算
        def calc_best(single, monthly, days):
            single_total = single * 2 * days * 4.33
            if use_pass_option and monthly < single_total and monthly > 0:
                return monthly, "定期券"
            return single_total, "刷卡"

        cost_s, strat_s = calc_best(row['学费'], row['学定期'], days_school)
        cost_j, strat_j = calc_best(row['塾费'], row['塾定期'], days_juku)
        
        total_monthly = row['月房租'] + row['管理费'] + cost_s + cost_j + base_living
        
        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 3, 1.2])
            with c1:
                if row["房源图片"]: st.image(row["房源图片"])
                else: st.caption("No Image")
            with c2:
                st.markdown(f"#### {row['房源名称']} ({row['最近车站']})")
                st.write(f"🏠 房租+管理: {int(row['月房租']+row['管理费']):,} 円")
                st.caption(f"🚇 通勤建议: 学校({strat_s}) | 私塾({strat_j}) | 路线: {row['路线']}")
            with c3:
                st.metric("预估月总支出", f"{int(total_monthly):,} 円")
                st.link_button("🗺️ 导航路线", get_google_maps_url(row['最近车站'], dest_school), use_container_width=True)

    if st.button("🗑️ 清空所有数据"):
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        save_data_to_github(st.session_state.df_houses)
        st.rerun()


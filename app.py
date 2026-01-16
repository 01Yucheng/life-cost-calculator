import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
from github import Github 
from io import BytesIO    

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
        return pd.DataFrame(columns=[
            "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
            "初期投入总额", "礼金押金描述", "学时(分)", "学费(单程)", "学定期(月)", 
            "塾时(分)", "塾费(单程)", "塾定期(月)", "线路概要"
        ])

def save_data_to_github(df):
    repo = get_github_repo()
    if not repo: return
    csv_string = df.to_csv(index=False, encoding='utf-8-sig')
    try:
        contents = repo.get_contents("house_data.csv")
        repo.update_file(contents.path, "Update from AI Calculator", csv_string, contents.sha)
        st.success("✅ 数据已同步至 GitHub!")
    except Exception:
        repo.create_file("house_data.csv", "Initial commit", csv_string)
        st.success("🚀 GitHub 数据库已初始化!")

# --- 3. 工具函数 ---
def get_transit(origin, destination):
    prompt = (
        f"作为日本交通专家，请分析从[{origin}]到[{destination}]的通勤。"
        f"请返回且仅返回一个 JSON 对象，格式如下：\n"
        f"{{\"mins\": 整数, \"yen\": 单程票价整数, \"pass_month\": 一个月定期券预估价格整数, \"line\": \"路线简称\"}}\n"
        f"注意：定期券价格约为单程的15-20倍。不要输出任何 Markdown 标签或解释文字。"
    )
    try:
        response = model.generate_content(prompt)
        clean_text = re.sub(r'```json|```', '', response.text).strip()
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        st.error(f"AI 交通解析出错: {e}")
        return None

def img_to_base64(img_file):
    return f"data:image/png;base64,{base64.b64encode(img_file.getvalue()).decode()}"

def get_google_maps_url(origin, dest):
    base = "https://www.google.com/maps/dir/"
    return f"{base}{urllib.parse.quote(origin)}/{urllib.parse.quote(dest)}/data=!4m2!4m1!3e3"

# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

with st.sidebar:
    st.header("⚙️ 全局设置")
    dest_school = st.text_input("🏫 学校地址/车站", value="东京都新宿区百人町2-24-12 (美都里慕)")
    dest_juku = st.text_input("🎨 私塾地址/车站", value="东京都荒川区西日暮里2-12-5 (尚艺舍)")
    st.divider()
    
    stay_months = st.slider("📅 预计居住时间 (月)", min_value=1, max_value=48, value=24)
    base_living = st.number_input("🍔 月固定基本生活费", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    
    st.divider()
    use_pass_option = st.toggle("🎫 考虑定期券方案", value=True)
    
    st.subheader("☁️ 云端同步")
    if st.button("💾 保存当前到 GitHub", use_container_width=True, type="primary"):
        save_data_to_github(st.session_state.df_houses)
    if st.button("🔄 从 GitHub 刷新", use_container_width=True):
        st.session_state.df_houses = load_data_from_github()
        st.rerun()

if "df_houses" not in st.session_state:
    st.session_state.df_houses = load_data_from_github()

# B. AI 输入区
with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1.5, 1.5, 1])
        name_in = n_col.text_input("🏠 房源名称")
        loc_in = l_col.text_input("📍 最近车站")
        rent_in = r_col.number_input("💰 月租(円)", value=80000)
        
        i_col1, i_col2 = st.columns(2)
        initial_total_in = i_col1.number_input("🔑 初期投入总额(円)", value=0, step=10000)
        rei_shiki_desc_in = i_col2.text_input("💴 礼押详情备注", placeholder="如：礼1押1")
    
    with c2:
        uploaded_file = st.file_uploader("🖼️ 房源照片", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 AI 自动计算并添加", use_container_width=True):
        if loc_in:
            with st.spinner("AI 正在计算最佳路径..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                img_data = img_to_base64(uploaded_file) if uploaded_file else ""
                
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in if name_in else f"{loc_in}房源",
                        "房源位置": loc_in,
                        "房源图片": img_data,
                        "月房租(円)": rent_in,
                        "管理费(円)": 5000,
                        "初期投入总额": initial_total_in,
                        "礼金押金描述": rei_shiki_desc_in,
                        "学时(分)": s_data['mins'],
                        "学费(单程)": s_data['yen'],
                        "学定期(月)": s_data.get('pass_month', s_data['yen'] * 18),
                        "塾时(分)": j_data['mins'],
                        "塾费(单程)": j_data['yen'],
                        "塾定期(月)": j_data.get('pass_month', j_data['yen'] * 18),
                        "线路概要": s_data['line']
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()

# C. 数据清单表
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "房源图片": st.column_config.ImageColumn("预览"),
        "初期投入总额": st.column_config.NumberColumn(format="%d 円"),
    },
    key="house_editor_pro"
)
st.session_state.df_houses = edited_df

# D. 报告生成与自动排序
if not edited_df.empty:
    st.divider()
    st.subheader(f"📊 房源推荐 (按月均综合成本由低到高排序)")

    # 预计算所有房源的综合成本并存入列表
    report_list = []
    for idx, row in edited_df.iterrows():
        try:
            s_pay = float(row["学费(单程)"]) * 2 * days_school * 4.33
            s_pass = float(row["学定期(月)"])
            best_s = min(s_pay, s_pass) if use_pass_option else s_pay
            
            j_pay = float(row["塾费(单程)"]) * 2 * days_juku * 4.33
            j_pass = float(row["塾定期(月)"])
            best_j = min(j_pay, j_pass) if use_pass_option else j_pay
            
            monthly_fixed = float(row["月房租(円)"]) + float(row["管理费(円)"]) + best_s + best_j + base_living
            amortized_initial = float(row["初期投入总额"]) / stay_months
            grand_total = monthly_fixed + amortized_initial
            
            report_list.append({
                "data": row,
                "grand_total": grand_total,
                "monthly_fixed": monthly_fixed,
                "amortized_initial": amortized_initial
            })
        except: continue
    
    # 执行排序逻辑：按 grand_total 升序
    sorted_reports = sorted(report_list, key=lambda x: x['grand_total'])

    # 循环渲染排序后的卡片
    for i, item in enumerate(sorted_reports):
        row = item['data']
        with st.container(border=True):
            # 第一名房源加上皇冠标识
            rank_icon = "🥇 " if i == 0 else ""
            img_c, info_c, btn_c = st.columns([1.5, 3, 1])
            with img_c:
                if row["房源图片"]: st.image(row["房源图片"], use_container_width=True)
            with info_c:
                st.markdown(f"### {rank_icon}{row['房源名称']} ({row['房源位置']})")
                st.write(f"📈 **实际月均总支出: {int(item['grand_total']):,} 円**")
                st.write(f"🏠 纯月固定: {int(item['monthly_fixed']):,} | 🔑 初期分摊: +{int(item['amortized_initial']):,}/月")
                st.caption(f"⏱️ 耗时: 学校 {row['学时(分)']}分 / 私塾 {row['塾时(分)']}分 | 📝 备注: {row['礼金押金描述']}")
            with btn_c:
                st.link_button(f"🏫 学校地图", get_google_maps_url(row['房源位置'], dest_school), use_container_width=True)
                st.link_button(f"🎨 私塾地图", get_google_maps_url(row['房源位置'], dest_juku), use_container_width=True)

    if st.button("🗑️ 清空所有数据"):
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        st.rerun()

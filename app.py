import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
from github import Github  # 新增依赖
from io import BytesIO    # 新增依赖

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
        target = "models/gemini-1.5-flash"
        return genai.GenerativeModel(target if target in models else models[0])
    except Exception as e:
        st.error(f"AI 初始化失败: {e}")
        st.stop()

model = init_ai()

# --- 2. 新增：GitHub 数据同步工具 ---
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
        # 保持与初始化 Session State 相同的列结构
        return pd.DataFrame(columns=[
            "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
            "学时(分)", "学费(单程)", "学定期(月)", "塾时(分)", "塾费(单程)", "塾定期(月)", "线路概要"
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
    """严格保持原有的 AI 交通解析逻辑"""
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

# A. 侧边栏：核心参数与目的地
with st.sidebar:
    st.header("⚙️ 设置")
    dest_school = st.text_input("🏫 学校地址/车站", value="东京都新宿区百人町2-24-12 (美都里慕)")
    dest_juku = st.text_input("🎨 私塾地址/车站", value="东京都荒川区西日暮里2-12-5 (尚艺舍)")
    st.divider()
    base_living = st.number_input("🍔 月固定生活费", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    
    # 新增：定期券询问选项
    st.divider()
    use_pass_option = st.toggle("🎫 考虑定期券方案", value=True, help="开启后，系统会自动对比定期券与单次IC卡费用，取最低值。")
    
    # 新增：云端同步按钮
    st.subheader("☁️ 云端同步")
    if st.button("💾 保存当前到 GitHub", use_container_width=True, type="primary"):
        save_data_to_github(st.session_state.df_houses)
    if st.button("🔄 从 GitHub 刷新", use_container_width=True):
        st.session_state.df_houses = load_data_from_github()
        st.rerun()

# 初始化 Session State (从 GitHub 加载或本地初始化)
if "df_houses" not in st.session_state:
    st.session_state.df_houses = load_data_from_github()

# B. AI 输入与图片拖拽区
with st.expander("➕ 录入新房源 (可拖入照片)", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1.5, 1.5, 1])
        name_in = n_col.text_input("🏠 房源名称", placeholder="例如：中野新村")
        loc_in = l_col.text_input("📍 最近车站", placeholder="例如：中野駅")
        rent_in = r_col.number_input("💰 预估月租", value=80000)
    
    with c2:
        uploaded_file = st.file_uploader("🖼️ 房源照片/截图", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 AI 自动计算并添加", use_container_width=True):
        if loc_in:
            with st.spinner("AI 正在计算最佳路径与定期券..."):
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
        "月房租(円)": st.column_config.NumberColumn(format="%d"),
    },
    key="house_editor_pro"
)
st.session_state.df_houses = edited_df

# --- D. 房源开销对比分析报告 ---
if not edited_df.empty:
    st.divider()
    st.subheader("📊 房源开销对比分析报告")
    
    csv_data = edited_df.drop(columns=["房源图片"]).to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 下载数据表 (CSV)", csv_data, "tokyo_living_pro.csv", "text/csv")

    for idx, row in edited_df.iterrows():
        try:
            # 1. 计算学校通勤费 (考虑开关)
            s_pay_per_ride = float(row["学费(单程)"]) * 2 * days_school * 4.33
            s_pass_monthly = float(row["学定期(月)"])
            
            if use_pass_option:
                best_s_commute = min(s_pay_per_ride, s_pass_monthly)
                s_advice = '购买定期券' if s_pass_monthly < s_pay_per_ride else '单次刷卡'
            else:
                best_s_commute = s_pay_per_ride
                s_advice = '单次刷卡(已禁用定期券)'
            
            # 2. 计算私塾通勤费 (考虑开关)
            j_pay_per_ride = float(row["塾费(单程)"]) * 2 * days_juku * 4.33
            j_pass_monthly = float(row["塾定期(月)"])
            
            if use_pass_option:
                best_j_commute = min(j_pay_per_ride, j_pass_monthly)
                j_advice = '购买定期券' if j_pass_monthly < j_pay_per_ride else '单次刷卡'
            else:
                best_j_commute = j_pay_per_ride
                j_advice = '单次刷卡(已禁用定期券)'
            
            # 总计
            total_m = float(row["月房租(円)"]) + float(row["管理费(円)"]) + best_s_commute + best_j_commute + base_living
            
            with st.container(border=True):
                img_c, info_c, btn_c = st.columns([1.5, 3, 1])
                
                with img_c:
                    if row["房源图片"]:
                        st.image(row["房源图片"], use_container_width=True)
                    else:
                        st.caption("📷 暂无照片")
                
                with info_c:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.write(f"💰 **预估月总支出: {int(total_m):,} 円**")
                    st.write(f"🏠 房租+管理: {int(float(row['月房租(円)'])+float(row['管理费(円)'])):,} | 🚇 最佳月通勤: {int(best_s_commute + best_j_commute):,}")
                    # 此处已将“线路概要”替换为“单程耗时”
                    st.caption(f"⏱️ 单程耗时: 学校 {row['学时(分)']}分 / 私塾 {row['塾时(分)']}分 | 建议：学校-{s_advice} / 私塾-{j_advice}")
                
                with btn_c:
                    st.link_button(f"🏫 学校地图", get_google_maps_url(row['房源位置'], dest_school), use_container_width=True)
                    st.link_button(f"🎨 私塾地图", get_google_maps_url(row['房源位置'], dest_juku), use_container_width=True)
        except Exception as e:
            continue

    if st.button("🗑️ 清空所有数据"):
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        st.rerun()

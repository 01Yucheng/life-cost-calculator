import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64

# --- 1. 配置与 AI 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器 Pro", layout="wide", page_icon="🗼")

@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    try:
        # 优先使用 flash 模型，速度快且便宜
        return genai.GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        st.error(f"AI 初始化失败: {e}")
        st.stop()

model = init_ai()

# --- 2. 工具函数 ---
def get_transit(origin, destination):
    """AI 交通解析函数 - 增强了 JSON 稳定性"""
    prompt = (
        f"作为日本交通专家，分析从[{origin}]到[{destination}]的通勤。"
        f"请仅返回一个 JSON 对象，格式如下：\n"
        f"{{\"mins\": 整数, \"yen\": 单程票价整数, \"line\": \"路线简称\"}}\n"
        f"不要输出任何其他文字。"
    )
    try:
        response = model.generate_content(prompt)
        # 清洗可能存在的 Markdown 标签 (```json ... ```)
        clean_text = re.sub(r'```json|```', '', response.text).strip()
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        return None

def img_to_base64(img_file):
    """处理拖入图片的 Base64 转换"""
    return f"data:image/png;base64,{base64.b64encode(img_file.getvalue()).decode()}"

def get_google_maps_url(origin, dest):
    """生成正确的 Google Maps 路线链接"""
    base = "https://www.google.com/maps/dir/?api=1"
    params = {
        "origin": origin,
        "destination": dest,
        "travelmode": "transit"
    }
    return f"{base}&{urllib.parse.urlencode(params)}"

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

# A. 侧边栏：核心参数与目的地
with st.sidebar:
    st.header("⚙️ 全局设置")
    dest_school = st.text_input("🏫 学校地址/车站", value="东京都新宿区百人町2-24-12 (美都里慕)")
    dest_juku = st.text_input("🎨 私塾地址/车站", value="东京都荒川区西日暮里2-12-5 (尚艺舍)")
    st.divider()
    base_living = st.number_input("🍔 每月伙食/杂费 (円)", value=60000, step=5000)
    
    st.subheader("📅 通勤频率")
    days_school = st.slider("学校 (天/周)", 1, 7, 5)
    days_juku = st.slider("私塾 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    
    use_commuter_pass = st.toggle("使用定期券 (Commuter Pass)", value=True, help="开启后，月通勤费将按单程票价约15倍计算，通常比单次买便宜")

# 初始化 Session State
if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
    ])

# B. AI 输入区
with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1.5, 1.5, 1])
        name_in = n_col.text_input("🏠 房源名称（可选）")
        loc_in = l_col.text_input("📍 靠近哪个车站？", placeholder="例如：中野站")
        rent_in = r_col.number_input("💰 房租 (円)", value=80000, step=1000)
    
    with c2:
        uploaded_file = st.file_uploader("🖼️ 上传/拖入房源图", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 AI 自动分析通勤并添加", use_container_width=True):
        if loc_in:
            with st.spinner("AI 正在查询换乘案内..."):
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
                        "塾时(分)": j_data['mins'],
                        "塾费(单程)": j_data['yen'],
                        "线路概要": s_data['line']
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()
        else:
            st.warning("请输入车站名称！")

# C. 数据编辑器
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "房源图片": st.column_config.ImageColumn("预览"),
        "月房租(円)": st.column_config.NumberColumn(format="%d"),
        "管理费(円)": st.column_config.NumberColumn(format="%d"),
    },
    key="house_editor_v2"
)
st.session_state.df_houses = edited_df

# D. 深度分析报告
if not edited_df.empty:
    st.divider()
    st.subheader("📊 房源月开销深度对比")
    
    for idx, row in edited_df.iterrows():
        try:
            # 计算各项开销
            rent = float(row["月房租(円)"])
            m_fee = float(row["管理费(円)"])
            s_fare = float(row["学费(单程)"])
            j_fare = float(row["塾费(单程)"])
            
            # 通勤费计算逻辑 (整合新功能：定期券)
            if use_commuter_pass:
                # 日本定期券通常 1 个月价格约为单程票价的 15-20 倍
                commute_m = (s_fare * 15) + (j_fare * 15 if days_juku > 0 else 0)
            else:
                commute_m = (s_fare * 2 * days_school + j_fare * 2 * days_juku) * 4.33
            
            total_m = rent + m_fee + commute_m + base_living
            
            with st.container(border=True):
                img_c, info_c, btn_c = st.columns([1, 2.5, 1])
                
                with img_c:
                    if row["房源图片"]:
                        st.image(row["房源图片"], use_container_width=True)
                    else:
                        st.write("📷 无图")
                
                with info_c:
                    st.markdown(f"#### {row['房源名称']} ({row['房源位置']})")
                    col_a, col_b = st.columns(2)
                    col_a.metric("预估月总支出", f"{int(total_m):,} 円")
                    col_b.write(f"🏠 房租+管理: **{int(rent+m_fee):,}**")
                    col_b.write(f"🚇 月通勤费: **{int(commute_m):,}**")
                    
                    # 进度条展示支出构成
                    rent_per = (rent + m_fee) / total_m
                    st.write(f"支出占比 (房租 vs 其他):")
                    st.progress(rent_per)
                    st.caption(f"线路：{row['线路概要']}")
                
                with btn_c:
                    # 整合修复后的地图功能
                    st.link_button("🏫 学校路线", get_google_maps_url(row['房源位置'], dest_school), use_container_width=True)
                    st.link_button("🎨 私塾路线", get_google_maps_url(row['房源位置'], dest_juku), use_container_width=True)

    # 底部操作
    c_left, c_right = st.columns([1, 4])
    if c_left.button("🗑️ 清空数据"):
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        st.rerun()
    
    csv_data = edited_df.drop(columns=["房源图片"]).to_csv(index=False).encode('utf-8-sig')
    c_right.download_button("📥 导出对比表 (CSV)", csv_data, "tokyo_living_report.csv", "text/csv")

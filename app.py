import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64

# --- 1. 配置与 AI 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

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

# --- 2. 工具函数 ---
def get_transit(origin, destination):
    """AI 交通解析函数"""
    prompt = f"日本交通分析 JSON：起点[{origin}]，终点[{destination}]。返回:{{'mins':整数,'yen':整数,'line':'简述'}}"
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        return None

def img_to_base64(img_file):
    """处理拖入图片的 Base64 转换"""
    return f"data:image/png;base64,{base64.b64encode(img_file.getvalue()).decode()}"

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器")

# A. 侧边栏：核心参数与目的地
with st.sidebar:
    st.header("⚙️ 设置")
    dest_school = st.text_input("🏫 学校地址/车站", value="东京都新宿区百人町2-24-12 (美都里慕)")
    dest_juku = st.text_input("🎨 私塾地址/车站", value="东京都荒川区西日暮里2-12-5 (尚艺舍)")
    st.divider()
    base_living = st.number_input("🍔 月固定生活费", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)

# 初始化 Session State 数据结构
if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
    ])

# B. AI 输入与图片拖拽区
with st.expander("➕ 录入新房源 (可拖入照片)", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1.5, 1.5, 1])
        name_in = n_col.text_input("🏠 房源名称")
        loc_in = l_col.text_input("📍 车站名")
        rent_in = r_col.number_input("💰 预估月租", value=80000)
    
    with c2:
        uploaded_file = st.file_uploader("🖼️ 拖入房源照片", type=['png', 'jpg', 'jpeg'])

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
                        "学时(分)": s_data['mins'],
                        "学费(单程)": s_data['yen'],
                        "塾时(分)": j_data['mins'],
                        "塾费(单程)": j_data['yen'],
                        "线路概要": s_data['line']
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()

# C. 数据清单表 (双击可修改)
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "房源图片": st.column_config.ImageColumn("预览"),
        "月房租(円)": st.column_config.NumberColumn(format="%d"),
    },
    key="house_editor_final"
)
st.session_state.df_houses = edited_df

# D. 房源开销对比分析报告 (回归并修复)
if not edited_df.empty:
    st.divider()
    st.subheader("📊 房源开销对比分析报告")
    
    # 导出按钮
    csv_data = edited_df.drop(columns=["房源图片"]).to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 下载数据表 (CSV)", csv_data, "tokyo_living.csv", "text/csv")

    for idx, row in edited_df.iterrows():
        try:
            # 数据校验与计算
            rent = float(row["月房租(円)"])
            m_fee = float(row["管理费(円)"])
            s_fare = float(row["学费(单程)"])
            j_fare = float(row["塾费(单程)"])
            
            # 动态计算月度总支出
            commute_m = (s_fare * 2 * days_school + j_fare * 2 * days_juku) * 4.33
            total_m = rent + m_fee + commute_m + base_living
            
            with st.container(border=True):
                img_c, info_c, btn_c = st.columns([1.5, 3, 1])
                
                with img_c:
                    if row["房源图片"]:
                        st.image(row["房源图片"], use_container_width=True)
                    else:
                        st.caption("📷 暂无照片")
                
                with info_c:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.write(f"📉 **预估月总支出: {int(total_m):,} 円**")
                    st.write(f"🏠 房租+管理: {int(rent+m_fee):,} | 🚇 月通勤: {int(commute_m):,}")
                    st.caption(f"线路概要: {row['线路概要']}")
                
                with btn_c:
                    map_url = "https://www.google.com/maps/dir/?api=1"
                    url_s = f"{map_url}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_school)}&travelmode=transit"
                    url_j = f"{map_api if 'map_api' in locals() else map_url}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_juku)}&travelmode=transit"
                    st.link_button(f"🏫 学校地图", url_s, use_container_width=True)
                    st.link_button(f"🎨 私塾地图", url_j, use_container_width=True)
        except Exception as e:
            continue

    if st.button("🗑️ 清空所有数据"):
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        st.rerun()

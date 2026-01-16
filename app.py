import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64

# --- 1. 配置与 AI 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

# 固定目的地
DEST_SCHOOL = "东京都新宿区百人町2-24-12 (美都里慕)"
DEST_JUKU = "东京都荒川区西日暮里2-12-5 (尚艺舍)"

@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 自动获取可用模型
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
    """通过 AI 获取通勤数据"""
    prompt = f"日本交通分析 JSON：起点[{origin}]，终点[{destination}]。返回:{{'mins':整数,'yen':整数,'line':'简述'}}"
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        return None

def img_to_base64(img_file):
    """将拖入的图片转为 base64 以便显示"""
    return f"data:image/png;base64,{base64.b64encode(img_file.getvalue()).decode()}"

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器")

# A. 侧边栏参数设置
with st.sidebar:
    st.header("⚙️ 计算参数设置")
    base_living = st.number_input("🍔 月固定生活费 (食费/杂费)", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    st.caption("注：0.5 天/周 表示两周去一次。")

# 初始化数据表
if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
    ])

# B. AI 输入与图片拖拽区
with st.expander("🤖 录入新房源 (支持图片拖入)", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1.5, 1.5, 1])
        name_in = n_col.text_input("🏠 房源名称", key="input_name")
        loc_in = l_col.text_input("📍 车站名", key="input_loc")
        rent_in = r_col.number_input("💰 预估月租", value=80000, key="input_rent")
    
    with c2:
        uploaded_file = st.file_uploader("🖼️ 拖入房源照片", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 AI 自动分析并添加到清单", use_container_width=True):
        if loc_in:
            with st.spinner(f"正在分析 {loc_in} 的路径..."):
                s_data = get_transit(loc_in, DEST_SCHOOL)
                j_data = get_transit(loc_in, DEST_JUKU)
                
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

# C. 可编辑表格区
st.subheader("📝 房源数据清单 (可手动微调)")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "房源图片": st.column_config.ImageColumn("预览"),
        "月房租(円)": st.column_config.NumberColumn(format="%d"),
        "管理费(円)": st.column_config.NumberColumn(format="%d"),
    },
    key="house_editor"
)
st.session_state.df_houses = edited_df

# D. 最终分析报告
if not edited_df.empty:
    st.divider()
    st.subheader("📊 房源开销对比分析")
    
    for idx, row in edited_df.iterrows():
        # 错误保护：确保数值有效
        try:
            s_f = float(row["学费(单程)"])
            j_f = float(row["塾费(单程)"])
            rent = float(row["月房租(円)"])
            m_fee = float(row["管理费(円)"])
            
            # 这里的计算联动侧边栏滑块
            commute_m = (s_f * 2 * days_school + j_f * 2 * days_juku) * 4.33
            total_m = rent + m_fee + commute_m + base_living
            
            with st.container(border=True):
                img_c, info_c, btn_c = st.columns([1.5, 3, 1])
                with img_c:
                    if row["房源图片"]:
                        st.image(row["房源图片"], use_container_width=True)
                    else:
                        st.caption("📷 暂无图片")
                with info_c:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.write(f"📉 **预估月总支出: {int(total_m):,} 円**")
                    st.write(f"🏠 房租+管理: {int(rent+m_fee):,} | 🚇 月通勤费: {int(commute_m):,}")
                    st.caption(f"交通概要: {row['线路概要']}")
                with btn_c:
                    map_api = "https://www.google.com/maps/dir/?api=1"
                    url_s = f"{map_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(DEST_SCHOOL)}&travelmode=transit"
                    url_j = f"{map_api}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(DEST_JUKU)}&travelmode=transit"
                    st.link_button(f"🏫 学校({row['学时(分)']}m)", url_s, use_container_width=True)
                    st.link_button(f"🎨 私塾({row['塾时(分)']}m)", url_j, use_container_width=True)
        except Exception as e:
            st.error(f"行 {idx} 计算出错，请检查表格数字是否填写完整。")

    # E. 底部公式说明
    st.info(f"**计算公式：** 总支出 = 房租 + 管理费 + (学校通勤费×{days_school}天 + 私塾通勤费×{days_juku}天) × 4.33周 + 生活费基数({base_living:,}円)")

    if st.button("🗑️ 清空所有房源数据"):
        st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
        st.rerun()

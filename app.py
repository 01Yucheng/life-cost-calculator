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
        model = genai.GenerativeModel("gemini-1.5-flash")
        return model
    except Exception as e:
        st.error(f"AI 初始化失败: {e}")
        st.stop()

model = init_ai()

# --- 2. 增强型工具函数 ---
def get_transit(origin, destination):
    """AI 交通解析函数 - 支持定期券计算与强力 JSON 解析"""
    prompt = (
        f"你是一位日本交通专家。请分析从[{origin}]到[{destination}]的通勤路线。"
        f"请仅返回一个纯 JSON 对象（不要包含 Markdown 代码块），格式如下：\n"
        f"{{\"mins\": 整数分钟, \"yen\": 单程票价整数, \"pass\": 一个月定期券预估价格, \"line\": \"路线简称\"}}"
    )
    try:
        response = model.generate_content(prompt)
        # 清除可能存在的 Markdown 代码块标签
        text = response.text
        text = re.sub(r'```json|```', '', text).strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"解析错误: {e}")
        return None

def img_to_base64(img_file):
    """处理图片转换"""
    return f"data:image/png;base64,{base64.b64encode(img_file.getvalue()).decode()}"

def get_google_maps_url(origin, dest):
    """构建准确的 Google Maps 路线链接"""
    base_url = "https://www.google.com/maps/dir/?api=1"
    params = {
        "origin": origin,
        "destination": dest,
        "travelmode": "transit"
    }
    return f"{base_url}&{urllib.parse.urlencode(params)}"

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

with st.sidebar:
    st.header("⚙️ 全局设置")
    dest_school = st.text_input("🏫 学校地址/车站", value="东京都新宿区百人町2-24-12 (美都里慕)")
    dest_juku = st.text_input("🎨 私塾地址/车站", value="东京都荒川区西日暮里2-12-5 (尚艺舍)")
    st.divider()
    base_living = st.number_input("🍔 个人基础生活费 (食/宿外)", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    st.info("💡 提示：系统会自动根据出勤天数判断买定期券(月票)是否更划算。")

# 初始化数据
if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
        "学费_单程", "学费_月额", "塾费_单程", "塾费_月额", "线路概要"
    ])

# B. AI 录入区
with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1.5, 1.5, 1])
        name_in = n_col.text_input("🏠 房源名称", placeholder="例如：西武新宿宿舍")
        loc_in = l_col.text_input("📍 车站名", placeholder="例如：高田马场")
        rent_in = r_col.number_input("💰 月租(含管)", value=75000)
    
    with c2:
        uploaded_file = st.file_uploader("🖼️ 房源/地图截图", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 AI 自动计算并添加", use_container_width=True):
        if loc_in:
            with st.spinner(f"正在分析从 {loc_in} 出发的通勤方案..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                img_data = img_to_base64(uploaded_file) if uploaded_file else ""
                
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in if name_in else f"{loc_in}房源",
                        "房源位置": loc_in,
                        "房源图片": img_data,
                        "月房租(円)": rent_in,
                        "管理费(円)": 0,  # 假设已包含在月租内，或可手动微调
                        "学费_单程": s_data['yen'],
                        "学费_月额": s_data.get('pass', s_data['yen'] * 20),
                        "塾费_单程": j_data['yen'],
                        "塾费_月额": j_data.get('pass', j_data['yen'] * 20),
                        "线路概要": s_data['line']
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.rerun()

# C. 数据管理
st.subheader("📝 房源对比清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "房源图片": st.column_config.ImageColumn("预览"),
        "月房租(円)": st.column_config.NumberColumn(format="%d 円"),
    }
)
st.session_state.df_houses = edited_df

# D. 深度报告
if not edited_df.empty:
    st.divider()
    st.subheader("📊 房源对比分析报告")
    
    for idx, row in edited_df.iterrows():
        try:
            # 计算学校月通勤费：对比 (单程*2*天数*4.33) 和 (定期券)
            s_pay_as_you_go = row["学费_单程"] * 2 * days_school * 4.33
            s_commute_m = min(s_pay_as_you_go, row["学费_月额"])
            
            # 计算私塾月通勤费
            j_pay_as_you_go = row["塾费_单程"] * 2 * days_juku * 4.33
            j_commute_m = min(j_pay_as_you_go, row["塾费_月额"])
            
            total_commute = s_commute_m + j_commute_m
            total_m = row["月房租(円)"] + row["管理费(円)"] + total_commute + base_living
            
            with st.container(border=True):
                img_c, info_c, btn_c = st.columns([1.2, 3, 1.2])
                
                with img_c:
                    if row["房源图片"]:
                        st.image(row["房源图片"], use_container_width=True)
                    else:
                        st.caption("📷 无预览图")
                
                with info_c:
                    st.markdown(f"#### {row['房源名称']} ({row['房源位置']})")
                    col_a, col_b = st.columns(2)
                    col_a.metric("预估月总支出", f"{int(total_m):,} 円")
                    col_b.write(f"🏠 房租: {int(row['月房租(円)']):,} 円")
                    col_b.write(f"🚇 月交通: {int(total_commute):,} 円 (已选最省方案)")
                    st.caption(f"📍 路线提示: {row['线路概要']}")
                
                with btn_c:
                    st.link_button("🗺️ 学校路线", get_google_maps_url(row['房源位置'], dest_school), use_container_width=True)
                    st.link_button("🎨 私塾路线", get_google_maps_url(row['房源位置'], dest_juku), use_container_width=True)
        except:
            continue

    if st.button("🗑️ 清空所有数据"):
        st.session_state.df_houses = st.session_state.df_houses.iloc[0:0]
        st.rerun()

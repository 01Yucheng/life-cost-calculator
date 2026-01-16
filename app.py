import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import time

# --- 1. 初始化 (加入缓存以防重复连接) ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide")

@st.cache_resource
def get_model(api_key):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('gemini-1.5-flash')

if "GEMINI_API_KEY" not in st.secrets:
    st.error("🔑 请先在 Secrets 中设置 GEMINI_API_KEY")
    st.stop()

model = get_model(st.secrets["GEMINI_API_KEY"])

# --- 2. 核心目的地 ---
DEST_SCHOOL = "东京都新宿区百人町2-24-12 (美都里慕)"
DEST_JUKU = "东京都荒川区西日暮里2-12-5 (尚艺舍)"

# --- 3. 改进的解析函数 (加入超时和详细日志) ---
def safe_ai_transit(origin, destination, label):
    prompt = f"日本电车通勤分析：起点[{origin}]，终点[{destination}]。严格返回JSON:{{'duration':分钟,'fare':日元,'route':'简短描述'}}"
    try:
        # 增加提示信息
        status.update(label=f"⏳ 正在查询前往{label}的路线...", state="running")
        response = model.generate_content(prompt)
        # 提取JSON
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        st.error(f"AI 访问失败 ({label}): {e}")
    return None

# --- 4. 界面设计 ---
if "house_data" not in st.session_state:
    st.session_state.house_data = []

st.title("🗼 东京生活成本 - AI 自动计算器")

# 输入区
with st.form("input_form", clear_on_submit=True):
    st.subheader("➕ 录入新房源")
    c1, c2 = st.columns(2)
    start_loc = c1.text_input("🏠 房源位置 (如: 西川口, 中野)", key="loc")
    house_rent = c2.number_input("💰 月租(円)", value=80000, step=5000)
    
    submit_btn = st.form_submit_button("🚀 提交并查询 AI 路径")

# --- 5. 处理提交逻辑 (使用 form 保证响应性) ---
if submit_btn:
    if not start_loc:
        st.warning("请先输入房源位置")
    else:
        with st.status("📡 AI 正在工作中...", expanded=True) as status:
            # 查询学校
            data_school = safe_ai_transit(start_loc, DEST_SCHOOL, "学校")
            # 查询私塾
            data_juku = safe_ai_transit(start_loc, DEST_JUKU, "私塾")
            
            if data_school and data_juku:
                new_entry = {
                    "name": f"{start_loc}房源",
                    "rent": house_rent,
                    "origin": start_loc,
                    "s_time": data_school['duration'],
                    "s_fare": data_school['fare'],
                    "j_time": data_juku['duration'],
                    "j_fare": data_juku['fare']
                }
                st.session_state.house_data.append(new_entry)
                status.update(label="✅ 查询完成并已添加到列表！", state="complete", expanded=False)
                time.sleep(1)
                st.rerun() # 强制刷新页面显示新数据

# --- 6. 最终报告展示 (带地图跳转) ---
st.divider()
if st.session_state.house_data:
    st.subheader("📊 房源分析报告")
    for house in st.session_state.house_data:
        with st.container(border=True):
            head, btn1, btn2 = st.columns([3, 1, 1])
            
            # 计算费用 (学校5次/周，私塾0.5次/周)
            commute_monthly = (house['s_fare'] * 10 + house['j_fare'] * 1) * 4.33
            total_cost = house['rent'] + commute_monthly + 60000 # 6万生活费
            
            with head:
                st.markdown(f"### {house['name']}")
                st.write(f"📉 **预估总月耗: {int(total_cost):,} 円**")
                st.caption(f"房租: {house['rent']:,} | 月通勤费: {int(commute_monthly):,}")
            
            with btn1:
                url_s = f"https://www.google.com/maps/dir/?api=1&origin={house['origin']}&destination={urllib.parse.quote(DEST_SCHOOL)}&travelmode=transit"
                st.link_button(f"🏫 学校 ({house['s_time']}min)", url_s, use_container_width=True)
                
            with btn2:
                url_j = f"https://www.google.com/maps/dir/?api=1&origin={house['origin']}&destination={urllib.parse.quote(DEST_JUKU)}&travelmode=transit"
                st.link_button(f"🎨 私塾 ({house['j_time']}min)", url_j, use_container_width=True)
else:
    st.info("尚未录入数据，请在上方输入位置并点击提交。")

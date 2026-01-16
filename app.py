import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import time

# --- 1. 初始化配置 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide")

# 目的地配置
DEST_SCHOOL = "东京都新宿区百人町2-24-12 (美都里慕)"
DEST_JUKU = "东京都荒川区西日暮里2-12-5 (尚艺舍)"

@st.cache_resource
def init_ai_engine():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # 自动寻找可用模型，解决 404 问题
    try:
        # 优先尝试这些名称
        for model_name in ['gemini-1.5-flash', 'gemini-1.5-flash-latest', 'gemini-pro']:
            try:
                model = genai.GenerativeModel(model_name)
                # 测试一下是否可用
                model.generate_content("test", generation_config={"max_output_tokens": 1})
                return model, model_name
            except:
                continue
        
        # 如果上面都失败，列出所有可用模型
        available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if available:
            # 去掉 'models/' 前缀
            best_model = available[0].replace('models/', '')
            return genai.GenerativeModel(best_model), best_model
    except Exception as e:
        st.error(f"无法获取模型列表: {e}")
    st.stop()

model, active_model_name = init_ai_engine()

# --- 2. 核心逻辑 ---
def get_transit_data(origin, destination, label):
    prompt = f"""
    作为日本交通专家，查询起点[{origin}]到终点[{destination}]的电车通勤数据。
    仅返回 JSON 格式：{{"duration": 分钟整数, "fare": 日元整数, "route": "线路描述"}}
    """
    try:
        # 使用更稳健的生成配置
        response = model.generate_content(prompt)
        # 提取 JSON 块
        text = response.text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        st.sidebar.error(f"查询{label}失败: {e}")
    return None

# --- 3. UI 界面 ---
if "house_list" not in st.session_state:
    st.session_state.house_list = []

st.title("🗼 东京生活成本 AI 计算器")
st.caption(f"当前激活模型: {active_model_name}")

with st.form("add_house", clear_on_submit=True):
    st.subheader("➕ 录入新房源")
    col1, col2 = st.columns(2)
    origin_input = col1.text_input("🏠 房源位置 (如: 西川口, 中野)", placeholder="车站名")
    rent_input = col2.number_input("💰 月租(円)", value=80000, step=5000)
    submit = st.form_submit_button("🚀 提交并查询 AI 路径")

if submit and origin_input:
    with st.status("📡 正在获取 AI 交通建议...") as status:
        res_school = get_transit_data(origin_input, DEST_SCHOOL, "学校")
        res_juku = get_transit_data(origin_input, DEST_JUKU, "私塾")
        
        if res_school and res_juku:
            st.session_state.house_list.append({
                "name": f"{origin_input}房源",
                "rent": rent_input,
                "origin": origin_input,
                "school": res_school,
                "juku": res_juku
            })
            status.update(label="✅ 数据已同步！", state="complete")
            st.rerun()

# --- 4. 报告生成 ---
st.divider()
if st.session_state.house_list:
    for h in st.session_state.house_list:
        with st.container(border=True):
            c_info, c_map1, c_map2 = st.columns([3, 1, 1])
            
            # 这里的权重：学校每周5天(10次)，私塾每两周1天(平均每周1次)
            weekly_fare = (h['school']['fare'] * 10) + (h['juku']['fare'] * 1)
            monthly_total = h['rent'] + (weekly_fare * 4.33) + 60000
            
            with c_info:
                st.markdown(f"### {h['name']}")
                st.write(f"📉 **预估总月耗: {int(monthly_total):,} 円**")
                st.caption(f"路线: {h['school']['route']}")
            
            with c_map1:
                url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(h['origin'])}&destination={urllib.parse.quote(DEST_SCHOOL)}&travelmode=transit"
                st.link_button(f"🏫 学校({h['school']['duration']}分)", url, use_container_width=True)
                
            with c_map2:
                url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(h['origin'])}&destination={urllib.parse.quote(DEST_JUKU)}&travelmode=transit"
                st.link_button(f"🎨 私塾({h['juku']['duration']}分)", url, use_container_width=True)
else:
    st.info("等待录入房源数据...")

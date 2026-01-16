import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse

# --- 1. 配置与初始化 (保持不变) ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

def init_gemini():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 未设置 API KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel('gemini-1.5-flash')

model = init_gemini()

# --- 2. 辅助函数：生成 Google Maps 链接 ---
def make_google_maps_link(origin, destination):
    """生成电车通勤的 Google Maps 跳转链接"""
    base_url = "https://www.google.com/maps/dir/?api=1"
    params = {
        "origin": origin,
        "destination": destination,
        "travelmode": "transit" # 强制电车模式
    }
    return f"{base_url}&{urllib.parse.urlencode(params)}"

def ask_ai_transit(origin, destination):
    prompt = f"分析日本交通路线 JSON 格式：起点 {origin}，终点 {destination}。包含 duration, fare, route。"
    try:
        response = model.generate_content(prompt)
        clean_text = re.search(r'\{.*\}', response.text, re.DOTALL).group()
        return json.loads(clean_text)
    except: return None

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 (地图联动版)")

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=[
        "房源名称", "月房租", "起点站", "学校时间", "学校票价", "私塾时间", "私塾票价"
    ])

# 输入区
with st.expander("➕ 添加新房源", expanded=True):
    c1, c2, c3 = st.columns(3)
    start_pt = c1.text_input("🏠 房源位置", "赤羽")
    rent = c2.number_input("💰 月租(円)", 85000)
    
    # 你的固定目的地
    dest_school = "东京都新宿区百人町2-24-12 (美都里慕)"
    dest_juku = "东京都荒川区西日暮里2-12-5 (尚艺舍)"

    if st.button("🚀 AI 一键检索双路径"):
        with st.spinner("正在解析学校与私塾路径..."):
            res_a = ask_ai_transit(start_pt, dest_school)
            res_b = ask_ai_transit(start_pt, dest_juku)
            
            if res_a and res_b:
                new_row = {
                    "房源名称": f"{start_pt}房源",
                    "月房租": rent,
                    "起点站": start_pt,
                    "学校时间": res_a["duration"],
                    "学校票价": res_a["fare"],
                    "私塾时间": res_b["duration"],
                    "私塾票价": res_b["fare"]
                }
                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([new_row])], ignore_index=True)
                st.success("成功录入！")

# --- 4. 最终报告区 ---
st.subheader("📊 房源对比报告 (含地图跳转)")

if not st.session_state.df.empty:
    for idx, row in st.session_state.df.iterrows():
        with st.container(border=True):
            col_info, col_btn_a, col_btn_b = st.columns([3, 1, 1])
            
            # 左侧：基本信息
            with col_info:
                st.markdown(f"### **{row['房源名称']}**")
                # 计算月支出 (学校5次/周, 私塾0.5次/周)
                monthly_transit = (row['学校票价'] * 5 + row['私塾票价'] * 0.5) * 4.33 * 2
                total = row['月房租'] + monthly_transit + 60000
                st.write(f"💵 **预估月总支出: {int(total):,} 円** (房租: {row['月房租']:,} + 交通: {int(monthly_transit):,})")
            
            # 中间：学校地图按钮
            with col_btn_a:
                url_a = make_google_maps_link(row['起点站'], dest_school)
                st.link_button(f"🏫 去学校 ({row['学校时间']}min)", url_a, use_container_width=True)
            
            # 右侧：私塾地图按钮
            with col_btn_b:
                url_b = make_google_maps_link(row['起点站'], dest_juku)
                st.link_button(f"🎨 去私塾 ({row['私塾时间']}min)", url_b, use_container_width=True)

    # 底部原始数据表
    with st.expander("查看原始数据表"):
        st.dataframe(st.session_state.df, use_container_width=True)

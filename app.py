import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re

# --- 1. 页面基本配置 ---
st.set_page_config(
    page_title="东京生活成本 AI 计算器", 
    layout="wide", 
    page_icon="🗼"
)

# --- 2. AI 引擎初始化逻辑 ---
def init_gemini():
    """初始化并检测可用模型，解决 404/403 问题"""
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 未在 Secrets 中检测到 GEMINI_API_KEY。")
        st.stop()
    
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
    
    try:
        # 自动获取当前 Key 拥有的模型列表
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 优先级：1.5-flash > 1.0-pro
        selected_model = ""
        for m in ["models/gemini-1.5-flash", "models/gemini-1.0-pro"]:
            if m in models:
                selected_model = m
                break
        
        if not selected_model and models:
            selected_model = models[0]
            
        if not selected_model:
            st.error("❌ 你的 API Key 暂不支持任何生成模型，请检查 Google Cloud 权限。")
            st.stop()
            
        return genai.GenerativeModel(selected_model), selected_model
    
    except Exception as e:
        st.error(f"❌ API 连接失败: {str(e)}")
        st.info("💡 提示：如果是 403 错误，请前往 Google AI Studio 检查 API Key 是否被封锁或限制。")
        st.stop()

# 初始化 AI
model, model_name = init_gemini()

# --- 3. 核心功能：AI 交通解析 ---
def ask_ai_transit(origin, destination):
    """通过 AI 获取结构化的交通数据"""
    prompt = f"""
    作为日本交通专家，请分析以下路线的单程通勤（早高峰时间）：
    起点：{origin}
    终点：{destination}
    
    必须且只能返回以下 JSON 格式，不要包含 Markdown 格式标记或额外解释：
    {{
        "duration": 整数(分钟),
        "fare": 整数(日元),
        "route": "简短描述"
    }}
    """
    try:
        response = model.generate_content(prompt)
        # 强力清洗：只提取 JSON 部分
        clean_text = re.search(r'\{.*\}', response.text, re.DOTALL).group()
        return json.loads(clean_text)
    except Exception as e:
        st.sidebar.error(f"解析失败: {e}")
        return None

# --- 4. 网页 UI 布局 ---
st.title("🗼 东京生活成本 AI 计算器")
st.caption(f"当前 AI 引擎: {model_name}")

# 初始化房源数据表
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=[
        "房源名称", "月房租(円)", "管理费(円)", "水电网(估)", 
        "食费/生活", "单程时间(分)", "单程票价(円)", "路线概要", "每周天数"
    ])

# A. 数据输入区
with st.container(border=True):
    st.subheader("🤖 AI 自动分析录入")
    c1, c2, c3 = st.columns([2, 2, 1])
    
    with c1:
        start_pt = st.text_input("🏠 房源位置 (例: 新大久保)", placeholder="输入车站名")
    with c2:
        end_pt = st.text_input("🏢 目的地 (例: 早稻田大学)", placeholder="输入学校或公司名")
    with c3:
        rent_input = st.number_input("💰 预估月租(円)", value=85000, step=1000)
        
    if st.button("🚀 询问 AI 并自动填表", use_container_width=True):
        if start_pt and end_pt:
            with st.spinner("AI 正在计算通勤方案..."):
                res = ask_ai_transit(start_pt, end_pt)
                if res:
                    new_row = {
                        "房源名称": f"{start_pt}附近",
                        "月房租(円)": rent_input,
                        "管理费(円)": 5000,
                        "水电网(估)": 15000,
                        "食费/生活": 45000,
                        "单程时间(分)": res["duration"],
                        "单程票价(円)": res["fare"],
                        "路线概要": res["route"],
                        "每周天数": 5
                    }
                    st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([new_row])], ignore_index=True)
                    st.success(f"已录入：{res['route']}，约 {res['duration']} 分钟")
                else:
                    st.warning("⚠️ AI 无法获取该路线，请手动录入。")

# B. 数据编辑区
st.subheader("📋 房源对比清单")
edited_df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)
st.session_state.df = edited_df

# C. 汇总分析区
if not edited_df.empty:
    st.divider()
    # 数据深拷贝用于计算
    calc_df = edited_df.copy().fillna(0)
    
    # 核心计算逻辑：月度成本汇总
    calc_df["月通勤费"] = calc_df["单程票价(円)"] * calc_df["每周天数"] * 4.33 * 2
    calc_df["固定支出"] = calc_df["月房租(円)"] + calc_df["管理费(円)"] + calc_df["水电网(估)"] + calc_df["食费/生活"]
    calc_df["月度总支出"] = calc_df["固定支出"] + calc_df["月通勤费"]
    
    st.subheader("📊 月度财务支出对比")
    
    # 结果展示
    display_df = calc_df[["房源名称", "月度总支出", "月房租(円)", "月通勤费", "单程时间(分)", "路线概要"]]
    st.dataframe(
        display_df.sort_values("月度总支出").style.highlight_min(subset=["月度总支出"], color="#d4edda"),
        use_container_width=True
    )
    
    # 图表分析
    st.bar_chart(data=calc_df, x="房源名称", y="月度总支出", color="#FF4B4B")
    
    with st.expander("📝 计算规则说明"):
        st.write("1. **月度计算**：按每月 4.33 周计算，单程票价乘往返(2)。")
        st.write("2. **AI 逻辑**：数据由 Gemini AI 基于训练集提供，可能存在几十日元的误差。")
        st.write("3. **修改数据**：直接双击表格中的数字即可修改，所有图表会同步更新。")
else:
    st.info("💡 请在上方输入房源和目的地，点击按钮让 AI 帮你计算成本。")

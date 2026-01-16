import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re

# --- 1. 页面与 AI 配置 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

def init_gemini():
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        # 使用 flash 模型，速度最快且免费额度高
        return genai.GenerativeModel('gemini-1.5-flash')
    else:
        st.error("⚠️ 未检测到 GEMINI_API_KEY。请在 Secrets 中配置后再运行。")
        st.stop()

model = init_gemini()

# --- 2. AI 核心逻辑：通勤解析 ---
def ask_ai_transit(origin, destination):
    prompt = f"""
    你是一个日本交通地理专家。请分析以下通勤路径：
    起点：{origin}
    终点：{destination}
    
    请严格按 JSON 格式输出，不要有任何多余文字：
    {{
        "duration": 整数(分钟数),
        "fare": 整数(单程票价日元),
        "route": "字符串(简短路线说明，如：JR山手线直达)"
    }}
    注意：请参考工作日早高峰 8:30 的平均情况。
    """
    try:
        response = model.generate_content(prompt)
        # 提取 JSON 块
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        st.sidebar.error(f"AI 查询出错: {e}")
    return None

# --- 3. UI 界面布局 ---
st.title("🗼 东京生活成本 AI 计算器")
st.markdown("通过 AI 自动评估不同房源的**通勤成本**与**生活总支出**。")

# 初始化 session_state 存储房源数据
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=[
        "房源名称", "月房租(円)", "管理费(円)", "水电网(估)", 
        "食费/生活", "单程时间(分)", "单程票价(円)", "路线概要", "每周天数"
    ])

# --- 4. 交互输入区 ---
with st.container(border=True):
    st.subheader("🤖 AI 自动数据录入")
    c1, c2, c3 = st.columns([2, 2, 1])
    
    with c1:
        start_pt = st.text_input("🏠 房源位置（车站名或地标）", placeholder="例：新大久保")
    with c2:
        end_pt = st.text_input("🏢 目的地（学校/公司）", placeholder="例：早稻田大学")
    with c3:
        rent = st.number_input("💰 房租(円)", value=85000, step=1000)
        
    if st.button("🚀 询问 AI 并添加到对比表", use_container_width=True):
        if start_pt and end_pt:
            with st.spinner("Gemini 正在分析电车数据..."):
                res = ask_ai_transit(start_pt, end_pt)
                if res:
                    new_data = {
                        "房源名称": f"{start_pt}附近",
                        "月房租(円)": rent,
                        "管理费(円)": 5000,
                        "水电网(估)": 15000,
                        "食费/生活": 45000,
                        "单程时间(分)": res["duration"],
                        "单程票价(円)": res["fare"],
                        "路线概要": res["route"],
                        "每周天数": 5
                    }
                    st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([new_data])], ignore_index=True)
                    st.success(f"已获取：从 {start_pt} 到 {end_pt} 大约需 {res['duration']} 分钟")

# --- 5. 数据编辑与计算区 ---
st.subheader("📋 房源对比清单")
# 允许用户手动微调 AI 给出的数据
edited_df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)
st.session_state.df = edited_df

if not edited_df.empty:
    # --- 计算逻辑 ---
    calc_df = edited_df.copy().fillna(0)
    # 月通勤次数：每周天数 * 4.33周 * 2 (往返)
    calc_df["月通勤费"] = calc_df["单程票价(円)"] * calc_df["每周天数"] * 4.33 * 2
    calc_df["月固定成本"] = calc_df["月房租(円)"] + calc_df["管理费(円)"] + calc_df["水电网(估)"] + calc_df["食费/生活"]
    calc_df["预计月总支出"] = calc_df["月固定成本"] + calc_df["月通勤费"]
    
    st.divider()
    
    # --- 6. 最终可视化可视化分析 ---
    st.subheader("📊 汇总分析结果")
    
    # 展示格式化的汇总表
    summary_df = calc_df[["房源名称", "预计月总支出", "月房租(円)", "月通勤费", "单程时间(分)", "路线概要"]].sort_values("预计月总支出")
    st.dataframe(summary_df.style.highlight_min(subset=["预计月总支出"], color="#D4EDDA"), use_container_width=True)

    # 支出构成对比图
    st.bar_chart(data=calc_df, x="房源名称", y="预计月总支出", color="#FF4B4B")
    
    with st.expander("📝 计算备注"):
        st.write("""
        1. **月度换算**：按每月平均 4.33 周计算。
        2. **生活费基数**：默认水电网 1.5w，食费/生活 4.5w，可根据实际情况在表格中修改。
        3. **AI 准确性**：AI 基于模型训练数据估算，建议对于最终选定的路线在 Google Maps 再次确认。
        """)
else:
    st.info("请在上方输入房源位置和目的地，点击按钮开始分析。")

import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re

# --- 1. 配置 ---
st.set_page_config(page_title="东京多房源对比-AI版", layout="wide", page_icon="🗼")

def init_gemini():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 未在 Secrets 中配置 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 优先选择 flash 模型
    return genai.GenerativeModel('gemini-1.5-flash')

model = init_gemini()

# --- 2. 目的地配置 (你的两个固定地点) ---
DESTINATIONS = {
    "学校 (美都里慕)": "东京都新宿区百人町2-24-12 (新大久保站)",
    "私塾 (尚艺舍)": "东京都荒川区西日暮里2-12-5 (西日暮里站)"
}

# --- 3. AI 批量抓取逻辑 ---
def fetch_transit_batch(origins):
    results = []
    # 构造一次性询问的 Prompt，节省 API 调用次数
    origins_str = "、".join(origins)
    prompt = f"""
    你是一个日本交通专家。请分析从以下【起点列表】分别前往两个【目的地】的单程通勤（早高峰）。
    
    起点列表：{origins_str}
    目的地A：{DESTINATIONS["学校 (美都里慕)"]}
    目的地B：{DESTINATIONS["私塾 (尚艺舍)"]}
    
    请严格按以下 JSON 数组格式返回，不要有解释：
    [
      {{
        "origin": "起点名",
        "to_A_min": 整数(分钟), "to_A_yen": 整数(日元), "to_A_route": "描述",
        "to_B_min": 整数(分钟), "to_B_yen": 整数(日元), "to_B_route": "描述"
      }},
      ...
    ]
    """
    try:
        response = model.generate_content(prompt)
        clean_text = re.search(r'\[.*\]', response.text, re.DOTALL).group()
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"AI 批量解析失败: {e}")
        return []

# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 - 多房源批量对比")

# 初始化数据表
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=[
        "房源位置", "月租金(円)", "学校时间(分)", "学校票价(円)", 
        "私塾时间(分)", "私塾票价(円)", "每周前往学校天数", "每周前往私塾天数"
    ])

# A. 批量输入区
with st.expander("➕ 批量添加新房源", expanded=True):
    # 使用 multiselect 允许用户输入并按回车添加多个站名
    input_origins = st.multiselect(
        "输入房源所在车站（支持多个，输完按回车）",
        options=["赤羽", "中野", "高圆寺", "池袋", "板桥"],
        default=[],
        help="你可以直接输入列表里没有的站名，按回车即可添加",
        placeholder="例：赤羽, 中野...",
    )
    
    col_rent, col_btn = st.columns([1, 1])
    default_rent = col_rent.number_input("统一预设月租 (可后期手动修改)", value=80000)
    
    if col_btn.button("🚀 AI 批量分析以上房源", use_container_width=True):
        if input_origins:
            with st.spinner(f"正在分析 {len(input_origins)} 个房源的通勤情况..."):
                batch_res = fetch_transit_batch(input_origins)
                new_rows = []
                for item in batch_res:
                    new_rows.append({
                        "房源位置": item["origin"],
                        "月租金(円)": default_rent,
                        "学校时间(分)": item["to_A_min"],
                        "学校票价(円)": item["to_A_yen"],
                        "私塾时间(分)": item["to_B_min"],
                        "私塾票价(円)": item["to_B_yen"],
                        "每周前往学校天数": 5,
                        "每周前往私塾天数": 1
                    })
                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame(new_rows)], ignore_index=True)
                st.rerun()

# B. 数据编辑区
st.subheader("📋 详细数据对比 (双击可修改数字)")
edited_df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)
st.session_state.df = edited_df

# C. 汇总计算
if not edited_df.empty:
    res = edited_df.copy().fillna(0)
    # 月通勤费 = (学校往返 + 私塾往返) * 4.33周
    res["月通勤费"] = (
        (res["学校票价(円)"] * res["每周前往学校天数"] * 2) + 
        (res["私塾票价(円)"] * res["每周前往私塾天数"] * 2)
    ) * 4.33
    
    res["月预估总支出"] = res["月租金(円)"] + res["月通勤费"] + 60000 # 6万生活费基数
    
    st.divider()
    st.subheader("📊 最终对比报告")
    
    # 重点展示表格
    display_cols = ["房源位置", "月预估总支出", "月租金(円)", "月通勤费", "学校时间(分)"]
    st.dataframe(res[display_cols].sort_values("月预估总支出"), use_container_width=True)
    
    # 图表：横轴房源，纵轴支出
    st.bar_chart(data=res, x="房源位置", y="月预估总支出")

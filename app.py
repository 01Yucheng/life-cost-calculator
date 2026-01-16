import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
import io
from PIL import Image

# --- 1. 配置与 AI 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器", layout="wide", page_icon="🗼")

@st.cache_resource
def init_ai():
    """
    解决 404 错误：修正模型调用路径
    """
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    try:
        # 修复关键点：直接使用 "gemini-1.5-flash" 而非 "models/..."
        # 能够兼容 v1beta 接口，解决 404 找不到模型的问题
        return genai.GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        st.error(f"AI 初始化失败: {e}")
        st.stop()

model = init_ai()

# --- 2. 核心功能函数 ---
def get_transit(origin, destination):
    """
    AI 交通解析：防止出现 99 分默认值
    """
    # 自动补齐车站名，提高 AI 识别成功率
    if origin and not origin.endswith("駅") and "Station" not in origin: 
        origin += "駅"
    
    prompt = f"""
    作为日本交通专家，请估算以下路线（仅需估算，无需实时API）：
    起点: {origin} -> 终点: {destination}
    
    必须且仅返回如下 JSON 格式，不要包含Markdown代码块：
    {{"mins": 整数(单程分钟), "yen": 整数(单程车费), "line": "主要线路名称"}}
    """
    try:
        response = model.generate_content(prompt)
        # 增强解析逻辑：提取文本中的 JSON 部分
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        # 实时捕获错误，防止静默失败
        print(f"Error parsing transit for {origin}: {e}")
        return None

def process_img(img_file):
    """
    修复 PNG OSError：处理透明图层并压缩
    """
    try:
        img = Image.open(img_file)
        # 关键修复：将 RGBA (PNG) 转换为 RGB 格式，防止 JPEG 保存失败
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        # 调整大小，控制 Base64 长度，加快页面加载
        img.thumbnail((400, 400))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except Exception as e:
        st.error(f"图片处理出错: {e}")
        return ""

# --- 3. 页面布局 ---
st.title("🗼 东京生活成本 AI 计算器")

with st.sidebar:
    st.header("⚙️ 生活参数设置")
    dest_school = st.text_input("🏫 学校目的地", value="新宿区百人町2-24-12")
    dest_juku = st.text_input("🎨 私塾目的地", value="荒川区西日暮里2-12-5")
    st.divider()
    base_living = st.number_input("🍔 月固定生活费", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)

if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学费(单程)", "塾费(单程)", "学时", "塾时", "线路"
    ])

# --- 4. 输入与录入 ---
with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1, 1, 1])
        name_in = n_col.text_input("🏠 房源名称")
        # 提示用户输入车站名
        loc_in = l_col.text_input("📍 车站名", placeholder="例如: 西荻窪") 
        rent_in = r_col.number_input("💰 预估月租", value=80000)
    with c2:
        uploaded_file = st.file_uploader("🖼️ 房源照片", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 AI 自动计算并添加", use_container_width=True):
        if loc_in:
            with st.spinner(f"正在分析 {loc_in} 的路径数据..."):
                # 获取数据
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                img_data = process_img(uploaded_file) if uploaded_file else ""
                
                # 校验数据，避免插入空值
                if s_data and j_data:
                    new_row = pd.DataFrame([{
                        "房源名称": name_in if name_in else f"{loc_in}房源",
                        "房源位置": loc_in,
                        "房源图片": img_data,
                        "月房租(円)": rent_in,
                        "管理费(円)": 5000,
                        "学费(单程)": s_data.get('yen', 0),
                        "塾费(单程)": j_data.get('yen', 0),
                        "学时": s_data.get('mins', 0),
                        "塾时": j_data.get('mins', 0),
                        "线路": s_data.get('line', '未知')
                    }])
                    st.session_state.df_houses = pd.concat([st.session_state.df_houses, new_row], ignore_index=True)
                    st.success(f"✅ 已成功添加 {loc_in} 的数据！")
                    st.rerun()
                else:
                    st.error(f"❌ 交通分析失败。请检查输入 '{loc_in}' 是否正确，或稍后重试。")
                    # 显示具体的错误提示

# --- 5. 数据列表与交互 ---
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "房源图片": st.column_config.ImageColumn("预览"),
        "月房租(円)": st.column_config.NumberColumn(format="%d 円"),
        "学时": st.column_config.NumberColumn(format="%d 分"),
    }
)
st.session_state.df_houses = edited_df

# --- 6. 报告卡片展示 ---
if not edited_df.empty:
    st.divider()
    st.subheader("📊 房源对比报告")
    
    for idx, row in edited_df.iterrows():
        try:
            # 计算逻辑
            s_fee = float(row.get("学费(单程)", 0))
            j_fee = float(row.get("塾费(单程)", 0))
            rent = float(row.get("月房租(円)", 0))
            admin = float(row.get("管理费(円)", 0))
            
            commute_total = (s_fee * 2 * days_school + j_fee * 2 * days_juku) * 4.33
            total_monthly = rent + admin + commute_total + base_living
            
            # 卡片 UI
            with st.container(border=True):
                col_img, col_info, col_act = st.columns([1.5, 3, 1.2])
                
                with col_img:
                    if row["房源图片"]:
                        st.image(row["房源图片"], use_container_width=True)
                    else:
                        st.markdown("📷 **暂无图片**")
                
                with col_info:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.markdown(f"## 💰 月总支: **{int(total_monthly):,} 円**")
                    st.caption(f"线路: {row.get('线路', '未知')}")
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("🏠 房租+管理", f"{int(rent+admin):,}")
                    c2.metric("🚇 月交通费", f"{int(commute_total):,}")
                    # 显示真实的时间，而不是 99 分
                    c3.metric("⏱️ 学校通勤", f"{row['学时']}分")

                with col_act:
                    # 地图跳转链接
                    map_url = "https://www.google.com/maps/dir/?api=1"
                    s_url = f"{map_url}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_school)}&travelmode=transit"
                    j_url = f"{map_url}&origin={urllib.parse.quote(row['房源位置'])}&destination={urllib.parse.quote(dest_juku)}&travelmode=transit"
                    
                    st.link_button("🏫 学校路线", s_url, use_container_width=True)
                    st.link_button("🎨 私塾路线", j_url, use_container_width=True)
                    
                    if st.button("🗑️ 删除", key=f"del_{idx}", use_container_width=True):
                        st.session_state.df_houses = st.session_state.df_houses.drop(idx).reset_index(drop=True)
                        st.rerun()
        except Exception as e:
            st.error(f"渲染卡片错误: {e}")

# 清空按钮
if st.button("🚨 清空所有数据"):
    st.session_state.df_houses = st.session_state.df_houses.iloc[0:0]
    st.rerun()

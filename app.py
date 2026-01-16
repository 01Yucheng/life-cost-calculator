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
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # 修复 404 错误：不再使用动态检测，直接指定稳定版本或尝试更具兼容性的名称
    try:
        # 如果 v1beta 报错，通常是由于 models/ 前缀或版本不匹配，此处直接定义
        return genai.GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        st.error(f"🚨 AI 初始化失败: {e}")
        st.stop()

model = init_ai()

# --- 2. 工具函数 ---
def get_transit(origin, destination):
    """AI 交通解析函数：增强了提示词以防止解析失败"""
    # 增加对“駅”字的自动补全，日本交通查询更精准
    if not origin.endswith("駅"): origin += "駅"
    
    prompt = f"""
    作为日本交通专家，请分析以下通勤路径：
    起点：{origin}
    终点：{destination}
    
    请严格返回如下 JSON 格式（不要包含 markdown 代码块）：
    {{"mins": 整数, "yen": 整数, "line": "线路名称简述"}}
    """
    try:
        response = model.generate_content(prompt)
        # 提取第一个匹配的 JSON 结构
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        # 如果失败，在界面显示具体报错原因以便调试
        st.warning(f"交通分析异常 ({origin}): {str(e)}")
        return None

def process_img(img_file):
    """
    处理图片转换并修复 PNG OSError
    1. 转换 RGBA 为 RGB 避免保存失败
    2. 压缩尺寸加快上传速度
    """
    img = Image.open(img_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    # 压缩图片以减少 Base64 长度
    img.thumbnail((500, 500))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"

# --- 3. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器")

with st.sidebar:
    st.header("⚙️ 设置")
    dest_school = st.text_input("🏫 学校地址/车站", value="新宿区百人町2-24-12")
    dest_juku = st.text_input("🎨 私塾地址/车站", value="荒川区西日暮里2-12-5")
    st.divider()
    base_living = st.number_input("🍔 月固定生活费", value=60000, step=5000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)

if "df_houses" not in st.session_state:
    st.session_state.df_houses = pd.DataFrame(columns=[
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", "学时(分)", "学费(单程)", "塾时(分)", "塾费(单程)", "线路概要"
    ])

with st.expander("➕ 录入新房源", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        n_col, l_col, r_col = st.columns([1.5, 1.5, 1])
        name_in = n_col.text_input("🏠 房源名称", placeholder="例如：松田")
        loc_in = l_col.text_input("📍 车站名", placeholder="例如：新大久保")
        rent_in = r_col.number_input("💰 预估月租", value=80000)
    
    with c2:
        uploaded_file = st.file_uploader("🖼️ 房源照片", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 AI 自动计算并添加", use_container_width=True):
        if loc_in:
            with st.spinner(f"正在分析 {loc_in} 的交通数据..."):
                s_data = get_transit(loc_in, dest_school)
                j_data = get_transit(loc_in, dest_juku)
                img_data = process_img(uploaded_file) if uploaded_file else ""
                
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
                    st.success("✅ 添加成功！")
                    st.rerun()
                else:
                    st.error("❌ 交通数据解析失败，请检查模型权限或输入。")

# --- 4. 数据展示与对比 ---
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "房源图片": st.column_config.ImageColumn("预览"),
        "月房租(円)": st.column_config.NumberColumn(format="%d"),
    },
    key="house_editor_v2"
)
st.session_state.df_houses = edited_df

if not edited_df.empty:
    st.divider()
    st.subheader("📊 房源开销对比分析报告")
    
    for idx, row in edited_df.iterrows():
        try:
            # 计算月通勤费 (单程 * 2 * 天数 * 4.33周)
            commute_m = (float(row["学费(单程)"]) * 2 * days_school + float(row["塾费(单程)"]) * 2 * days_juku) * 4.33
            total_m = float(row["月房租(円)"]) + float(row["管理费(円)"]) + commute_m + base_living
            
            with st.container(border=True):
                img_c, info_c, btn_c = st.columns([1.5, 3, 1.2])
                with img_c:
                    if row["房源图片"]: st.image(row["房源图片"])
                    else: st.caption("📷 暂无照片")
                with info_c:
                    st.markdown(f"### {row['房源名称']} ({row['房源位置']})")
                    st.markdown(f"#### 💰 月支出: **{int(total_m):,} 円**")
                    st.write(f"🏠 房租+管理: {int(float(row['月房租(円)'])+float(row['管理费(円)'])):,} | 🚇 月通勤费: {int(commute_m):,}")
                    # 显示具体的通勤时间，避免显示默认的 99 分
                    st.markdown(f"⏱️ **通勤时间：学校 {row['学时(分)']}分 | 私塾 {row['塾时(分)']}分**")
                with btn_c:
                    map_url = "https://www.google.com/maps/dir/"
                    url_s = f"{map_url}{row['房源位置']}/{dest_school}/"
                    url_j = f"{map_url}{row['房源位置']}/{dest_juku}/"
                    st.link_button("🏫 查学校路径", url_s, use_container_width=True)
                    st.link_button("🎨 查私塾路径", url_j, use_container_width=True)
                    if st.button("🗑️ 删除房源", key=f"del_{idx}", use_container_width=True):
                        st.session_state.df_houses = st.session_state.df_houses.drop(idx).reset_index(drop=True)
                        st.rerun()
        except: continue

if st.button("🚨 情况所有云端数据"):
    st.session_state.df_houses = pd.DataFrame(columns=st.session_state.df_houses.columns)
    st.rerun()

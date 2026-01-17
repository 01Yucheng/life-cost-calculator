import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import urllib.parse
import base64
from github import Github, Auth
from io import BytesIO
from PIL import Image

# --- 1. 配置与 AI 初始化 ---
st.set_page_config(page_title="东京生活成本 AI 计算器 Pro", layout="wide", page_icon="🗼")

@st.cache_resource
def init_ai():
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🔑 未在 Secrets 中找到 GEMINI_API_KEY")
        st.stop()
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    try:
        # 优先尝试使用 gemini-1.5-flash (性能和速度平衡)
        return genai.GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        st.error(f"AI 初始化失败: {e}")
        st.stop()

model = init_ai()

# --- 2. GitHub 数据同步工具 ---
def get_github_repo():
    try:
        auth = Auth.Token(st.secrets["GITHUB_TOKEN"])
        g = Github(auth=auth)
        return g.get_repo(st.secrets["REPO_NAME"])
    except Exception as e:
        st.error(f"GitHub 连接失败: {e}")
        return None

def load_data_from_github():
    cols = [
        "房源名称", "房源位置", "房源图片", "月房租(円)", "管理费(円)", 
        "初期资金投入", "初期费用明细", "面积", "户型",
        "学时(分)", "学费(单程)", "学定期(月)", 
        "塾时(分)", "塾费(单程)", "塾定期(月)"
    ]
    try:
        repo = get_github_repo()
        if repo:
            file_content = repo.get_contents("house_data.csv")
            df = pd.read_csv(BytesIO(file_content.decoded_content), encoding='utf-8-sig')
            # 确保列名一致并补齐
            df.columns = [c.strip() for c in df.columns]
            for c in cols:
                if c not in df.columns: df[c] = ""
            
            # 强制数字转换
            num_cols = ["月房租(円)", "管理费(円)", "初期资金投入", "学费(单程)", "学定期(月)", "塾时(分)", "塾费(单程)", "塾定期(月)"]
            for col in num_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            return df[cols]
    except Exception:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def save_data_to_github(df):
    repo = get_github_repo()
    if not repo: return
    # 转换为 CSV 字符串
    csv_string = df.to_csv(index=False, encoding='utf-8-sig')
    try:
        contents = repo.get_contents("house_data.csv")
        repo.update_file(contents.path, "Update data", csv_string, contents.sha)
        st.success("✅ 数据已同步至 GitHub!")
    except Exception:
        repo.create_file("house_data.csv", "Initial commit", csv_string)
        st.success("🚀 GitHub 数据库已初始化!")

# --- 3. 核心工具函数 ---
def safe_int(val):
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)) or val == "": 
            return 0
        return int(float(val))
    except: return 0

def analyze_house_image(uploaded_file):
    try:
        img = Image.open(uploaded_file)
        prompt = """
        作为日本不动产专家，请从图中提取信息并返回 JSON：
        {
          "name": "大楼名称",
          "station": "最近车站",
          "rent": 租金数字,
          "admin": 管理费数字,
          "initial_total": 初期费用总和,
          "area": "面积数字",
          "layout": "户型(如1K)",
          "details": "初期费用明细"
        }
        注意：仅返回 JSON 格式，不要包含Markdown代码块。
        """
        response = model.generate_content([prompt, img])
        # 使用更稳健的 JSON 提取正则
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception as e:
        st.error(f"AI 图片解析失败: {e}")
        return None

def get_transit(origin, destination):
    if not origin or origin.strip() == "":
        return {"mins": 0, "yen": 0, "pass": 0}
    prompt = f"基于GoogleMap数据，计算平日早8:30从[{origin}]到[{destination}]的通勤，返回JSON: {{\"mins\": 整数, \"yen\": 单程费用, \"pass\": 1个月定期券费用}}"
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"mins": 0, "yen": 0, "pass": 0}
    except: return {"mins": 0, "yen": 0, "pass": 0}

# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

# 初始化 Session State
if "df_houses" not in st.session_state:
    with st.spinner("💾 正在从云端同步数据库..."):
        st.session_state.df_houses = load_data_from_github()

if "ai_cache" not in st.session_state:
    st.session_state.ai_cache = {"name": "", "station": "", "rent": 0, "admin": 0, "initial": 0, "details": "", "area": "", "layout": ""}

# --- 侧边栏配置 ---
with st.sidebar:
    st.header("⚙️ 全局设置")
    dest_school = st.text_input("🏫 学校地址", value="东京都新宿区百人町2-24-12")
    dest_juku = st.text_input("🎨 私塾地址", value="东京都荒川区西日暮里2-12-5")
    st.divider()
    stay_months = st.slider("📅 预计居住时间 (月)", 1, 48, 24)
    base_living = st.number_input("🍔 月固定基本生活费", value=60000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    use_pass_option = st.toggle("🎫 考虑定期券方案", value=True)
    
    st.divider()
    if st.button("🔄 强制同步至云端", type="primary"):
        save_data_to_github(st.session_state.df_houses)

# --- 录入新房源 ---
with st.expander("➕ 录入新房源", expanded=True):
    up_file = st.file_uploader("🖼️ 上传房源详情图", type=['png', 'jpg', 'jpeg'], key="house_uploader")
    
    if up_file and st.button("🔍 AI 扫描并预填"):
        with st.spinner("AI 解析中..."):
            res = analyze_house_image(up_file)
            if res:
                st.session_state.ai_cache = {
                    "name": res.get("name", ""), "station": res.get("station", ""),
                    "rent": res.get("rent", 0), "admin": res.get("admin", 0),
                    "initial": res.get("initial_total", 0), "details": res.get("details", ""),
                    "area": str(res.get("area", "")), "layout": res.get("layout", "")
                }
                st.rerun()

    cache = st.session_state.ai_cache
    c1, c2 = st.columns(2)
    name_in = c1.text_input("🏠 房源名称", value=cache["name"])
    loc_in = c2.text_input("📍 最近车站", value=cache["station"])
    
    r1, r2, r3 = st.columns(3)
    rent_in = r1.number_input("💰 月租(円)", value=safe_int(cache["rent"]))
    adm_in = r2.number_input("🏢 管理费", value=safe_int(cache["admin"]))
    ini_in = r3.number_input("🔑 初期资金投入", value=safe_int(cache["initial"]))
    
    c_area, c_layout = st.columns(2)
    area_in = c_area.text_input("📐 面积 (m²)", value=cache["area"])
    layout_in = c_layout.text_input("🧱 户型", value=cache["layout"])
    det_in = st.text_input("📝 初期明细备注", value=cache["details"])

    if st.button("🚀 计算并保存", type="primary"):
        if not loc_in or not name_in:
            st.warning("请填写房源名称和车站")
        else:
            with st.spinner("正在计算并同步..."):
                s_d = get_transit(loc_in, dest_school)
                j_d = get_transit(loc_in, dest_juku)
                
                # 图片处理：缩放并转 Base64
                img_b64 = ""
                if up_file:
                    img_obj = Image.open(up_file)
                    img_obj.thumbnail((800, 800)) # 缩放减小体积
                    buf = BytesIO()
                    img_obj.convert("RGB").save(buf, format="JPEG", quality=75)
                    img_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
                
                new_row = {
                    "房源名称": name_in, "房源位置": loc_in, "房源图片": img_b64,
                    "月房租(円)": rent_in, "管理费(円)": adm_in, "初期资金投入": ini_in, 
                    "初期费用明细": det_in, "面积": area_in, "户型": layout_in,
                    "学时(分)": s_d.get('mins', 0), "学费(单程)": s_d.get('yen', 0), "学定期(月)": s_d.get('pass', 0),
                    "塾时(分)": j_d.get('mins', 0), "塾费(单程)": j_d.get('yen', 0), "塾定期(月)": j_d.get('pass', 0)
                }
                
                st.session_state.df_houses = pd.concat([st.session_state.df_houses, pd.DataFrame([new_row])], ignore_index=True)
                save_data_to_github(st.session_state.df_houses)
                st.session_state.ai_cache = {"name": "", "station": "", "rent": 0, "admin": 0, "initial": 0, "details": "", "area": "", "layout": ""}
                st.rerun()

# --- 数据清单表 ---
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(
    st.session_state.df_houses, 
    num_rows="dynamic", 
    use_container_width=True, 
    key="main_data_editor"
)

# 当用户在编辑器里做了改动（比如删除），同步回 state
if not edited_df.equals(st.session_state.df_houses):
    st.session_state.df_houses = edited_df

# --- 成本分析卡片 ---
if not st.session_state.df_houses.empty:
    st.divider()
    st.subheader(f"📊 成本分析 (按 {stay_months}月平摊排序)")

    report_list = []
    for _, row in st.session_state.df_houses.iterrows():
        try:
            if not row["房源名称"] or pd.isna(row["房源名称"]): continue
            
            rent_sum = float(row["月房租(円)"]) + float(row["管理费(円)"])
            
            # 交通费逻辑
            s_pay = float(row["学费(单程)"]) * 2 * days_school * 4.33
            s_pass = float(row["学定期(月)"])
            best_s = min(s_pay, s_pass) if (use_pass_option and s_pass > 0) else s_pay
            
            j_pay = float(row["塾费(单程)"]) * 2 * days_juku * 4.33
            j_pass = float(row["塾定期(月)"])
            best_j = min(j_pay, j_pass) if (use_pass_option and j_pass > 0) else j_pay
            
            monthly_fixed = rent_sum + best_s + best_j + base_living
            amortized_init = float(row["初期资金投入"]) / stay_months
            total = monthly_fixed + amortized_init
            
            report_list.append({"data": row, "total": total, "fixed": monthly_fixed, "amort": amortized_init})
        except: continue

    sorted_data = sorted(report_list, key=lambda x: x['total'])

    for i, item in enumerate(sorted_data):
        r = item['data']
        with st.container(border=True):
            img_c, info_c, btn_c = st.columns([1.5, 3, 1])
            with img_c:
                if r.get("房源图片") and str(r["房源图片"]).startswith("data:image"): 
                    st.image(r["房源图片"], use_container_width=True)
                else:
                    st.info("🖼️ 无房源图")
            with info_c:
                st.markdown(f"### {'🥇 ' if i==0 else ''}{r['房源名称']}")
                st.write(f"📍 车站: {r['房源位置']} | 户型: {r.get('户型','-')} ({r.get('面积','-')}m²)")
                st.markdown(f"📈 **预计月均总支出: {int(item['total']):,} 円**")
                
                with st.expander("🔍 费用明细"):
                    st.write(f"🏠 房租+管理费: {int(float(r['月房租(円)'])+float(r['管理费(円)'])):,} 円")
                    st.write(f"🎫 通勤费(月均): {int(item['fixed'] - (float(r['月房租(円)'])+float(r['管理费(円)'])+base_living)):,} 円")
                    st.write(f"🔑 初期分摊: {int(item['amort']):,} 円/月 (总额 {int(r['初期资金投入']):,})")
            
            with btn_c:
                # 修正后的 Google Maps 链接
                loc_q = urllib.parse.quote(str(r['房源位置']))
                st.link_button("🏫 去学校", f"https://www.google.com/maps/dir/?api=1&origin={loc_q}&destination={urllib.parse.quote(dest_school)}&travelmode=transit", use_container_width=True)
                st.link_button("🎨 去私塾", f"https://www.google.com/maps/dir/?api=1&origin={loc_q}&destination={urllib.parse.quote(dest_juku)}&travelmode=transit", use_container_width=True)

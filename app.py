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
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target = "models/gemini-3-flash"
        return genai.GenerativeModel(target if target in models else models[0])
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
        st.error(f"GitHub 连接失败，请检查 Secrets 配置: {e}")
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
            for c in cols:
                if c not in df.columns:
                    df[c] = ""
            num_cols = ["月房租(円)", "管理费(円)", "初期资金投入", "学费(单程)", "学定期(月)", "塾时(分)", "塾费(单程)", "塾定期(月)"]
            for col in num_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            df["房源图片"] = df["房源图片"].fillna("")
            return df[cols]
    except Exception:
        return pd.DataFrame(columns=cols)

def save_data_to_github(df):
    repo = get_github_repo()
    if not repo: return
    csv_string = df.to_csv(index=False, encoding='utf-8-sig')
    try:
        contents = repo.get_contents("house_data.csv")
        repo.update_file(contents.path, "Update data with images", csv_string, contents.sha)
        st.success("✅ 数据（含图片）已同步至 GitHub!")
    except Exception:
        repo.create_file("house_data.csv", "Initial commit", csv_string)
        st.success("🚀 GitHub 数据库已初始化!")

# --- 3. 工具函数 ---
def safe_int(val):
    """防止 NoneType 或非法字符串导致转换崩溃的万能转换器"""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)) or val == "": 
            return 0
        return int(float(val))
    except (ValueError, TypeError):
        return 0

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
        注意：仅返回 JSON 格式，不要包含Markdown代码块外壳。
        """
        response = model.generate_content([prompt, img])
        clean_text = re.search(r'\{.*\}', response.text, re.DOTALL).group()
        return json.loads(clean_text)
    except: return None

def get_transit(origin, destination):
    if not origin or origin.strip() == "":
        return {"mins": 0, "yen": 0, "pass": 0}
    prompt = f"从[{origin}]到[{destination}]通勤，返回JSON: {{\"mins\": 整数, \"yen\": 单程, \"pass\": 月定期}}"
    try:
        response = model.generate_content(prompt)
        clean_text = re.search(r'\{.*\}', response.text, re.DOTALL).group()
        return json.loads(clean_text)
    except: return {"mins": 0, "yen": 0, "pass": 0}

# --- 4. UI 界面 ---
# --- 4. UI 界面 ---
st.title("🗼 东京生活成本 AI 计算器 Pro")

# 1. 自动初始化数据（确保只运行一次）
if "df_houses" not in st.session_state:
    with st.spinner("💾 正在从云端加载数据..."):
        st.session_state.df_houses = load_data_from_github()

# 2. 侧边栏配置
with st.sidebar:
    st.header("⚙️ 全局设置")
    dest_school = st.text_input("🏫 学校地址", value="东京都新宿区百人町2-24-12 (美都里慕)")
    dest_juku = st.text_input("🎨 私塾地址", value="东京都荒川区西日暮里2-12-5 (尚艺舍)")
    st.divider()
    stay_months = st.slider("📅 预计居住时间 (月)", 1, 48, 24)
    base_living = st.number_input("🍔 月固定基本生活费", value=60000)
    days_school = st.slider("🏫 学校通勤 (天/周)", 1, 7, 5)
    days_juku = st.slider("🎨 私塾通勤 (天/周)", 0.0, 7.0, 0.5, step=0.5)
    use_pass_option = st.toggle("🎫 考虑定期券方案", value=True)
    
    st.divider()
    # 刷新后想看到数据，必须点这个按钮同步到 GitHub
    if st.button("💾 保存当前到 GitHub", use_container_width=True, type="primary"):
        save_data_to_github(st.session_state.df_houses)

# 3. 录入新房源（只保留这一个区块，不要在下面写第二个！）
with st.expander("➕ 录入新房源 (支持 AI 自动识别)", expanded=True):
    up_file = st.file_uploader("🖼️ 上传房源详情图", type=['png', 'jpg', 'jpeg'], key="house_img_uploader")
    
    if "ai_cache" not in st.session_state:
        st.session_state.ai_cache = {"name": "", "station": "", "rent": 0, "admin": 0, "initial": 0, "details": "", "area": "", "layout": ""}

    if up_file and st.button("🔍 AI 扫描房源图"):
        with st.spinner("AI 正在提取资料..."):
            res = analyze_house_image(up_file)
            if res:
                st.session_state.ai_cache = {
                    "name": res.get("name", ""), "station": res.get("station", ""),
                    "rent": res.get("rent", 0), "admin": res.get("admin", 0),
                    "initial": res.get("initial_total", 0), "details": res.get("details", ""),
                    "area": str(res.get("area", "")), "layout": res.get("layout", "")
                }

    cache = st.session_state.ai_cache
    c1, c2 = st.columns(2)
    name_in = c1.text_input("🏠 房源名称", value=cache.get("name", ""))
    loc_in = c2.text_input("📍 最近车站", value=cache.get("station", ""))
    
    r1, r2, r3 = st.columns(3)
    rent_in = r1.number_input("💰 月租(円)", value=safe_int(cache.get("rent")))
    adm_in = r2.number_input("🏢 管理费", value=safe_int(cache.get("admin")))
    ini_in = r3.number_input("🔑 初期资金投入", value=safe_int(cache.get("initial")))
    
    c_area, c_layout = st.columns(2)
    area_in = c_area.text_input("📐 面积 (m²)", value=cache.get("area", ""))
    layout_in = c_layout.text_input("🧱 户型", value=cache.get("layout", ""))
    det_in = st.text_input("📝 初期明细备注", value=cache.get("details", ""))

    if st.button("🚀 计算并添加到清单", use_container_width=True):
        if not loc_in:
            st.warning("请输入车站名称")
        else:
            with st.spinner("正在处理并计算通勤时间..."):
                s_d = get_transit(loc_in, dest_school)
                j_d = get_transit(loc_in, dest_juku)
                
                # 图片 Base64 转换
                img_b64 = ""
                if up_file:
                    img_b64 = f"data:image/png;base64,{base64.b64encode(up_file.getvalue()).decode()}"
                
                new_row = {
                    "房源名称": name_in, "房源位置": loc_in, "房源图片": img_b64,
                    "月房租(円)": rent_in, "管理费(円)": adm_in, "初期资金投入": ini_in, 
                    "初期费用明细": det_in, "面积": area_in, "户型": layout_in,
                    "学时(分)": s_d.get('mins', 0), "学费(单程)": s_d.get('yen', 0), "学定期(月)": s_d.get('pass', 0),
                    "塾时(分)": j_d.get('mins', 0), "塾费(单程)": j_d.get('yen', 0), "塾定期(月)": j_d.get('pass', 0)
                }
                st.session_state.df_houses = pd.concat([st.session_state.df_houses, pd.DataFrame([new_row])], ignore_index=True)
                st.rerun()

# 4. 数据清单表（放在录入区之后）
st.subheader("📝 房源数据清单")
edited_df = st.data_editor(st.session_state.df_houses, num_rows="dynamic", use_container_width=True, key="main_editor")
st.session_state.df_houses = edited_df

# 5. 报告卡片渲染（省略重复的计算逻辑，保持你原有的即可）
# ... (原有排序和卡片显示代码)
# --- B. 录入新房源 ---
with st.expander("➕ 录入新房源", expanded=True):
    up_file = st.file_uploader("🖼️ 上传房源详情图", type=['png', 'jpg', 'jpeg'], key="house_img_uploader")
    
    if "ai_cache" not in st.session_state:
        st.session_state.ai_cache = {"name": "", "station": "", "rent": 0, "admin": 0, "initial": 0, "details": "", "area": "", "layout": ""}

    if up_file and st.button("🔍 AI 扫描房源图"):
        with st.spinner("AI 正在解析图片..."):
            res = analyze_house_image(up_file)
            if res:
                st.session_state.ai_cache = {
                    "name": res.get("name", ""),
                    "station": res.get("station", ""),
                    "rent": res.get("rent", 0),
                    "admin": res.get("admin", 0),
                    "initial": res.get("initial_total", 0),
                    "details": res.get("details", ""),
                    "area": str(res.get("area", "")),
                    "layout": res.get("layout", "")
                }

    cache = st.session_state.ai_cache
    c1, c2 = st.columns(2)
    name_in = c1.text_input("🏠 房源名称", value=cache.get("name", ""))
    loc_in = c2.text_input("📍 最近车站", value=cache.get("station", ""))
    
    r1, r2, r3 = st.columns(3)
    rent_in = r1.number_input("💰 月租(円)", value=safe_int(cache.get("rent")))
    adm_in = r2.number_input("🏢 管理费", value=safe_int(cache.get("admin")))
    ini_in = r3.number_input("🔑 初期资金投入", value=safe_int(cache.get("initial")))
    
    c_area, c_layout = st.columns(2)
    area_in = c_area.text_input("📐 面积 (m²)", value=cache.get("area", ""))
    layout_in = c_layout.text_input("🧱 户型", value=cache.get("layout", ""))
    det_in = st.text_input("📝 初期明细备注", value=cache.get("details", ""))

    if st.button("🚀 计算并添加到清单", use_container_width=True):
        if not loc_in:
            st.warning("请输入车站名称以计算通勤时间")
        else:
            with st.spinner("正在处理并计算通勤时间..."):
                s_d = get_transit(loc_in, dest_school)
                j_d = get_transit(loc_in, dest_juku)
                
                img_b64 = ""
                if up_file:
                    img_b64 = f"data:image/png;base64,{base64.b64encode(up_file.getvalue()).decode()}"
                
                new_row = {
                    "房源名称": name_in, "房源位置": loc_in, "房源图片": img_b64,
                    "月房租(円)": rent_in, "管理费(円)": adm_in, "初期资金投入": ini_in, 
                    "初期费用明细": det_in, "面积": area_in, "户型": layout_in,
                    "学时(分)": s_d.get('mins', 0), "学费(单程)": s_d.get('yen', 0), "学定期(月)": s_d.get('pass', 0),
                    "塾时(分)": j_d.get('mins', 0), "塾费(单程)": j_d.get('yen', 0), "塾定期(月)": j_d.get('pass', 0)
                }
                st.session_state.df_houses = pd.concat([st.session_state.df_houses, pd.DataFrame([new_row])], ignore_index=True)
                st.rerun()

# C. 数据清单表
st.subheader("📝 房源数据清单")
df_edit = st.session_state.df_houses.copy()
num_cols = ["月房租(円)", "管理费(円)", "初期资金投入", "学费(单程)", "学定期(月)", "塾费(单程)", "塾定期(月)"]
for col in num_cols:
    if col in df_edit.columns:
        df_edit[col] = pd.to_numeric(df_edit[col], errors='coerce').fillna(0)

edited_df = st.data_editor(df_edit, num_rows="dynamic", use_container_width=True, key="main_editor")
st.session_state.df_houses = edited_df

# D. 报告生成与展示
if not edited_df.empty:
    st.divider()
    st.subheader(f"📊 成本分析卡片 (按 {stay_months}月平摊排序)")

    report_list = []
    for _, row in edited_df.iterrows():
        try:
            if not row["房源名称"] or pd.isna(row["房源名称"]): continue
            
            r_rent = float(row.get("月房租(円)", 0))
            r_adm = float(row.get("管理费(円)", 0))
            r_ini = float(row.get("初期资金投入", 0))
            
            s_pay = float(row.get("学费(单程)", 0)) * 2 * days_school * 4.33
            s_pass = float(row.get("学定期(月)", 0))
            best_s = min(s_pay, s_pass) if (use_pass_option and s_pass > 0) else s_pay
            
            j_pay = float(row.get("塾费(单程)", 0)) * 2 * days_juku * 4.33
            j_pass = float(row.get("塾定期(月)", 0))
            best_j = min(j_pay, j_pass) if (use_pass_option and j_pass > 0) else j_pay
            
            monthly_fixed = r_rent + r_adm + best_s + best_j + base_living
            amortized_init = r_ini / (stay_months if stay_months > 0 else 1)
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
                st.markdown(f"### {'🥇 ' if i==0 else ''}{r['房源名称']} ({r['房源位置']})")
                st.markdown(f"🏠 **户型: {r.get('户型', 'N/A')} | 面积: {r.get('面积', 'N/A')} m²**")
                st.write(f"📈 **预计月均总支出: {int(item['total']):,} 円**")
                
                with st.expander("🔍 查看费用构成"):
                    st.write(f"🏠 **月度固定**: {int(item['fixed']):,} 円")
                    st.write(f"🔑 **初期分摊**: +{int(item['amort']):,} 円/月 (总额 {int(r['初期资金投入']):,})")
                    if r.get("初期费用明细"):
                        st.info(f"📋 明细: {r['初期费用明细']}")
                
                st.caption(f"⏱️ 通勤: 学校 {int(r.get('学时(分)', 0))}分 / 私塾 {int(r.get('塾时(分)', 0))}分")

            with btn_c:
                start_p = f"{r['房源名称']}"
                school_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(start_p)}&destination={urllib.parse.quote(dest_school)}&travelmode=transit"
                juku_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(start_p)}&destination={urllib.parse.quote(dest_juku)}&travelmode=transit"
                
                st.link_button("🏫 去学校", school_url, use_container_width=True)
                st.link_button("🎨 去私塾", juku_url, use_container_width=True)


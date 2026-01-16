import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
import urllib.parse

# --- 1. 基础配置 ---
st.set_page_config(page_title="东京生活成本计算器-终极稳定版", layout="wide")
TOKYO_TZ = pytz.timezone("Asia/Tokyo")

def get_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 未在 Secrets 中发现 API Key，请检查配置。")
    st.stop()

# --- 2. 核心逻辑优化 ---

def get_precise_geo(address, api_key):
    """
    【修复原因4：地址歧义】
    强制在后台增加 'Tokyo, Japan' 补全，确保 Geocoding 锁定东京。
    """
    if not address: return None
    refined_query = f"{address}, Tokyo, Japan" if "Japan" not in address else address
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(refined_query)}&key={api_key}&language=ja"
    try:
        resp = requests.get(url, timeout=10).json()
        if resp["status"] == "OK":
            res = resp["results"][0]
            return {"id": res["place_id"], "name": res["formatted_address"]}
    except: pass
    return None

def fetch_transit_data(o_id, d_id, api_key):
    """
    【修复原因1&2：参数错误与深夜停运】
    1. 强制查询『下周一早高峰 08:30』，保证任何时间测试都有结果。
    2. 使用更稳健的 Directions V1 接口，避开 V2 的参数冲突。
    """
    now = datetime.now(TOKYO_TZ)
    # 计算下周一的时间戳
    days_to_monday = (7 - now.weekday()) % 7
    if days_to_monday == 0: days_to_monday = 7
    target_time = (now + timedelta(days=days_to_monday)).replace(hour=8, minute=30, second=0, microsecond=0)
    
    url = (f"https://maps.googleapis.com/maps/api/directions/json?"
           f"origin=place_id:{o_id}&destination=place_id:{d_id}&mode=transit&"
           f"departure_time={int(target_time.timestamp())}&key={api_key}&language=ja")
    
    try:
        resp = requests.get(url, timeout=10).json()
        if resp["status"] == "OK":
            route = resp["routes"][0]["legs"][0]
            t = route["duration"]["value"] // 60
            f = int(resp["routes"][0].get("fare", {}).get("value", 0))
            return t, f
    except: pass
    return None, None

def make_google_maps_link(o_addr, d_addr):
    """保底方案：生成手动查看链接"""
    base = "https://www.google.com/maps/dir/?api=1"
    params = {
        "origin": o_addr,
        "destination": d_addr,
        "travelmode": "transit"
    }
    return f"{base}&{urllib.parse.urlencode(params)}"

# --- 3. UI 交互界面 ---

st.title("🇯🇵 东京生活成本计算器 (高容错版)")
api_key = get_api_key()

# A. 房源表格初始化
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([{
        "房源名称": "默认示例", "房租": 85000, "管理费": 5000, "水电网": 15000, "手机": 3000, 
        "餐饮": 40000, "其他": 10000, "通勤时间(分)": 30.0, "单程票价(円)": 200.0, "A周频": 5.0, "B周频": 0.0
    }])

st.subheader("1. 房源数据管理 (双击可直接修改内容)")
st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

st.divider()

# B. 抓取逻辑区
st.subheader("2. 自动抓取通勤路径")
st.info("提示：我们强制模拟『早高峰 08:30』进行检索，以确保结果稳定性。")

col1, col2 = st.columns(2)
with col1:
    origin_in = st.text_input("出发地点 (住处附近车站)", value="新大久保駅")
    dest_a_in = st.text_input("目的地 A (学校/工作)", value="山下駅(東京)")
    freq_a = st.number_input("A每周次数", value=5.0)
with col2:
    row_idx = st.number_input("更新表格第几行", value=1, min_value=1)
    dest_b_in = st.text_input("目的地 B (兼职/其他)", value="")
    freq_b = st.number_input("B每周次数", value=0.0)

if st.button("🚀 开始精准抓取路径数据", use_container_width=True):
    with st.spinner("正在连接 Google 日本交通数据库..."):
        o_geo = get_precise_geo(origin_in, api_key)
        
        if not o_geo:
            st.error(f"❌ 无法识别起点：{origin_in}，请尝试输入更完整的车站名。")
        else:
            success_results = []
            
            # 依次检索 A 和 B
            for label, addr, freq in [("A", dest_a_in, freq_a), ("B", dest_b_in, freq_b)]:
                if addr and freq > 0:
                    d_geo = get_precise_geo(addr, api_key)
                    if d_geo:
                        t, f = fetch_transit_data(o_geo["id"], d_geo["id"], api_key)
                        if t is not None:
                            success_results.append({"t": t, "f": f, "w": freq})
                            st.success(f"✅ 路线 {label} 抓取成功：{t}分钟 / {f}日元")
                        else:
                            st.warning(f"⚠️ 路线 {label} 自动抓取无结果。")
                            st.link_button(f"🌐 手动查看路线 {label}", make_google_maps_link(origin_in, addr))
            
            # 【修复原因3：空结果崩溃校验】
            if success_results:
                # 计算加权平均
                total_w = sum(r['w'] for r in success_results)
                avg_t = sum(r['t'] * r['w'] for r in success_results) / total_w
                avg_f = sum(r['f'] * r['w'] for r in success_results) / total_w
                
                # 写回表格
                idx = int(row_idx - 1)
                if idx < len(st.session_state.df):
                    st.session_state.df.iat[idx, 7] = round(avg_t, 1)
                    st.session_state.df.iat[idx, 8] = round(avg_f, 1)
                    st.session_state.df.iat[idx, 9] = freq_a
                    st.session_state.df.iat[idx, 10] = freq_b
                    st.rerun()

# C. 月度汇总
st.divider()
st.subheader("3. 月度综合支出分析")
df_calc = st.session_state.df.copy()
if not df_calc.empty:
    df_calc["月通勤次数"] = (df_calc["A周频"] + df_calc["B周频"]) * 4.33 * 2
    df_calc["月固定成本"] = df_calc.iloc[:, 1:7].astype(float).sum(axis=1)
    df_calc["月通勤成本"] = df_calc["单程票价(円)"] * df_calc["月通勤次数"]
    df_calc["月现金支出总计"] = df_calc["月固定成本"] + df_calc["月通勤成本"]
    st.dataframe(df_calc.sort_values("月现金支出总计"), use_container_width=True)

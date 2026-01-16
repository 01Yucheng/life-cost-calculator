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
    st.error("❌ 请在 Streamlit Secrets 中配置 GOOGLE_MAPS_API_KEY")
    st.stop()

# --- 2. 核心逻辑：精准检索 ---

def get_precise_geo(address, api_key):
    """自动纠偏地址：强制增加地区限定，提升 Geocoding 成功率"""
    if not address: return None
    # 强制增加后缀，解决类似“山下駅”的同名歧义
    search_query = f"{address}, Tokyo, Japan" if "Japan" not in address else address
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(search_query)}&key={api_key}&language=ja"
    try:
        resp = requests.get(url, timeout=10).json()
        if resp["status"] == "OK":
            res = resp["results"][0]
            return {"id": res["place_id"], "lat": res["geometry"]["location"]["lat"], "lng": res["geometry"]["location"]["lng"]}
    except: pass
    return None

def fetch_transit_data(o_id, d_id, api_key):
    """
    核心修复：
    1. 强制查询“下周一早上 08:30”，避开深夜停运导致的 ZERO_RESULTS。
    2. 使用 Directions API (V1) 以获得对日本票价更稳健的支持。
    """
    now = datetime.now(TOKYO_TZ)
    # 计算下周一的时间戳
    target_date = now + timedelta(days=(7 - now.weekday()) % 7)
    target_time = target_date.replace(hour=8, minute=30, second=0, microsecond=0)
    
    url = (f"https://maps.googleapis.com/maps/api/directions/json?"
           f"origin=place_id:{o_id}&destination=place_id:{d_id}&mode=transit&"
           f"departure_time={int(target_time.timestamp())}&key={api_key}&language=ja")
    
    try:
        resp = requests.get(url, timeout=10).json()
        if resp["status"] == "OK":
            route = resp["routes"][0]["legs"][0]
            time_min = route["duration"]["value"] // 60
            fare_val = int(resp["routes"][0].get("fare", {}).get("value", 0))
            return time_min, fare_val
    except: pass
    return None, None

def get_google_maps_link(o_addr, d_addr):
    """生成保底的手动查看链接"""
    return f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(o_addr)}&destination={urllib.parse.quote(d_addr)}&travelmode=transit"

# --- 3. UI 交互 ---

st.title("🇯🇵 东京生活成本计算器 (自动抓取全修复版)")
api_key = get_api_key()

# 数据存储初始化
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([{
        "房源名称": "示例房源", "房租": 85000, "管理费": 5000, "水电网": 15000, "手机": 3000, 
        "餐饮": 40000, "其他": 10000, "单程时间(分)": 30.0, "单程票价(円)": 200.0, "A周频": 5.0, "B周频": 0.0
    }])

st.subheader("1. 房源对比清单 (可双击修改数据)")
st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

st.divider()

st.subheader("2. 通勤数据自动同步")
st.caption("采用“虚拟早高峰”检索，确保无论何时点击都能抓取到有效班次数据。")

col1, col2 = st.columns(2)
with col1:
    origin_in = st.text_input("住处起点", value="新大久保駅")
    dest_a_in = st.text_input("目的地 A", value="山下駅(東京)")
    freq_a = st.number_input("A每周天数", value=5.0)
with col2:
    row_idx = st.number_input("更新表格第几行", value=1, min_value=1)
    dest_b_in = st.text_input("目的地 B (可选)", value="")
    freq_b = st.number_input("B每周天数", value=0.0)

if st.button("🚀 开启同步：穿透检索路径", use_container_width=True):
    with st.spinner("正在解析地址并模拟早高峰路径..."):
        o_geo = get_precise_geo(origin_in, api_key)
        if not o_geo:
            st.error(f"❌ 无法识别起点地址: {origin_in}")
        else:
            final_data = []
            for label, addr, freq in [("A", dest_a_in, freq_a), ("B", dest_b_in, freq_b)]:
                if addr and freq > 0:
                    d_geo = get_precise_geo(addr, api_key)
                    if d_geo:
                        t, f = fetch_transit_data(o_geo["id"], d_geo["id"], api_key)
                        if t is not None:
                            final_data.append({"t": t, "f": f, "w": freq})
                            st.success(f"✅ 路线 {label} 抓取成功：{t}分钟 / {f}日元")
                        else:
                            st.warning(f"⚠️ 路线 {label} 自动检索无结果。")
                            st.link_button(f"🌐 点击在 Google Maps 中手动验证路线 {label}", get_google_maps_link(origin_in, addr))
            
            # 计算加权数据并写回表格
            if final_data:
                total_t = sum(r['t'] * r['w'] for r in final_data)
                total_f = sum(r['f'] * r['w'] for r in final_data)
                total_w = sum(r['w'] for r in final_data)
                
                target_i = int(row_idx - 1)
                if target_i < len(st.session_state.df):
                    st.session_state.df.iat[target_i, 7] = round(total_t / total_w, 1)
                    st.session_state.df.iat[target_i, 8] = round(total_f / total_w, 1)
                    st.session_state.df.iat[target_i, 9] = freq_a
                    st.session_state.df.iat[target_i, 10] = freq_b
                    st.rerun()

# --- 4. 汇总报告 ---
st.divider()
st.subheader("3. 综合支出分析 (实时联动)")
df_res = st.session_state.df.copy()
if not df_res.empty:
    df_res["月通勤次数"] = (df_res["A周频"] + df_res["B周频"]) * 4.33 * 2
    df_res["月固定成本"] = df_res.iloc[:, 1:7].astype(float).sum(axis=1)
    df_res["月通勤成本"] = df_res["单程票价(円)"] * df_res["月通勤次数"]
    df_res["现金总支出/月"] = df_res["月固定成本"] + df_res["月通勤成本"]
    st.dataframe(df_res.sort_values("现金总支出/月"), use_container_width=True)

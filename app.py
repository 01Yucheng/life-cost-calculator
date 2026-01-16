import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
import urllib.parse

# --- 1. 基础配置 ---
st.set_page_config(page_title="东京生活成本计算器-终极版", layout="wide")
TOKYO_TZ = pytz.timezone("Asia/Tokyo")

def get_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 请在 Secrets 中配置 API Key")
    st.stop()

# --- 2. 增强地址与路线抓取逻辑 ---

def get_precise_geo(address, api_key):
    """自动纠偏：增加日本东京限定，解决同名车站歧义"""
    if not address: return None
    search_query = f"{address}, Tokyo, Japan" if "Japan" not in address else address
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(search_query)}&key={api_key}&language=ja"
    try:
        resp = requests.get(url, timeout=10).json()
        if resp["status"] == "OK":
            res = resp["results"][0]
            return {"id": res["place_id"], "name": res["formatted_address"]}
    except: pass
    return None

def fetch_transit_data(o_id, d_id, api_key):
    """
    强制模拟“下周一早高峰 08:30”，彻底避开深夜停运导致的 ZERO_RESULTS。
    """
    now = datetime.now(TOKYO_TZ)
    # 计算到下周一的天数差
    days_ahead = (7 - now.weekday()) % 7
    if days_ahead == 0: days_ahead = 7
    target_time = (now + timedelta(days=days_ahead)).replace(hour=8, minute=30, second=0, microsecond=0)
    
    # 使用 Directions API，其在日本票价抓取上更稳定
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

# --- 3. UI 界面与交互 ---

st.title("🇯🇵 东京生活成本计算器 (修复版)")
api_key = get_api_key()

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([{
        "房源名称": "默认房源", "房租": 85000, "管理费": 5000, "水电网": 15000, "手机": 3000, 
        "餐饮": 40000, "其他": 10000, "单程时间(分)": 30.0, "单程票价(円)": 200.0, "A周频": 5.0, "B周频": 0.0
    }])

st.subheader("1. 房源数据预览")
st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

st.divider()

st.subheader("2. 自动同步通勤数据")
c1, c2 = st.columns(2)
with c1:
    origin_in = st.text_input("住处起点", value="新大久保駅")
    dest_a_in = st.text_input("目的地 A", value="山下駅(東京)")
    freq_a = st.number_input("A每周天数", value=5.0)
with c2:
    row_idx = st.number_input("更新行号", value=1, min_value=1)
    dest_b_in = st.text_input("目的地 B", value="")
    freq_b = st.number_input("B每周天数", value=0.0)

if st.button("🚀 开始同步路径数据", use_container_width=True):
    with st.spinner("正在解析地址并模拟早高峰路径..."):
        o_geo = get_precise_geo(origin_in, api_key)
        if not o_geo:
            st.error("❌ 无法定位起点")
        else:
            res_cache = []
            for label, addr, freq in [("A", dest_a_in, freq_a), ("B", dest_b_in, freq_b)]:
                if addr and freq > 0:
                    d_geo = get_precise_geo(addr, api_key)
                    if d_geo:
                        t, f = fetch_transit_data(o_geo["id"], d_geo["id"], api_key)
                        if t is not None:
                            res_cache.append({"t": t, "f": f, "w": freq, "label": label})
                            st.success(f"✅ 路线 {label} 抓取成功！")
                        else:
                            st.warning(f"⚠️ 路线 {label} 在早高峰时段也未找到路径。")
            
            if res_cache:
                total_t = sum(r['t'] * r['w'] for r in res_cache) / sum(r['w'] for r in res_cache)
                total_f = sum(r['f'] * r['w'] for r in res_cache) / sum(r['w'] for r in res_cache)
                
                idx = int(row_idx - 1)
                if idx < len(st.session_state.df):
                    st.session_state.df.iat[idx, 7] = round(total_t, 1)
                    st.session_state.df.iat[idx, 8] = round(total_f, 1)
                    st.session_state.df.iat[idx, 9] = freq_a
                    st.session_state.df.iat[idx, 10] = freq_b
                    st.rerun()

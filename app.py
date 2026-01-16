import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
import urllib.parse

# --- 1. 基础配置 ---
st.set_page_config(page_title="东京生活成本计算器-终极修复版", layout="wide")
TOKYO_TZ = pytz.timezone("Asia/Tokyo")

def get_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 未发现 API Key")
    st.stop()

# --- 2. 增强逻辑：精准检索 ---

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
            return {"id": res["place_id"], "name": res["formatted_address"]}
    except: pass
    return None

def fetch_transit_data(o_id, d_id, api_key):
    """
    核心修复：强制查询下周一早上 08:30，避开深夜停运导致的检索失败。
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
            time_min = route["duration"]["value"] // 60
            fare_val = int(resp["routes"][0].get("fare", {}).get("value", 0))
            return time_min, fare_val
    except: pass
    return None, None

# --- 3. UI 交互 ---

st.title("🇯🇵 东京生活成本计算器 (自动抓取修复版)")
api_key = get_api_key()

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([{
        "房源名称": "默认房源", "房租": 85000, "管理费": 5000, "水电网": 15000, "手机": 3000, 
        "餐饮": 40000, "其他": 10000, "单程时间(分)": 30.0, "单程票价(円)": 200.0, "A周频": 5.0, "B周频": 0.0
    }])

st.subheader("1. 房源数据管理")
st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

st.divider()

st.subheader("2. 通勤数据自动同步")
col1, col2 = st.columns(2)
with col1:
    origin_in = st.text_input("住处起点 (例: 新大久保駅)", value="新大久保駅")
    dest_a_in = st.text_input("目的地 A (例: 山下駅)", value="山下駅(東京)")
    freq_a = st.number_input("A每周天数", value=5.0)
with col2:
    row_idx = st.number_input("更新到表格第几行", value=1, min_value=1)
    dest_b_in = st.text_input("目的地 B (可选)", value="")
    freq_b = st.number_input("B每周天数", value=0.0)

if st.button("🚀 开始精准抓取路径数据", use_container_width=True):
    with st.spinner("正在解析地址并模拟早高峰路径..."):
        o_geo = get_precise_geo(origin_in, api_key)
        if not o_geo:
            st.error(f"❌ 无法识别起点: {origin_in}")
        else:
            success_res = []
            for label, addr, freq in [("A", dest_a_in, freq_a), ("B", dest_b_in, freq_b)]:
                if addr and freq > 0:
                    d_geo = get_precise_geo(addr, api_key)
                    if d_geo:
                        t, f = fetch_transit_data(o_geo["id"], d_geo["id"], api_key)
                        if t is not None:
                            success_res.append({"t": t, "f": f, "w": freq, "label": label})
                            st.success(f"✅ 路线 {label} 抓取成功：{t}分钟 / {f}円")
                        else:
                            st.warning(f"⚠️ 路线 {label} 自动抓取失败，建议输入更精确的站名。")
            
            # 安全写回逻辑
            if success_res:
                total_w = sum(r['w'] for r in success_res)
                avg_t = sum(r['t'] * r['w'] for r in success_res) / total_w
                avg_f = sum(r['f'] * r['w'] for r in success_res) / total_w
                
                idx = int(row_idx - 1)
                if idx < len(st.session_state.df):
                    st.session_state.df.iat[idx, 7] = round(avg_t, 1)
                    st.session_state.df.iat[idx, 8] = round(avg_f, 1)
                    st.session_state.df.iat[idx, 9] = freq_a
                    st.session_state.df.iat[idx, 10] = freq_b
                    st.rerun()

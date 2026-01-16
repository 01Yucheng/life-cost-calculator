import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timedelta
import pytz
import urllib.parse

# --- 1. 初始化配置 ---
st.set_page_config(page_title="东京生活成本计算器-终极修复版", layout="wide")
TOKYO_TZ = pytz.timezone("Asia/Tokyo")

def get_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 未在 Secrets 中发现 GOOGLE_MAPS_API_KEY")
    st.stop()

# --- 2. 增强型 API 检索逻辑 ---

def get_geo_info(address, api_key):
    """强制增加日本东京前缀，通过 Geocoding 获取 Place ID 和坐标"""
    if not address: return None
    search_addr = f"日本 東京 {address}" if "日本" not in address else address
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(search_addr)}&key={api_key}&language=ja"
    try:
        resp = requests.get(url, timeout=10).json()
        if resp["status"] == "OK":
            res = resp["results"][0]
            return {
                "id": res["place_id"], 
                "lat": res["geometry"]["location"]["lat"], 
                "lng": res["geometry"]["location"]["lng"],
                "name": res["formatted_address"]
            }
    except Exception as e:
        st.error(f"地址解析异常: {e}")
    return None

def fetch_transit_data(o_id, d_id, api_key):
    """
    核心修复点：
    1. 强制模拟下周一早高峰 08:30，解决深夜无车问题。
    2. 使用更稳定的 Directions API 替代 V2，确保票价抓取率。
    """
    now = datetime.now(TOKYO_TZ)
    # 模拟下周一早上 8:30
    target_time = now + timedelta(days=(7 - now.weekday()) % 7)
    target_time = target_time.replace(hour=8, minute=30, second=0)
    
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

# --- 3. UI 交互 ---

st.title("🇯🇵 东京生活成本计算器 (终极修复版)")
api_key = get_api_key()

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([{
        "房源名称": "默认房源", "房租": 85000, "管理费": 5000, "水电网": 15000, "手机": 3000, 
        "餐饮": 40000, "其他": 10000, "加权单程时间(分)": 0.0, "单程票价(円)": 0.0, "A周频": 5.0, "B周频": 0.0
    }])

st.subheader("1. 房源数据管理")
st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

st.divider()
st.subheader("2. 通勤自动计算")
col1, col2 = st.columns(2)
with col1:
    o_addr = st.text_input("出发住处 (例: 新大久保駅)", value="新大久保駅")
    a_addr = st.text_input("目的地 A (例: 山下駅)", value="豪徳寺駅") # 建议使用明确的大站名测试
    a_freq = st.number_input("A每周天数", value=5.0)
with col2:
    row_num = st.number_input("要更新的表格行号", value=1, min_value=1)
    b_addr = st.text_input("目的地 B (可选)", value="")
    b_freq = st.number_input("B每周天数", value=0.0)

if st.button("🚀 开始检索路径并计算成本", use_container_width=True):
    with st.spinner("正在检索 Google 日本交通实时数据..."):
        o_geo = get_geo_info(o_addr, api_key)
        if not o_geo:
            st.error(f"❌ 找不到起点地址: {o_addr}。请确认地址拼写。")
        else:
            results_cache = []
            
            # 顺序检索 A 和 B
            for label, addr, freq in [("A", a_addr, a_freq), ("B", b_addr, b_freq)]:
                if addr and freq > 0:
                    d_geo = get_geo_info(addr, api_key)
                    if d_geo:
                        t, f = fetch_transit_data(o_geo["id"], d_geo["id"], api_key)
                        if t is not None:
                            results_cache.append({"label": label, "o": o_geo, "d": d_geo, "t": t, "f": f, "freq": freq})
                        else:
                            st.warning(f"⚠️ 无法找到前往 {label}({addr}) 的公共交通路线。")
                    else:
                        st.error(f"❌ 找不到目的地 {label} 地址: {addr}")

            # 只要有一条线路成功，就执行计算写回
            if results_cache:
                total_t, total_f, total_weight = 0, 0, 0
                for r in results_cache:
                    total_t += r["t"] * r["freq"]
                    total_f += r["f"] * r["freq"]
                    total_weight += r["freq"]
                
                idx = int(row_num - 1)
                if idx < len(st.session_state.df):
                    st.session_state.df.iat[idx, 7] = round(total_t / total_weight, 1)
                    st.session_state.df.iat[idx, 8] = round(total_f / total_weight, 1)
                    st.session_state.df.iat[idx, 9] = a_freq
                    st.session_state.df.iat[idx, 10] = b_freq
                    st.success(f"✅ 第 {row_num} 行数据更新成功！")
                    
                    # 安全渲染：只有 results_cache 不为空才创建 columns
                    st.subheader("🗺️ 通勤路线预览")
                    map_cols = st.columns(len(results_cache))
                    for i, res in enumerate(results_cache):
                        with map_cols[i]:
                            st.info(f"**路线 {res['label']}**: {res['t']}分 / {res['f']}円")
                            m_url = (f"https://maps.googleapis.com/maps/api/staticmap?size=500x300&scale=2&"
                                     f"markers=color:red|{res['o']['lat']},{res['o']['lng']}&"
                                     f"markers=color:blue|{res['d']['lat']},{res['d']['lng']}&key={api_key}")
                            st.image(m_url)
                else:
                    st.error(f"❌ 指定行号 {row_num} 超出表格当前范围。")
            else:
                st.error("❌ 检索失败：未找到任何有效通勤路线。")

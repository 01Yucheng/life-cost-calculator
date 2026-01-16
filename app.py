import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timedelta
import pytz
import urllib.parse

# --- 1. 配置 ---
st.set_page_config(page_title="东京生活成本计算器-终极版", layout="wide")
TOKYO_TZ = pytz.timezone("Asia/Tokyo")

def get_google_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 请在 Secrets 中配置 GOOGLE_MAPS_API_KEY")
    st.stop()

# --- 2. 增强型 API 逻辑 ---

def get_geo_info(address, api_key):
    """获取 Place ID 和坐标，自动增加地区前缀提高成功率"""
    if not address: return None
    clean_addr = f"日本 東京 {address}" if "日本" not in address else address
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(clean_addr)}&key={api_key}&language=ja"
    try:
        data = requests.get(url).json()
        if data["status"] == "OK":
            res = data["results"][0]
            return {
                "id": res["place_id"], 
                "lat": res["geometry"]["location"]["lat"], 
                "lng": res["geometry"]["location"]["lng"],
                "name": res["formatted_address"]
            }
    except: pass
    return None

def fetch_transit_data(o_id, d_id, api_key):
    """双路检索：优先 Routes V2，失败则自动尝试 Directions API"""
    # 模拟工作日早上 8:30，确保有车
    target_time = datetime.now(TOKYO_TZ).replace(hour=8, minute=30, second=0)
    if target_time < datetime.now(TOKYO_TZ):
        target_time += timedelta(days=1)
    
    # 1. 尝试 Routes V2
    url_v2 = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": api_key, 
               "X-Goog-FieldMask": "routes.duration,routes.travelAdvisory.transitFare"}
    body = {
        "origin": {"placeId": o_id}, "destination": {"placeId": d_id},
        "travelMode": "TRANSIT", "departureTime": target_time.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "languageCode": "ja-JP"
    }
    
    try:
        resp = requests.post(url_v2, headers=headers, json=body).json()
        if "routes" in resp and resp["routes"]:
            r = resp["routes"][0]
            t = int(r["duration"].replace("s", "")) // 60
            f = int(r.get("travelAdvisory", {}).get("transitFare", {}).get("units", 0))
            return t, f, "V2"
    except: pass

    # 2. 备选方案：旧版 Directions API
    url_dir = f"https://maps.googleapis.com/maps/api/directions/json?origin=place_id:{o_id}&destination=place_id:{d_id}&mode=transit&departure_time={int(target_time.timestamp())}&key={api_key}&language=ja"
    try:
        resp = requests.get(url_dir).json()
        if resp["status"] == "OK":
            route = resp["routes"][0]["legs"][0]
            t = route["duration"]["value"] // 60
            f = int(resp["routes"][0].get("fare", {}).get("value", 0))
            return t, f, "Directions"
    except: pass
    
    return None, None, None

# --- 3. UI 渲染 ---

st.title("🇯🇵 东京生活成本计算器 (全环境兼容版)")
api_key = get_google_api_key()

# 数据初始化
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([{
        "房源名称": "默认测试", "房租": 85000, "管理费": 5000, "水电网": 15000, "手机": 3000, 
        "餐饮": 40000, "其他": 10000, "通勤时间(分)": 0.0, "单程票价(円)": 0.0, "A周频": 5.0, "B周频": 0.0
    }])

# 表格编辑
st.subheader("1. 房源数据预览 (支持直接双击修改)")
st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

# 计算区
st.divider()
st.subheader("2. 通勤自动计算 (智能补全+时间模拟)")
col1, col2 = st.columns(2)
with col1:
    o_addr = st.text_input("出发地 (如: 新大久保駅)", value="新大久保駅")
    a_addr = st.text_input("目的地 A (如: 山下駅)", value="山下駅")
    a_freq = st.number_input("A每周次数", value=5.0)
with col2:
    row_num = st.number_input("更新到第几行", value=1, min_value=1)
    b_addr = st.text_input("目的地 B (可选)", value="")
    b_freq = st.number_input("B每周次数", value=0.0)

if st.button("🚀 开始检索 (高级+备选模式)", use_container_width=True):
    with st.spinner("正在穿透搜索东京交通网络..."):
        o_geo = get_geo_info(o_addr, api_key)
        if not o_geo: st.error("无法定位出发地")
        else:
            final_t, final_f = 0, 0
            results_to_show = []
            
            for label, addr, freq in [("A", a_addr, a_freq), ("B", b_addr, b_freq)]:
                if addr and freq > 0:
                    d_geo = get_geo_info(addr, api_key)
                    if d_geo:
                        t, f, source = fetch_transit_data(o_geo["id"], d_geo["id"], api_key)
                        if t is not None:
                            results_to_show.append({"label": label, "o": o_geo, "d": d_geo, "t": t, "f": f, "src": source})
                            final_t += t * freq
                            final_f += f * freq
            
            if results_to_show:
                total_freq = a_freq + b_freq
                idx = row_num - 1
                st.session_state.df.iat[idx, 7] = round(final_t / total_freq, 1)
                st.session_state.df.iat[idx, 8] = round(final_f / total_freq, 1)
                st.session_state.df.iat[idx, 9] = a_freq
                st.session_state.df.iat[idx, 10] = b_freq
                st.success(f"✅ 更新成功！")
                
                # 安全渲染地图预览
                st.markdown("### 🗺️ 路线可视化")
                cols = st.columns(len(results_to_display := results_to_show))
                for i, res in enumerate(results_to_display):
                    with cols[i]:
                        st.info(f"**路线 {res['label']}** ({res['src']} 引擎)")
                        st.write(f"⏱️ {res['t']} 分钟 | 💰 {res['f']} 日元")
                        map_url = f"https://maps.googleapis.com/maps/api/staticmap?size=600x300&scale=2&markers=color:red|label:S|{res['o']['lat']},{res['o']['lng']}&markers=color:blue|label:E|{res['d']['lat']},{res['d']['lng']}&key={api_key}"
                        st.image(map_url)

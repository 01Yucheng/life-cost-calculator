import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timedelta
import pytz
import urllib.parse

# --- 1. 基础配置 ---
st.set_page_config(page_title="东京生活成本计算器", layout="wide")
TOKYO_TZ = pytz.timezone("Asia/Tokyo")

def get_google_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 未在 Secrets 中找到 GOOGLE_MAPS_API_KEY")
    st.stop()

# --- 2. Google API 逻辑 ---

def get_place_id_and_coords(address, api_key):
    """获取 Place ID 和 经纬度"""
    if not address: return None
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}&language=ja"
    try:
        response = requests.get(url)
        data = response.json()
        if data["status"] == "OK":
            result = data["results"][0]
            return {
                "place_id": result["place_id"],
                "lat": result["geometry"]["location"]["lat"],
                "lng": result["geometry"]["location"]["lng"],
                "formatted_address": result["formatted_address"]
            }
    except Exception as e:
        st.error(f"Geocoding 错误: {e}")
    return None

def get_static_map_url(origin_coords, dest_coords, api_key):
    """生成静态地图预览链接"""
    base_url = "https://maps.googleapis.com/maps/api/staticmap?"
    markers = [
        f"color:red|label:S|{origin_coords['lat']},{origin_coords['lng']}",
        f"color:blue|label:E|{dest_coords['lat']},{dest_coords['lng']}"
    ]
    params = {
        "size": "600x300",
        "scale": "2",
        "markers": markers,
        "key": api_key,
        "language": "ja"
    }
    return base_url + urllib.parse.urlencode(params, doseq=True)

def call_routes_v2(origin_id, dest_id, departure_time, api_key, debug=False):
    """修复后的 Routes API v2 调用"""
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration,routes.travelAdvisory.transitFare"
    }
    
    utc_time = departure_time.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        "origin": {"placeId": origin_id},
        "destination": {"placeId": dest_id},
        "travelMode": "TRANSIT",
        "departureTime": utc_time,
        "languageCode": "ja-JP",
        "units": "METRIC"
    }
    
    if debug:
        st.sidebar.subheader("Debug: API Request")
        st.sidebar.json(body)

    response = requests.post(url, headers=headers, json=body)
    
    if debug:
        st.sidebar.subheader(f"Debug: Response ({response.status_code})")
        st.sidebar.json(response.json())
        
    return response.status_code, response.json()

# --- 3. UI 界面 ---

st.title("🇯🇵 东京生活成本计算器")
st.caption("修复版：修正地图渲染列错误 & 优化 API 逻辑")

api_key = get_google_api_key()

with st.sidebar:
    st.header("全局参数")
    use_time_value = st.checkbox("启用时间价值折算", value=False)
    time_value_rate = st.number_input("时间价值 (日元/小时)", value=2000, step=100)
    debug_mode = st.toggle("Debug 模式", value=False)

# A. 房源录入
st.subheader("1. 房源对比清单")
if "df_data" not in st.session_state:
    st.session_state.df_data = pd.DataFrame([{
        "房源名称": "示例房源", "房租(月/日元)": 90000, "管理费(月/日元)": 5000,
        "水电网(月/日元)": 15000, "手机(月/日元)": 3000, "餐饮买菜(月/日元)": 40000, "其他(月/日元)": 10000,
        "加权单程通勤时间(分钟)": 0.0, "加权单程通勤费用(日元)": 0.0,
        "A每周次数": 5.0, "B每周次数": 0.0
    }])

st.session_state.df_data = st.data_editor(st.session_state.df_data, num_rows="dynamic", use_container_width=True)

# B. 通勤计算
st.divider()
st.subheader("2. 通勤自动计算")

c1, c2 = st.columns(2)
with c1:
    origin_input = st.text_input("出发住处地址", placeholder="例：新大久保駅")
    dest_a_input = st.text_input("目的地 A (语校/工作)", placeholder="例：新宿駅")
    freq_a = st.number_input("A 每周次数", value=5.0, step=0.5)
with c2:
    target_row = st.number_input("写回表格第几行", value=1, min_value=1, step=1)
    dest_b_input = st.text_input("目的地 B (私塾/兼职)", placeholder="例：秋葉原駅")
    freq_b = st.number_input("B 每周次数", value=0.0, step=0.5)

if st.button("🚀 开始计算路线", use_container_width=True):
    if not origin_input:
        st.error("请输入出发住处地址")
    else:
        with st.spinner("计算中..."):
            origin_geo = get_place_id_and_coords(origin_input, api_key)
            now = datetime.now(TOKYO_TZ) + timedelta(minutes=10)
            
            results_to_display = []
            time_a, fare_a, time_b, fare_b = 0, 0, 0, 0
            
            # 计算 A
            if dest_a_input:
                geo_a = get_place_id_and_coords(dest_a_input, api_key)
                if geo_a:
                    code, res = call_routes_v2(origin_geo["place_id"], geo_a["place_id"], now, api_key, debug_mode)
                    if code == 200 and "routes" in res:
                        r = res["routes"][0]
                        time_a = int(r["duration"].replace("s", "")) // 60
                        fare_a = int(r.get("travelAdvisory", {}).get("transitFare", {}).get("units", 0))
                        results_to_display.append({"label": "A", "origin": origin_geo, "dest": geo_a, "time": time_a, "fare": fare_a})

            # 计算 B
            if dest_b_input:
                geo_b = get_place_id_and_coords(dest_b_input, api_key)
                if geo_b:
                    code, res = call_routes_v2(origin_geo["place_id"], geo_b["place_id"], now, api_key, debug_mode)
                    if code == 200 and "routes" in res:
                        r = res["routes"][0]
                        time_b = int(r["duration"].replace("s", "")) // 60
                        fare_b = int(r.get("travelAdvisory", {}).get("transitFare", {}).get("units", 0))
                        results_to_display.append({"label": "B", "origin": origin_geo, "dest": geo_b, "time": time_b, "fare": fare_b})

            # 更新表格逻辑
            total_freq = freq_a + freq_b
            if total_freq > 0:
                weighted_time = (time_a * freq_a + time_b * freq_b) / total_freq
                weighted_fare = (fare_a * freq_a + fare_b * freq_b) / total_freq
                
                row_idx = target_row - 1
                if row_idx < len(st.session_state.df_data):
                    st.session_state.df_data.iat[row_idx, 7] = round(weighted_time, 1)
                    st.session_state.df_data.iat[row_idx, 8] = round(weighted_fare, 1)
                    st.session_state.df_data.iat[row_idx, 9] = freq_a
                    st.session_state.df_data.iat[row_idx, 10] = freq_b
                    st.success(f"已更新第 {target_row} 行数据")
                    
                    # 只有在有结果时才渲染预览
                    if results_to_display:
                        st.subheader("🗺️ 路线预览")
                        cols = st.columns(len(results_to_display))
                        for i, res in enumerate(results_to_display):
                            with cols[i]:
                                st.write(f"**路线 {res['label']}** ({res['time']}分 / {res['fare']}円)")
                                st.image(get_static_map_url(res['origin'], res['dest'], api_key))
                else:
                    st.error("目标行不存在")

# --- 4. 汇总展示 ---
st.divider()
st.subheader("3. 成本分析报告")

df = st.session_state.df_data.copy()
if not df.empty:
    df["每月单程次数"] = (df["A每周次数"] + df["B每周次数"]) * 4.33
    df["每月固定支出"] = df.iloc[:, 1:7].sum(axis=1)
    df["每月通勤支出"] = df["加权单程通勤费用(日元)"] * df["每月单程次数"] * 2
    df["现金总支出/月"] = df["每月固定支出"] + df["每月通勤支出"]
    
    if use_time_value:
        df["每月通勤时数"] = (df["加权单程通勤时间(分钟)"] * df["每月单程次数"] * 2) / 60
        df["时间成本/月"] = df["每月通勤时数"] * time_value_rate
        df["综合总成本/月"] = df["现金总支出/月"] + df["时间成本/月"]
        df = df.sort_values("综合总成本/月")
    else:
        df = df.sort_values("现金总支出/月")

    st.dataframe(df.style.highlight_min(axis=0, color="#1b4d3e"), use_container_width=True)

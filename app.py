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

# --- 2. Google API 逻辑逻辑 ---

def get_place_id_and_coords(address, api_key):
    """获取 Place ID 和 经纬度"""
    if not address: return None
    # 自动为纯地名加上“东京”前缀提高准确率
    search_query = address if "东京" in address or "県" in address else f"东京 {address}"
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(search_query)}&key={api_key}&language=ja"
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
        st.error(f"地址解析错误: {e}")
    return None

def get_static_map_url(origin_coords, dest_coords, api_key):
    """生成静态地图预览"""
    base_url = "https://maps.googleapis.com/maps/api/staticmap?"
    markers = [
        f"color:red|label:S|{origin_coords['lat']},{origin_coords['lng']}",
        f"color:blue|label:E|{dest_coords['lat']},{dest_coords['lng']}"
    ]
    params = {
        "size": "600x300", "scale": "2", "markers": markers, "key": api_key, "language": "ja"
    }
    return base_url + urllib.parse.urlencode(params, doseq=True)

def call_routes_v2(origin_id, dest_id, departure_time, api_key):
    """Routes API v2 调用"""
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
        "languageCode": "ja-JP", "units": "METRIC"
    }
    response = requests.post(url, headers=headers, json=body)
    return response.status_code, response.json()

# --- 3. UI 界面 ---

st.title("🇯🇵 东京生活成本计算器 (稳定版)")
api_key = get_google_api_key()

with st.sidebar:
    st.header("全局参数")
    use_time_value = st.checkbox("启用时间价值折算", value=False)
    time_value_rate = st.number_input("时间价值 (日元/小时)", value=2000, step=100)
    debug_mode = st.toggle("显示 API 原生数据", value=False)

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
    origin_input = st.text_input("出发地 (如: 住处地址/最近车站)", placeholder="例: 新大久保駅")
    dest_a_input = st.text_input("目的地 A (语校/工作)", placeholder="例: 新宿駅")
    freq_a = st.number_input("A 每周次数", value=5.0, min_value=0.0, max_value=7.0)
with c2:
    target_row = st.number_input("写入表格行号", value=1, min_value=1)
    dest_b_input = st.text_input("目的地 B (私塾/兼职)", placeholder="例: 秋葉原駅")
    freq_b = st.number_input("B 每周次数", value=0.0, min_value=0.0, max_value=7.0)

if st.button("🚀 开始精准计算路线", use_container_width=True):
    if not origin_input:
        st.warning("请输入出发地")
    else:
        with st.spinner("正在检索 Google Maps 最佳路径..."):
            origin_geo = get_place_id_and_coords(origin_input, api_key)
            now = datetime.now(TOKYO_TZ) + timedelta(minutes=10)
            
            display_list = []
            results = {"A": {"t": 0, "f": 0}, "B": {"t": 0, "f": 0}}
            
            # 计算逻辑
            for label, inp in [("A", dest_a_input), ("B", dest_b_input)]:
                if inp:
                    geo = get_place_id_and_coords(inp, api_key)
                    if geo:
                        code, res = call_routes_v2(origin_geo["place_id"], geo["place_id"], now, api_key)
                        if code == 200 and "routes" in res and res["routes"]:
                            route = res["routes"][0]
                            t = int(route["duration"].replace("s", "")) // 60
                            f = int(route.get("travelAdvisory", {}).get("transitFare", {}).get("units", 0))
                            results[label] = {"t": t, "f": f}
                            display_list.append({"label": label, "o": origin_geo, "d": geo, "t": t, "f": f})
                        else:
                            st.error(f"无法找到前往 {label} 的公交路线，请确认地址。")

            # 写回 session_state
            total_f = freq_a + freq_b
            if total_f > 0:
                w_time = (results["A"]["t"] * freq_a + results["B"]["t"] * freq_b) / total_f
                w_fare = (results["A"]["f"] * freq_a + results["B"]["f"] * freq_b) / total_f
                
                ridx = target_row - 1
                if ridx < len(st.session_state.df_data):
                    st.session_state.df_data.iat[ridx, 7] = round(w_time, 1)
                    st.session_state.df_data.iat[ridx, 8] = round(w_fare, 1)
                    st.session_state.df_data.iat[ridx, 9] = freq_a
                    st.session_state.df_data.iat[ridx, 10] = freq_b
                    st.success(f"✅ 第 {target_row} 行房源通勤数据已更新！")
                    
                    if display_list:
                        st.subheader("🗺️ 路线预览")
                        cols = st.columns(len(display_list))
                        for i, item in enumerate(display_list):
                            with cols[i]:
                                st.info(f"**路线 {item['label']}**: {item['t']} 分钟 / {item['f']} 日元")
                                st.image(get_static_map_url(item['o'], item['d'], api_key))
                else:
                    st.error("指定的行号超出了房源列表范围。")

# --- 4. 汇总分析 ---
st.divider()
st.subheader("3. 综合月度支出排名 (按成本从低到高)")

final_df = st.session_state.df_data.copy()
if not final_df.empty:
    # 基础现金计算 (每月平均 4.33 周)
    final_df["每月单程次数"] = (final_df["A每周次数"] + final_df["B每周次数"]) * 4.33
    final_df["固定支出"] = final_df.iloc[:, 1:7].astype(float).sum(axis=1)
    final_df["通勤支出"] = final_df["加权单程通勤费用(日元)"] * final_df["每月单程次数"] * 2
    final_df["月现金总支出"] = final_df["固定支出"] + final_df["通勤支出"]
    
    if use_time_value:
        final_df["月通勤时数"] = (final_df["加权单程通勤时间(分钟)"] * final_df["每月单程次数"] * 2) / 60
        final_df["隐性时间成本"] = final_df["月通勤时数"] * time_value_rate
        final_df["综合成本(含时间)"] = final_df["月现金总支出"] + final_df["隐性时间成本"]
        final_df = final_df.sort_values("综合成本(含时间)")
    else:
        final_df = final_df.sort_values("月现金总支出")

    st.dataframe(final_df.style.highlight_min(axis=0, color="#1b4d3e"), use_container_width=True)

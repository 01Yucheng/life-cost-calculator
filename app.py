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
    """获取 Place ID 和 经纬度（用于 Static Map）"""
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}&language=ja"
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
    """调用 Routes API v2"""
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration,routes.travelAdvisory.transitFare"
    }
    
    # 转换为 UTC ISO 格式
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

# --- 3. UI 界面逻辑 ---

st.title("🇯🇵 东京生活成本计算器")
st.caption("资深全栈版：集成 Google Routes API v2 & 静态地图预览")

api_key = get_google_api_key()

# Sidebar 配置
with st.sidebar:
    st.header("全局参数")
    use_time_value = st.checkbox("启用时间价值折算", value=False)
    time_value_rate = st.number_input("时间价值 (日元/小时)", value=2000, step=100)
    debug_mode = st.toggle("Debug 模式", value=False)
    st.info("提示：若 API 没返回票价，请手动在表格中填写（常见于私铁路线）。")

# A. 房源录入表格
st.subheader("1. 房源对比清单")
if "df_data" not in st.session_state:
    st.session_state.df_data = pd.DataFrame([
        {
            "房源名称": "示例: 高田马场公寓", "房租(月/日元)": 90000, "管理费(月/日元)": 5000,
            "水电网(月/日元)": 15000, "手机(月/日元)": 3000, "餐饮买菜(月/日元)": 40000, "其他(月/日元)": 10000,
            "加权单程通勤时间(分钟)": 0.0, "加权单程通勤费用(日元)": 0.0,
            "A每周次数": 5.0, "B每周次数": 0.0
        }
    ])

edited_df = st.data_editor(st.session_state.df_data, num_rows="dynamic", use_container_width=True)
st.session_state.df_data = edited_df

# B. 通勤计算区
st.divider()
st.subheader("2. 通勤自动计算")

col1, col2 = st.columns(2)
with col1:
    origin_input = st.text_input("出发住处地址", placeholder="例：新大久保駅")
    dest_a_input = st.text_input("目的地 A (语校/工作)", placeholder="例：新宿駅")
    freq_a = st.number_input("A 每周次数", value=5.0, step=0.5)

with col2:
    target_row = st.number_input("写回表格第几行", value=1, min_value=1, step=1)
    dest_b_input = st.text_input("目的地 B (私塾/兼职)", placeholder="例：秋葉原駅")
    freq_b = st.number_input("B 每周次数", value=0.0, step=0.5)

btn_calc = st.button("🚀 开始计算路线", use_container_width=True)

if btn_calc:
    if not origin_input or (not dest_a_input and not dest_b_input):
        st.error("请至少输入起点和一个目的地。")
    else:
        with st.spinner("正在同步 Google Maps 数据..."):
            # 1. 获取地理编码
            origin_geo = get_place_id_and_coords(origin_input, api_key)
            dest_a_geo = get_place_id_and_coords(dest_a_input, api_key) if dest_a_input else None
            dest_b_geo = get_place_id_and_coords(dest_b_input, api_key) if dest_b_input else None
            
            if not origin_geo:
                st.error("无法识别起点地址。")
            else:
                results = []
                now = datetime.now(TOKYO_TZ) + timedelta(minutes=10)
                
                # 计算 A
                time_a, fare_a = 0, 0
                if dest_a_geo:
                    st.toast(f"正在计算 A 路线...")
                    code, res = call_routes_v2(origin_geo["place_id"], dest_a_geo["place_id"], now, api_key, debug_mode)
                    if code == 200 and "routes" in res:
                        route = res["routes"][0]
                        time_a = int(route["duration"].replace("s", "")) // 60
                        fare_a = int(route.get("travelAdvisory", {}).get("transitFare", {}).get("units", 0))
                        results.append(("A", origin_geo, dest_a_geo))
                    
                # 计算 B
                time_b, fare_b = 0, 0
                if dest_b_geo:
                    st.toast(f"正在计算 B 路线...")
                    code, res = call_routes_v2(origin_geo["place_id"], dest_b_geo["place_id"], now, api_key, debug_mode)
                    if code == 200 and "routes" in res:
                        route = res["routes"][0]
                        time_b = int(route["duration"].replace("s", "")) // 60
                        fare_b = int(route.get("travelAdvisory", {}).get("transitFare", {}).get("units", 0))
                        results.append(("B", origin_geo, dest_b_geo))

                # 加权计算并写回
                total_freq = freq_a + freq_b
                if total_freq > 0:
                    w_time = (time_a * freq_a + time_b * freq_b) / total_freq
                    w_fare = (fare_a * freq_a + fare_b * freq_b) / total_freq
                    
                    idx = target_row - 1
                    if idx < len(st.session_state.df_data):
                        st.session_state.df_data.iat[idx, 7] = round(w_time, 1)
                        st.session_state.df_data.iat[idx, 8] = round(w_fare, 1)
                        st.session_state.df_data.iat[idx, 9] = freq_a
                        st.session_state.df_data.iat[idx, 10] = freq_b
                        st.success(f"✅ 已更新第 {target_row} 行房源数据！")
                        
                        # 路线预览图展示
                        st.markdown("### 🗺️ 路线预览")
                        map_cols = st.columns(len(results))
                        for i, (label, o, d) in enumerate(results):
                            with map_cols[i]:
                                st.write(f"**路线 {label} 可视化**")
                                st.image(get_static_map_url(o, d, api_key))
                                st.link_button(f"在 Google Maps 中打开 {label}", f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(o['formatted_address'])}&destination={urllib.parse.quote(d['formatted_address'])}&travelmode=transit")
                        
                        st.rerun()

# --- 4. 最终结果计算 ---
st.divider()
st.subheader("3. 结果汇总与排序")

if not st.session_state.df_data.empty:
    res_df = st.session_state.df_data.copy()
    res_df["每月单程次数"] = (res_df["A每周次数"] + res_df["B每周次数"]) * 4.33
    res_df["固定支出/月"] = res_df.iloc[:, 1:7].sum(axis=1)
    res_df["通勤费用/月"] = res_df["加权单程通勤费用(日元)"] * res_df["每月单程次数"] * 2
    res_df["现金总成本/月"] = res_df["固定支出/月"] + res_df["通勤费用/月"]
    
    if use_time_value:
        res_df["每月通勤时数"] = (res_df["加权单程通勤时间(分钟)"] * res_df["每月单程次数"] * 2) / 60
        res_df["时间折算成本/月"] = res_df["每月通勤时数"] * time_value_rate
        res_df["综合总成本/月"] = res_df["现金总成本/月"] + res_df["时间折算成本/月"]
        res_df = res_df.sort_values("综合总成本/月")
    else:
        res_df = res_df.sort_values("现金总成本/月")

    st.dataframe(res_df.style.highlight_min(axis=0, color="#1b4d3e"), use_container_width=True)

    # 导出
    csv = res_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 下载分析报告 (CSV)", data=csv, file_name="生活成本对比.csv", mime="text/csv")

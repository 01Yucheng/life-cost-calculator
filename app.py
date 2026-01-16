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

# --- 2. 辅助函数 (Helpers) ---
def get_google_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 未发现 API Key。请在 Streamlit Secrets 中配置 GOOGLE_MAPS_API_KEY")
    st.stop()

def get_google_maps_link(origin, destination):
    base_url = "https://www.google.com/maps/dir/?api=1"
    params = {
        "origin": origin,
        "destination": destination,
        "travelmode": "transit"
    }
    return f"{base_url}&{urllib.parse.urlencode(params)}"

def round_time_5min(dt):
    """时间向上取整到5分钟，减少API冗余请求"""
    minutes = (dt.minute // 5 + 1) * 5
    return dt.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)

# --- 3. Google API 逻辑 ---
def get_place_id(address, api_key):
    """使用 Geocoding API 获取 Place ID"""
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}"
    response = requests.get(url)
    data = response.json()
    if data["status"] == "OK":
        return data["results"][0]["place_id"]
    return None

def call_routes_v2(origin_id, dest_id, departure_time, api_key, debug=False):
    """调用 Google Routes API v2 (TRANSIT 模式)"""
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration,routes.legs.steps.transitDetails,routes.travelAdvisory.transitFare"
    }
    
    body = {
        "origin": {"placeId": origin_id},
        "destination": {"placeId": dest_id},
        "travelMode": "TRANSIT",
        "departureTime": departure_time.isoformat() + "Z",
        "computeInlineRouteOptions": {"includeTraffic": "TRAFFIC_AWARE"}
    }
    
    if debug:
        st.sidebar.subheader("Debug: API Request")
        st.sidebar.json(body)

    response = requests.post(url, headers=headers, json=body)
    
    if debug:
        st.sidebar.subheader(f"Debug: API Response ({response.status_code})")
        st.sidebar.json(response.json())
        
    return response.status_code, response.json()

def get_transit_info_with_retry(origin, dest, api_key, debug=False):
    """通勤计算核心逻辑（带重试机制）"""
    o_id = get_place_id(origin, api_key)
    d_id = get_place_id(dest, api_key)
    
    if not o_id or not d_id:
        return None, None, "无法解析地址"

    now = datetime.now(TOKYO_TZ)
    # 处理过去的时间
    selected_time = round_time_5min(now + timedelta(minutes=10))
    
    # 第一次尝试：departureTime
    status, data = call_routes_v2(o_id, d_id, selected_time, api_key, debug)
    
    # 如果没结果，可能是深夜或无路线，尝试稍微调整时间（此处按需求逻辑）
    if "routes" not in data or len(data["routes"]) == 0:
        return None, None, "未找到公共交通路线"

    route = data["routes"][0]
    # 耗时处理 (e.g. "1200s")
    duration_sec = int(route["duration"].replace("s", ""))
    duration_min = duration_sec // 60
    
    # 票价处理
    fare = None
    if "travelAdvisory" in route and "transitFare" in route["travelAdvisory"]:
        # Routes API 返回的通常是单位金额（比如日元）
        fare = int(route["travelAdvisory"]["transitFare"]["units"])
    
    return duration_min, fare, "OK"

# --- 4. UI 布局 ---
st.title("🇯🇵 东京生活成本计算器 (房租 + 通勤)")
st.markdown("对比多个房源的综合成本，自动计算 Google Maps 公共交通时间和费用。")

api_key = get_google_api_key()

# --- Sidebar: 配置 ---
with st.sidebar:
    st.header("全局配置")
    use_time_value = st.checkbox("启用时间价值折算", value=False)
    time_value_rate = st.number_input("时间价值 (日元/小时)", value=2000, step=100)
    debug_mode = st.toggle("Debug 模式", value=False)
    
    st.divider()
    st.info("💡 提示：API 经常返回空的票价（Route API 限制），若为空请手动在表格微调。")

# --- A. 房源对比表格 ---
st.subheader("1. 房源信息录入")

# 初始化表格数据
if "df_data" not in st.session_state:
    st.session_state.df_data = pd.DataFrame([
        {
            "房源名称": "示例房源 A", "房租(月/日元)": 85000, "管理费(月/日元)": 5000,
            "水电网(月/日元)": 15000, "手机(月/日元)": 3000, "餐饮买菜(月/日元)": 40000, "其他(月/日元)": 10000,
            "加权单程通勤时间(分钟)": 30.0, "加权单程通勤费用(日元)": 400.0,
            "A每周次数": 5.0, "B每周次数": 0.0
        }
    ])

edited_df = st.data_editor(
    st.session_state.df_data,
    num_rows="dynamic",
    use_container_width=True,
    key="editor"
)
st.session_state.df_data = edited_df

# --- B. 通勤自动计算区 ---
st.divider()
st.subheader("2. 通勤自动计算 (Google Routes API v2)")

col1, col2 = st.columns(2)
with col1:
    origin_addr = st.text_input("出发地址 (例如: 中野駅 / 東京都中野区...)", placeholder="输入住处地址")
    dest_a = st.text_input("目的地 A (例如: 新宿駅 / 语言学校地址)", placeholder="目的地 A")
    freq_a = st.number_input("A 每周去几次", value=5.0, step=0.5)

with col2:
    st.write("") # 占位
    dest_b = st.text_input("目的地 B (例如: 秋叶原 / 工作地点)", placeholder="目的地 B")
    freq_b = st.number_input("B 每周去几次", value=0.0, step=0.5)
    target_row = st.number_input("写入到房源第几行 (从1开始)", value=1, min_value=1, step=1)

# 操作按钮
calc_col1, calc_col2, calc_col3 = st.columns([1, 1, 1])

if calc_col1.button("🚀 计算通勤（公共交通）", use_container_width=True):
    if not origin_addr or (not dest_a and not dest_b):
        st.warning("请输入出发地和至少一个目的地。")
    else:
        with st.spinner("正在请求 Google Routes API..."):
            # 计算 A
            res_a = (0, 0, "Skip")
            if dest_a:
                res_a = get_transit_info_with_retry(origin_addr, dest_a, api_key, debug_mode)
            
            # 计算 B
            res_b = (0, 0, "Skip")
            if dest_b:
                res_b = get_transit_info_with_retry(origin_addr, dest_b, api_key, debug_mode)
            
            # 逻辑处理
            time_a, fare_a, status_a = res_a
            time_b, fare_b, status_b = res_b
            
            if status_a == "OK" or status_b == "OK":
                # 加权计算
                w_a = freq_a * 4.33
                w_b = freq_b * 4.33
                total_w = w_a + w_b
                
                if total_w > 0:
                    # 如果 API 没返回票价，设为 0 以防报错，并在 UI 提示
                    f_a = fare_a if fare_a else 0
                    f_b = fare_b if fare_b else 0
                    
                    weighted_time = (time_a * w_a + time_b * w_b) / total_w
                    weighted_fare = (f_a * w_a + f_b * w_b) / total_w
                    
                    # 更新 Session State
                    idx = target_row - 1
                    if idx < len(st.session_state.df_data):
                        st.session_state.df_data.iat[idx, 7] = round(weighted_time, 1)
                        st.session_state.df_data.iat[idx, 8] = round(weighted_fare, 1)
                        st.session_state.df_data.iat[idx, 9] = freq_a
                        st.session_state.df_data.iat[idx, 10] = freq_b
                        st.rerun()
                    else:
                        st.error(f"行数 {target_row} 超出当前表格范围。")
                
                if not fare_a or not fare_b:
                    st.info("ℹ️ 部分路线票价未能通过 API 获取，已设为 0，请根据地图链接手动填入。")
            else:
                st.error(f"计算失败: A-{status_a}, B-{status_b}")

if dest_a:
    calc_col2.link_button("🗺️ 查看 A 路线 (Google Maps)", get_google_maps_link(origin_addr, dest_a), use_container_width=True)
if dest_b:
    calc_col3.link_button("🗺️ 查看 B 路线 (Google Maps)", get_google_maps_link(origin_addr, dest_b), use_container_width=True)

# --- 5. 结果对比区 ---
st.divider()
st.subheader("3. 最终结果对比")

if not st.session_state.df_data.empty:
    res_df = st.session_state.df_data.copy()
    
    # 计算逻辑
    # 每月单程总次数 = (A次 + B次) * 4.33
    res_df["每月单程次数"] = (res_df["A每周次数"] + res_df["B每周次数"]) * 4.33
    
    res_df["固定支出/月"] = res_df.iloc[:, 1:7].sum(axis=1)
    # 通勤费用 = 加权单程票价 * 每月单程次数 * 2 (往返)
    res_df["通勤费用/月"] = res_df["加权单程通勤费用(日元)"] * res_df["每月单程次数"] * 2
    res_df["现金总成本/月"] = res_df["固定支出/月"] + res_df["通勤费用/月"]
    
    if use_time_value:
        # 通勤时间/月(小时) = 加权分钟 * 每月单程次数 * 2 / 60
        res_df["通勤时间/月(h)"] = (res_df["加权单程通勤时间(分钟)"] * res_df["每月单程次数"] * 2) / 60
        res_df["时间价值成本/月"] = res_df["通勤时间/月(h)"] * time_value_rate
        res_df["综合成本/月"] = res_df["现金总成本/月"] + res_df["时间价值成本/月"]
        res_df = res_df.sort_values("综合成本/月")
    else:
        res_df = res_df.sort_values("现金总成本/月")

    # 美化显示
    st.dataframe(
        res_df.style.highlight_min(subset=["现金总成本/月"] if not use_time_value else ["综合成本/月"], color="#2E7D32"),
        use_container_width=True
    )

    # --- 6. 导出 ---
    csv = res_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 下载生活成本对比.csv",
        data=csv,
        file_name="生活成本对比.csv",
        mime="text/csv",
    )
else:
    st.write("请在上方表格中添加房源数据。")

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
import urllib.parse

# --- 1. 初始化配置 ---
st.set_page_config(page_title="东京生活成本计算器-稳定修复版", layout="wide")
TOKYO_TZ = pytz.timezone("Asia/Tokyo")

def get_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 请在 Streamlit Secrets 中配置 GOOGLE_MAPS_API_KEY")
    st.stop()

# --- 2. 核心逻辑：解决报错的关键 ---

def get_precise_geo(address, api_key):
    """
    解决地址歧义：强制增加 'Tokyo, Japan' 后缀
    """
    if not address: return None
    refined_query = f"{address}, Tokyo, Japan" if "Japan" not in address else address
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(refined_query)}&key={api_key}&language=ja"
    try:
        resp = requests.get(url, timeout=10).json()
        if resp["status"] == "OK":
            res = resp["results"][0]
            return {"id": res["place_id"], "name": res["formatted_address"]}
    except Exception: pass
    return None

def fetch_transit_data(o_id, d_id, api_key):
    """
    解决 400 错误与深夜停运：
    1. 使用 Directions API (V1) 避免 V2 的参数冲突
    2. 强制模拟下周一 08:30，确保永远有电车班次
    """
    now = datetime.now(TOKYO_TZ)
    # 计算下周一的日期
    days_to_monday = (7 - now.weekday()) % 7
    if days_to_monday == 0: days_to_monday = 7
    target_time = (now + timedelta(days=days_to_monday)).replace(hour=8, minute=30, second=0, microsecond=0)
    
    # 采用 Unix 时间戳格式，这是最稳定的格式
    departure_timestamp = int(target_time.timestamp())
    
    url = (f"https://maps.googleapis.com/maps/api/directions/json?"
           f"origin=place_id:{o_id}&destination=place_id:{d_id}&mode=transit&"
           f"departure_time={departure_timestamp}&key={api_key}&language=ja")
    
    try:
        resp = requests.get(url, timeout=10).json()
        if resp["status"] == "OK":
            route = resp["routes"][0]["legs"][0]
            t = route["duration"]["value"] // 60
            # 提取票价，如果 API 没返回则设为 0
            f = int(resp["routes"][0].get("fare", {}).get("value", 0))
            return t, f
    except Exception: pass
    return None, None

def make_manual_link(o_addr, d_addr):
    """保底方案：如果自动抓取失败，生成网页链接"""
    return f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(o_addr)}&destination={urllib.parse.quote(d_addr)}&travelmode=transit"

# --- 3. UI 界面 ---

st.title("🇯🇵 东京生活成本计算器 (修复版)")
api_key = get_api_key()

# A. 房源数据表
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([{
        "房源名称": "默认房源", "房租": 85000, "管理费": 5000, "水电网": 15000, "手机": 3000, 
        "餐饮": 40000, "其他": 10000, "时间(分)": 30.0, "票价(円)": 200.0, "A周频": 5.0, "B周频": 0.0
    }])

st.subheader("1. 房源对比清单")
st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

st.divider()

# B. 通勤计算区
st.subheader("2. 自动抓取通勤数据")
st.info("提示：系统强制模拟『下周一早高峰 08:30』进行检索，避开深夜停运时段。")

c1, c2 = st.columns(2)
with c1:
    origin_in = st.text_input("住处起点", value="新大久保駅")
    dest_a_in = st.text_input("目的地 A", value="豪徳寺駅")
    freq_a = st.number_input("A每周天数", value=5.0)
with c2:
    row_to_update = st.number_input("更新到第几行", value=1, min_value=1)
    dest_b_in = st.text_input("目的地 B (可选)", value="")
    freq_b = st.number_input("B每周天数", value=0.0)

if st.button("🚀 开启同步：穿透检索路径", use_container_width=True):
    with st.spinner("正在检索实时班次..."):
        o_geo = get_precise_geo(origin_in, api_key)
        if not o_geo:
            st.error(f"❌ 无法识别起点地址: {origin_in}")
        else:
            results = []
            for label, addr, freq in [("A", dest_a_in, freq_a), ("B", dest_b_in, freq_b)]:
                if addr and freq > 0:
                    d_geo = get_precise_geo(addr, api_key)
                    if d_geo:
                        t, f = fetch_transit_data(o_geo["id"], d_geo["id"], api_key)
                        if t is not None:
                            results.append({"t": t, "f": f, "w": freq})
                            st.success(f"✅ 路线 {label} 抓取成功：{t}分钟 / {f}日元")
                        else:
                            st.warning(f"⚠️ 路线 {label} 自动检索失败（可能无直达）。")
                            st.link_button(f"🌐 手动查看路线 {label}", make_manual_link(origin_in, addr))
            
            # 安全更新表格数据
            if results:
                total_w = sum(r['w'] for r in results)
                avg_t = sum(r['t'] * r['w'] for r in results) / total_w
                avg_f = sum(r['f'] * r['w'] for r in results) / total_w
                
                idx = int(row_to_update - 1)
                if idx < len(st.session_state.df):
                    st.session_state.df.iat[idx, 7] = round(avg_t, 1)
                    st.session_state.df.iat[idx, 8] = round(avg_f, 1)
                    st.session_state.df.iat[idx, 9] = freq_a
                    st.session_state.df.iat[idx, 10] = freq_b
                    st.rerun()

# C. 汇总分析
st.divider()
st.subheader("3. 综合支出月度汇总")
final_df = st.session_state.df.copy()
if not final_df.empty:
    # 逻辑计算
    final_df["月通勤总次"] = (final_df["A周频"] + final_df["B周频"]) * 4.33 * 2
    final_df["月固定成本"] = final_df.iloc[:, 1:7].astype(float).sum(axis=1)
    final_df["月通勤成本"] = final_df["票价(円)"] * final_df["月通勤总次"]
    final_df["月总支出"] = final_df["月固定成本"] + final_df["月通勤成本"]
    st.dataframe(final_df.sort_values("月总支出"), use_container_width=True)

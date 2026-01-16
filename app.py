import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
import urllib.parse

# --- 1. 基础配置 ---
st.set_page_config(page_title="东京生活成本计算器-终极双工版", layout="wide")
TOKYO_TZ = pytz.timezone("Asia/Tokyo")

def get_google_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    st.error("❌ 未发现 API Key")
    st.stop()

# --- 2. 增强检索与链接生成 ---

def get_web_maps_url(origin, dest):
    """生成网页版 Google Maps 链接作为保底方案"""
    params = {
        "origin": origin,
        "destination": dest,
        "travelmode": "transit"
    }
    return f"https://www.google.com/maps/dir/?api=1&{urllib.parse.urlencode(params)}"

def get_geo_info(address, api_key):
    """尝试通过更宽泛的区域限定来找地址"""
    if not address: return None
    # 增加区域限定提高精度
    search_addr = f"{address}, Tokyo, Japan" if "Japan" not in address else address
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(search_addr)}&key={api_key}&language=ja"
    try:
        data = requests.get(url).json()
        if data["status"] == "OK":
            res = data["results"][0]
            return {"id": res["place_id"], "name": res["formatted_address"]}
    except: pass
    return None

def fetch_transit_data(o_id, d_id, api_key):
    """尝试获取路径数据"""
    # 设定为下个工作日早 8:30
    now = datetime.now(TOKYO_TZ)
    target = now + timedelta(days=(7 - now.weekday()) % 7)
    target = target.replace(hour=8, minute=30, second=0)
    
    url = (f"https://maps.googleapis.com/maps/api/directions/json?"
           f"origin=place_id:{o_id}&destination=place_id:{d_id}&mode=transit&"
           f"departure_time={int(target.timestamp())}&key={api_key}&language=ja")
    try:
        resp = requests.get(url).json()
        if resp["status"] == "OK":
            route = resp["routes"][0]["legs"][0]
            t = route["duration"]["value"] // 60
            f = int(resp["routes"][0].get("fare", {}).get("value", 0))
            return t, f
    except: pass
    return None, None

# --- 3. UI 布局 ---

st.title("🇯🇵 东京生活成本计算器 (自动检索+手动保底)")
api_key = get_google_api_key()

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([{
        "房源名称": "默认房源", "房租": 85000, "管理费": 5000, "水电网": 15000, "手机": 3000, 
        "餐饮": 40000, "其他": 10000, "加权时间(分)": 30.0, "单程票价(円)": 200.0, "A周频": 5.0, "B周频": 0.0
    }])

st.info("💡 提示：若自动检索失败，可点击下方生成的链接查看路径，并直接在上方表格手动修改数据。")

# 1. 数据编辑区
st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

st.divider()

# 2. 检索区
st.subheader("🔍 通勤路径检索")
c1, c2 = st.columns(2)
with c1:
    origin = st.text_input("出发住处", value="新大久保駅")
    dest_a = st.text_input("目的地 A", value="山下駅(東京)")
    freq_a = st.number_input("A每周天数", value=5.0)
with c2:
    row_idx = st.number_input("更新到表格第几行", value=1, min_value=1)
    dest_b = st.text_input("目的地 B (可选)", value="")
    freq_b = st.number_input("B每周天数", value=0.0)

if st.button("🚀 尝试自动抓取数据", use_container_width=True):
    with st.spinner("正在检索..."):
        o_geo = get_geo_info(origin, api_key)
        if not o_geo:
            st.error("找不到起点地址，请检查拼写")
        else:
            results = []
            for label, d_addr in [("A", dest_a), ("B", dest_b)]:
                if d_addr:
                    d_geo = get_geo_info(d_addr, api_key)
                    if d_geo:
                        t, f = fetch_transit_data(o_geo["id"], d_geo["id"], api_key)
                        results.append({"label": label, "t": t, "f": f, "addr": d_addr})
            
            # 计算并写回
            if results:
                weighted_t, weighted_f, total_w = 0, 0, 0
                for r in results:
                    weight = freq_a if r["label"]=="A" else freq_b
                    if r["t"] is not None:
                        weighted_t += r["t"] * weight
                        weighted_f += r["f"] * weight
                        total_w += weight
                        st.success(f"✅ 路线 {r['label']} 抓取成功: {r['t']}分 / {r['f']}円")
                    else:
                        st.warning(f"⚠️ 自动检索路线 {r['label']} 失败。")
                        st.link_button(f"🌐 点击在 Google Maps 中手动查看路线 {r['label']}", get_web_maps_url(origin, r['addr']))
                
                if total_w > 0:
                    i = int(row_idx - 1)
                    if i < len(st.session_state.df):
                        st.session_state.df.iat[i, 7] = round(weighted_t / total_w, 1)
                        st.session_state.df.iat[i, 8] = round(weighted_f / total_w, 1)
                        st.session_state.df.iat[i, 9] = freq_a
                        st.session_state.df.iat[i, 10] = freq_b
                        st.rerun()

# --- 4. 汇总报告 ---
st.divider()
st.subheader("📊 月度成本分析汇总")
res_df = st.session_state.df.copy()
if not res_df.empty:
    res_df["月通勤次数"] = (res_df["A周频"] + res_df["B周频"]) * 4.33 * 2
    res_df["月固定成本"] = res_df.iloc[:, 1:7].sum(axis=1)
    res_df["月通勤成本"] = res_df["单程票价(円)"] * res_df["月通勤次数"]
    res_df["月现金总支出"] = res_df["月固定成本"] + res_df["月通勤成本"]
    
    st.dataframe(res_df.sort_values("月现金总支出"), use_container_width=True)

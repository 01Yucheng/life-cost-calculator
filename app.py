import datetime as dt
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="生活成本计算器", layout="wide")
st.title("生活成本计算器（租金 + 通勤成本 + 通勤时间）")
st.caption("通勤自动计算：强制使用公共交通（transit），并提供 Google Maps 公共交通导航跳转。")

# -----------------------
# helpers
# -----------------------
def money(v: float) -> str:
    return f"¥{v:,.0f}"

def get_google_api_key():
    try:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    except Exception:
        return None

def google_maps_transit_link(origin_text: str, dest_text: str) -> str:
    o = quote_plus(origin_text.strip())
    d = quote_plus(dest_text.strip())
    return f"https://www.google.com/maps/dir/?api=1&origin={o}&destination={d}&travelmode=transit"

def departure_ts_jst(depart_date: dt.date, depart_time: dt.time) -> int:
    jst = ZoneInfo("Asia/Tokyo")
    depart_dt = dt.datetime.combine(depart_date, depart_time).replace(tzinfo=jst)

    # 5分钟取整（缓存更容易命中）
    minute = (depart_dt.minute // 5) * 5
    depart_dt = depart_dt.replace(minute=minute, second=0, microsecond=0)
    return int(depart_dt.timestamp())

def ensure_future_ts_jst(ts: int) -> tuple[int, bool]:
    """如果选择的出发时间在过去，自动改成 now+10min"""
    now = int(dt.datetime.now(tz=ZoneInfo("Asia/Tokyo")).timestamp())
    if ts <= now:
        return now + 10 * 60, True
    return ts, False

# -----------------------
# sidebar global params
# -----------------------
with st.sidebar:
    st.header("全局参数")
    commute_days = st.number_input("每月通勤天数（用于现金成本计算）", min_value=0, max_value=31, value=20, step=1)
    trips_per_day = st.number_input("每天通勤次数（去+回通常2）", min_value=0, max_value=6, value=2, step=1)

    use_time_value = st.toggle("把通勤时间折算成成本（时间价值）", value=True)
    time_value = None
    if use_time_value:
        time_value = st.number_input("你的时间价值（日元/小时）", min_value=0, value=1500, step=100)

    st.divider()
    debug = st.toggle("显示调试信息（排查用）", value=False)

# -----------------------
# Google Geocoding (address -> lat,lng)
# -----------------------
@st.cache_data(ttl=60 * 60 * 24 * 7)  # 7天缓存
def geocode_latlng(query: str, api_key: str):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": query,
        "region": "jp",
        "language": "ja",
        "key": api_key,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    status = data.get("status")
    if status != "OK":
        err = data.get("error_message", "")
        raise RuntimeError(f"Geocoding API 返回 {status}. {err}".strip())

    result = data["results"][0]
    loc = result["geometry"]["location"]
    formatted = result.get("formatted_address", query)
    return float(loc["lat"]), float(loc["lng"]), formatted

# -----------------------
# Directions transit only (lat,lng -> transit)
# -----------------------
@st.cache_data(ttl=60 * 60 * 24)  # 24h缓存
def directions_transit_cached(origin_lat: float, origin_lng: float,
                              dest_lat: float, dest_lng: float,
                              departure_ts: int, api_key: str):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{origin_lat},{origin_lng}",
        "destination": f"{dest_lat},{dest_lng}",
        "mode": "transit",                 # ✅ 强制公共交通
        "departure_time": departure_ts,    # 由上层保证是未来
        "language": "ja",
        "region": "jp",
        "key": api_key,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_directions_ok(data):
    route = data["routes"][0]
    leg = route["legs"][0]
    minutes = round(leg["duration"]["value"] / 60)

    fare_jpy = None
    fare = route.get("fare")
    if isinstance(fare, dict) and fare.get("currency") == "JPY" and "value" in fare:
        fare_jpy = float(fare["value"])

    summary = route.get("summary", "")
    return minutes, fare_jpy, summary

# -----------------------
# Listings table
# -----------------------
st.subheader("输入房源信息")

if "listings" not in st.session_state:
    st.session_state.listings = pd.DataFrame(
        [
            {
                "房源名称": "例：高田马场 1DK A",
                "房租(月/日元)": 110000,
                "管理费(月/日元)": 8000,
                "水电网(月/日元)": 12000,
                "手机(月/日元)": 3000,
                "餐饮买菜(月/日元)": 40000,
                "其他(月/日元)": 5000,
                "单程通勤时间(分钟)": 22,
                "单程通勤费用(日元)": 180,
            }
        ]
    )

edited = st.data_editor(
    st.session_state.listings,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)
st.session_state.listings = edited

# -----------------------
# Commute calculator (2 destinations weighted)
# -----------------------
st.divider()
st.subheader("通勤自动计算（强制公共交通 + 双目的地加权）")

api_key = get_google_api_key()
if api_key is None:
    st.warning(
        "未检测到 GOOGLE_MAPS_API_KEY。\n"
        "Streamlit Cloud：App → Settings → Secrets 添加：\n"
        'GOOGLE_MAPS_API_KEY="你的key"'
    )

# Origin + Destination A/B
origin_col, destA_col, destB_col = st.columns([1, 1, 1])

with origin_col:
    origin_addr = st.text_input("出发（住处地址/车站名）", value="浅草駅(東京)")

with destA_col:
    dest_A_default = "日本〒169-0073 Tokyo, Shinjuku City, Hyakunincho, 2 Chome−24−12 光信ビル"
    dest_A = st.text_input("目的地 A（语校/新大久保）", value=dest_A_default)
    freq_A = st.number_input("A 每周去几次", min_value=0.0, value=1.0, step=0.5)

with destB_col:
    dest_B_default = "日本〒116-0013 Tokyo, Arakawa City, Nishinippori, 2-chōme−12−5 尚藝舎ビル１階"
    dest_B = st.text_input("目的地 B（私塾/西日暮里）", value=dest_B_default)
    freq_B = st.number_input("B 每周去几次", min_value=0.0, value=0.5, step=0.5)  # ✅ 两周一次=0.5/周

date_col, time_col, row_col = st.columns([1, 1, 1])
with date_col:
    depart_date = st.date_input("出发日期", value=dt.date.today())
with time_col:
    depart_time = st.time_input("出发时间", value=dt.time(8, 30))
with row_col:
    target_row = st.number_input("写入到房源第几行（从1开始）", min_value=1, value=1, step=1)

mapsA = google_maps_transit_link(origin_addr, dest_A)
mapsB = google_maps_transit_link(origin_addr, dest_B)

btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
with btn_col1:
    calc_btn = st.button("计算通勤（公共交通）", type="primary", disabled=(api_key is None))
with btn_col2:
    st.link_button("Google Maps：去 A（公共交通）", mapsA)
with btn_col3:
    st.link_button("Google Maps：去 B（公共交通）", mapsB)

weeks_per_month = 4.33
monthly_oneway_A = freq_A * weeks_per_month   # 单程次数/月
monthly_oneway_B = freq_B * weeks_per_month

st.caption(
    f"按平均每月 {weeks_per_month:.2f} 周估算："
    f"A≈{monthly_oneway_A:.1f} 次/月，B≈{monthly_oneway_B:.1f} 次/月（单程次数）。"
)

if calc_btn:
    try:
        if not origin_addr.strip():
            st.error("请填写出发地址/车站名。")
            st.stop()
        if (not dest_A.strip()) or (not dest_B.strip()):
            st.error("请填写目的地 A 和 B。")
            st.stop()

        # 处理时间：保证 departure_time 不在过去
        ts = departure_ts_jst(depart_date, depart_time)
        ts, adjusted = ensure_future_ts_jst(ts)
        if adjusted:
            st.warning("你选择的出发时间已经过去，系统已自动改为：当前时间 + 10 分钟（JST）。")

        # 为了提高地点解析，补全“東京都 日本”（不改变你展示的原始文本）
        def enrich(q: str) -> str:
            s = q.strip()
            if ("日本" not in s) and ("Tokyo" not in s) and ("東京都" not in s):
                s += " 東京都 日本"
            return s

        origin_q = enrich(origin_addr)
        destA_q = enrich(dest_A)
        destB_q = enrich(dest_B)

        # Geocode
        o_lat, o_lng, o_fmt = geocode_latlng(origin_q, api_key)
        a_lat, a_lng, a_fmt = geocode_latlng(destA_q, api_key)
        b_lat, b_lng, b_fmt = geocode_latlng(destB_q, api_key)

        # Directions (transit only)
        dataA = directions_transit_cached(o_lat, o_lng, a_lat, a_lng, ts, api_key)
        statusA = dataA.get("status")

        dataB = directions_transit_cached(o_lat, o_lng, b_lat, b_lng, ts, api_key)
        statusB = dataB.get("status")

        # 显示结果或错误 + 始终给 Google Maps 链接（你要求的）
        okA = (statusA == "OK")
        okB = (statusB == "OK")

        if not okA:
            st.error(f"A 公共交通查询失败：{statusA}. {dataA.get('error_message','')}".strip())
            st.link_button("打开 Google Maps：A 公共交通导航", mapsA)

        if not okB:
            st.error(f"B 公共交通查询失败：{statusB}. {dataB.get('error_message','')}".strip())
            st.link_button("打开 Google Maps：B 公共交通导航", mapsB)

        if not (okA or okB):
            st.stop()

        # Parse OK ones
        minutes_A = fare_A = summary_A = None
        minutes_B = fare_B = summary_B = None

        if okA:
            minutes_A, fare_A, summary_A = parse_directions_ok(dataA)
            st.success(f"✅ A（语校）单程公共交通：{minutes_A} 分钟")
            if fare_A is not None:
                st.info(f"✅ A 单程票价（API返回）：{money(fare_A)}")
            if summary_A:
                st.caption(f"A 路线摘要：{summary_A}")
            st.link_button("在 Google Maps 打开 A 公共交通导航", mapsA)

        if okB:
            minutes_B, fare_B, summary_B = parse_directions_ok(dataB)
            st.success(f"✅ B（私塾）单程公共交通：{minutes_B} 分钟")
            if fare_B is not None:
                st.info(f"✅ B 单程票价（API返回）：{money(fare_B)}")
            if summary_B:
                st.caption(f"B 路线摘要：{summary_B}")
            st.link_button("在 Google Maps 打开 B 公共交通导航", mapsB)

        # Weighted merge (write back as weighted average "one-way")
        # 若某一条失败，就只按成功的那条来（频率权重也只用成功的部分）
        total_w = 0.0
        total_minutes = 0.0
        total_fare = 0.0
        fare_w = 0.0

        if okA and monthly_oneway_A > 0:
            total_w += monthly_oneway_A
            total_minutes += minutes_A * monthly_oneway_A
            if fare_A is not None:
                total_fare += fare_A * monthly_oneway_A
                fare_w += monthly_oneway_A

        if okB and monthly_oneway_B > 0:
            total_w += monthly_oneway_B
            total_minutes += minutes_B * monthly_oneway_B
            if fare_B is not None:
                total_fare += fare_B * monthly_oneway_B
                fare_w += monthly_oneway_B

        if total_w <= 0:
            st.error("A/B 的每周次数都是 0，无法计算加权通勤。")
            st.stop()

        avg_oneway_minutes = total_minutes / total_w
        avg_oneway_fare = (total_fare / fare_w) if fare_w > 0 else None

        # Write to table
        idx = int(target_row) - 1
        if 0 <= idx < len(st.session_state.listings):
            st.session_state.listings.loc[idx, "单程通勤时间(分钟)"] = int(round(avg_oneway_minutes))
            if avg_oneway_fare is not None:
                st.session_state.listings.loc[idx, "单程通勤费用(日元)"] = float(avg_oneway_fare)
            st.success(f"✅ 已把“加权平均单程通勤”写入到第 {target_row} 行")
        else:
            st.warning("行号超出范围：请先在上面表格添加足够的房源行。")

        if debug:
            st.write("解析到的出发地：", o_fmt)
            st.write("解析到的目的地A：", a_fmt)
            st.write("解析到的目的地B：", b_fmt)
            st.write("departure_ts（JST）：", ts)
            st.write("A/B 每月单程次数：", monthly_oneway_A, monthly_oneway_B)
            st.write("加权平均单程分钟：", avg_oneway_minutes)
            st.write("加权平均单程票价：", avg_oneway_fare)

    except Exception as e:
        st.error(str(e))

# -----------------------
# Cost comparison
# -----------------------
def calc_row(row, commute_days, trips_per_day, time_value):
    fixed = (
        float(row["房租(月/日元)"])
        + float(row["管理费(月/日元)"])
        + float(row["水电网(月/日元)"])
        + float(row["手机(月/日元)"])
        + float(row["餐饮买菜(月/日元)"])
        + float(row["其他(月/日元)"])
    )

    commute_cost = float(row["单程通勤费用(日元)"]) * trips_per_day * commute_days
    money_total = fixed + commute_cost  # ✅ 正确加号

    commute_minutes = float(row["单程通勤时间(分钟)"]) * trips_per_day * commute_days
    commute_hours = commute_minutes / 60.0

    time_cost = None
    total_with_time = None
    if time_value is not None:
        time_cost = commute_hours * float(time_value)
        total_with_time = money_total + time_cost

    return fixed, commute_cost, money_total, commute_hours, time_cost, total_with_time

st.divider()
st.subheader("结果对比")

if len(st.session_state.listings) == 0:
    st.info("请先在上面表格里添加至少一个房源。")
    st.stop()

results = []
for _, row in st.session_state.listings.iterrows():
    fixed, commute_cost, money_total, commute_hours, time_cost, total_with_time = calc_row(
        row, commute_days, trips_per_day, time_value
    )
    results.append(
        {
            "房源名称": row["房源名称"],
            "固定支出/月": fixed,
            "通勤费用/月": commute_cost,
            "现金总成本/月": money_total,
            "通勤时间/月(小时)": commute_hours,
            "时间折算成本/月": time_cost,
            "综合成本/月(现金+时间)": total_with_time,
        }
    )

df = pd.DataFrame(results)

if time_value is None:
    sort_col = "现金总成本/月"
else:
    sort_col = "综合成本/月(现金+时间)"

df_sorted = df.sort_values(by=sort_col, ascending=True)

df_show = df_sorted.copy()
for col in ["固定支出/月", "通勤费用/月", "现金总成本/月", "时间折算成本/月", "综合成本/月(现金+时间)"]:
    if col in df_show.columns:
        df_show[col] = df_show[col].apply(lambda x: "" if pd.isna(x) else money(float(x)))
df_show["通勤时间/月(小时)"] = df_show["通勤时间/月(小时)"].apply(lambda x: f"{float(x):.1f}")

st.caption(f"当前按「{sort_col}」从低到高排序。")
st.dataframe(df_show, use_container_width=True, hide_index=True)

st.subheader("导出")
csv = df_sorted.to_csv(index=False).encode("utf-8-sig")
st.download_button("下载 CSV 结果", data=csv, file_name="生活成本对比.csv", mime="text/csv")

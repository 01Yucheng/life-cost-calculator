import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="生活成本计算器", layout="wide")
st.title("生活成本计算器（租金 + 通勤成本 + 通勤时间）")
st.caption("提示：通勤时间建议按“门到门”（走路+等车+换乘+进出站+车上时间）更真实。")

def money(v: float) -> str:
    return f"¥{v:,.0f}"

# =========================
# Sidebar: 全局参数
# =========================
with st.sidebar:
    st.header("全局参数")
    commute_days = st.number_input("每月通勤天数（上课/实习）", min_value=0, max_value=31, value=20, step=1)
    trips_per_day = st.number_input("每天通勤次数（去+回通常2）", min_value=0, max_value=6, value=2, step=1)

    use_time_value = st.toggle("把通勤时间折算成成本（时间价值）", value=True)
    time_value = None
    if use_time_value:
        time_value = st.number_input("你的时间价值（日元/小时）", min_value=0, value=1500, step=100)

    st.divider()
    debug = st.toggle("显示调试信息（排查用）", value=False)

# =========================
# Keys
# =========================
def get_google_api_key():
    try:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    except Exception:
        return None

# =========================
# Time helper (JST)
# =========================
def departure_ts_jst(depart_date: dt.date, depart_time: dt.time) -> int:
    jst = ZoneInfo("Asia/Tokyo")
    depart_dt = dt.datetime.combine(depart_date, depart_time).replace(tzinfo=jst)

    # 5分钟取整
    minute = (depart_dt.minute // 5) * 5
    depart_dt = depart_dt.replace(minute=minute, second=0, microsecond=0)
    return int(depart_dt.timestamp())

# =========================
# Geocoding
# =========================
@st.cache_data(ttl=60 * 60 * 24 * 7)
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

# =========================
# Directions (transit + fallback)
# =========================
@st.cache_data(ttl=60 * 60 * 24)
def directions_cached(origin_lat, origin_lng, dest_lat, dest_lng, departure_ts, api_key, mode="transit"):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{origin_lat},{origin_lng}",
        "destination": f"{dest_lat},{dest_lng}",
        "mode": mode,
        "departure_time": departure_ts,
        "language": "ja",
        "region": "jp",
        "key": api_key,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_directions(data):
    route = data["routes"][0]
    leg = route["legs"][0]
    minutes = round(leg["duration"]["value"] / 60)

    fare_jpy = None
    fare = route.get("fare")
    if isinstance(fare, dict) and fare.get("currency") == "JPY" and "value" in fare:
        fare_jpy = float(fare["value"])

    summary = route.get("summary", "")
    return minutes, fare_jpy, summary

# =========================
# 房源表格输入
# =========================
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

# =========================
# 通勤自动计算
# =========================
st.divider()
st.subheader("通勤自动计算（输入地址 → 自动生成通勤时间/票价）")

api_key = get_google_api_key()
api_key_present = api_key is not None

if not api_key_present:
    st.warning(
        "未检测到 GOOGLE_MAPS_API_KEY。\n"
        "Streamlit Cloud：App → Settings → Secrets 添加：\n"
        'GOOGLE_MAPS_API_KEY="你的key"'
    )

colA, colB = st.columns([1, 1])
with colA:
    origin_addr = st.text_input("出发（住处地址/车站名）", value="浅草駅(東京)")
with colB:
    dest_addr = st.text_input("目的地（默认语校附近，可改）", value="新大久保駅(東京)")

colC, colD, colE = st.columns([1, 1, 1])
with colC:
    depart_date = st.date_input("出发日期", value=dt.date.today())
with colD:
    depart_time = st.time_input("出发时间", value=dt.time(8, 30))
with colE:
    target_row = st.number_input("写入到房源第几行（从1开始）", min_value=1, value=1, step=1)

calc_btn = st.button("计算通勤（公共交通）", type="primary", disabled=not api_key_present)

if calc_btn:
    try:
        if not origin_addr.strip() or not dest_addr.strip():
            st.error("请填写出发和目的地。")
        else:
            origin_q = origin_addr.strip()
            dest_q = dest_addr.strip()

            # 补全提高识别
            if "日本" not in origin_q and "東京都" not in origin_q and "Tokyo" not in origin_q:
                origin_q += " 東京都 日本"
            if "日本" not in dest_q and "東京都" not in dest_q and "Tokyo" not in dest_q:
                dest_q += " 東京都 日本"

            o_lat, o_lng, o_fmt = geocode_latlng(origin_q, api_key)
            d_lat, d_lng, d_fmt = geocode_latlng(dest_q, api_key)

            ts = departure_ts_jst(depart_date, depart_time)

            # 1) 先试 transit
            data = directions_cached(o_lat, o_lng, d_lat, d_lng, ts, api_key, mode="transit")
            status = data.get("status")

            used_mode = "transit"
            if status == "ZERO_RESULTS":
                # 2) fallback：改用 driving，保证你至少得到一个时间用于比较房源
                data = directions_cached(o_lat, o_lng, d_lat, d_lng, ts, api_key, mode="driving")
                used_mode = "driving"
                status = data.get("status")

            if status != "OK":
                err = data.get("error_message", "")
                st.error(f"Directions API 返回 {status}. {err}".strip())
            else:
                minutes, fare_jpy, summary = parse_directions(data)

                if used_mode == "transit":
                    st.success(f"✅ 单程通勤时间（公共交通）：{minutes} 分钟")
                else:
                    st.warning(f"⚠️ 公共交通无结果，已改用 driving 估算：{minutes} 分钟（仅做参考）")

                if fare_jpy is not None and used_mode == "transit":
                    st.info(f"✅ 单程票价（API返回）：{money(fare_jpy)}")
                elif used_mode == "transit":
                    st.warning("票价本次未返回（部分路线/地区 Google 不提供 fare 字段）。")

                if summary:
                    st.caption(f"路线摘要：{summary}")

                if debug:
                    st.write("解析到的出发地：", o_fmt)
                    st.write("解析到的目的地：", d_fmt)
                    st.write("出发时间戳（JST）：", ts)
                    st.write("使用 mode：", used_mode)

                # 写回表格
                idx = int(target_row) - 1
                if 0 <= idx < len(st.session_state.listings):
                    st.session_state.listings.loc[idx, "单程通勤时间(分钟)"] = minutes
                    if fare_jpy is not None and used_mode == "transit":
                        st.session_state.listings.loc[idx, "单程通勤费用(日元)"] = float(fare_jpy)
                    st.success(f"✅ 已写入到第 {target_row} 行")
                else:
                    st.warning("行号超出范围：请先在上面表格添加足够的房源行。")

    except Exception as e:
        st.error(str(e))

# =========================
# 成本计算
# =========================
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

    # ✅ 修复：这里必须是加号
    money_total = fixed + commute_cost

    commute_minutes = float(row["单程通勤时间(分钟)"]) * trips_per_day * commute_days
    commute_hours = commute_minutes / 60.0

    time_cost = None
    total_with_time = None
    if time_value is not None:
        time_cost = commute_hours * float(time_value)
        total_with_time = money_total + time_cost

    return fixed, commute_cost, money_total, commute_hours, time_cost, total_with_time

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

st.divider()
st.subheader("结果对比")

if time_value is None:
    sort_col = "现金总成本/月"
    df_sorted = df.sort_values(by=sort_col, ascending=True)
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

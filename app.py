import datetime as dt
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st


# =========================
# App Config
# =========================
st.set_page_config(page_title="生活成本计算器", layout="wide")
st.title("生活成本计算器（租金 + 通勤成本 + 通勤时间）")
st.caption("通勤自动计算：强制公共交通（TRANSIT），双目的地按频率加权，并提供 Google Maps 公交导航跳转。")

JST = ZoneInfo("Asia/Tokyo")
WEEKS_PER_MONTH = 4.33


# =========================
# Helpers
# =========================
def money(v: float) -> str:
    return f"¥{v:,.0f}"


def get_google_api_key() -> str | None:
    try:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    except Exception:
        return None


def maps_transit_link(origin_text: str, dest_text: str) -> str:
    o = quote_plus(origin_text.strip())
    d = quote_plus(dest_text.strip())
    return f"https://www.google.com/maps/dir/?api=1&origin={o}&destination={d}&travelmode=transit"


def normalize_departure_ts_jst(date_: dt.date, time_: dt.time) -> int:
    """生成 JST 时间戳，并做 5 分钟取整（提高缓存命中）。"""
    depart_dt = dt.datetime.combine(date_, time_).replace(tzinfo=JST)
    minute = (depart_dt.minute // 5) * 5
    depart_dt = depart_dt.replace(minute=minute, second=0, microsecond=0)
    return int(depart_dt.timestamp())


def ensure_future_ts(ts: int) -> tuple[int, bool]:
    """如果用户选择的时间在过去：自动推到 now+10min（JST）。"""
    now = int(dt.datetime.now(tz=JST).timestamp())
    if ts <= now:
        return now + 10 * 60, True
    return ts, False


def enrich_jp_query(text: str) -> str:
    """提高站名/地址解析稳定性：补上“東京都 日本”（不改变用户原始输入展示）。"""
    s = text.strip()
    if ("日本" not in s) and ("Tokyo" not in s) and ("東京都" not in s):
        s += " 東京都 日本"
    return s


def extract_error_message(payload: dict) -> str:
    """Routes API 失败时一般是 {error:{message:...}}；兼容旧字段 error_message。"""
    if not isinstance(payload, dict):
        return ""
    e = payload.get("error")
    if isinstance(e, dict):
        msg = e.get("message")
        if isinstance(msg, str):
            return msg
    msg2 = payload.get("error_message")
    return msg2 if isinstance(msg2, str) else ""


# =========================
# Google APIs
# =========================
@st.cache_data(ttl=60 * 60 * 24 * 7)
def geocode(query: str, api_key: str) -> tuple[float, float, str]:
    """Geocoding API: query -> (lat, lng, formatted_address)"""
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
        msg = data.get("error_message", "")
        raise RuntimeError(f"Geocoding API 返回 {status}. {msg}".strip())

    result = data["results"][0]
    loc = result["geometry"]["location"]
    formatted = result.get("formatted_address", query)
    return float(loc["lat"]), float(loc["lng"]), formatted


@st.cache_data(ttl=60 * 60 * 12)
def routes_compute_transit(
    o_lat: float, o_lng: float,
    d_lat: float, d_lng: float,
    ts: int,
    api_key: str,
    time_mode: str,  # "departure" or "arrival"
) -> dict:
    """
    Routes API v2: computeRoutes (TRANSIT)
    - 保留 HTTP 状态与原始返回，方便排错
    - 不 raise_for_status（否则拿不到 error body）
    """
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    field_mask = ",".join([
        "routes.duration",
        "routes.legs.duration",
        "routes.travelAdvisory.transitFare",
    ])

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }

    body = {
        "origin": {"location": {"latLng": {"latitude": o_lat, "longitude": o_lng}}},
        "destination": {"location": {"latLng": {"latitude": d_lat, "longitude": d_lng}}},
        "travelMode": "TRANSIT",
        "languageCode": "ja",
        "regionCode": "JP",
    }

    when = dt.datetime.fromtimestamp(ts, tz=JST).isoformat()
    if time_mode == "arrival":
        body["arrivalTime"] = when
    else:
        body["departureTime"] = when

    r = requests.post(url, headers=headers, json=body, timeout=20)
    raw_text = r.text

    try:
        data = r.json()
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {"_non_dict_json": str(data)}

    # debug fields
    data["_http_status"] = r.status_code
    data["_raw_text"] = raw_text[:2000]
    data["_sent_body"] = body
    data["_sent_field_mask"] = field_mask

    return data


def parse_route(data: dict) -> tuple[int, float | None, str]:
    """
    Routes API data 解析：
    - minutes：routes[0].duration（如 "1234s"）
    - fare_jpy：routes[0].travelAdvisory.transitFare（可能为空）
    - summary：Routes API 没有旧 summary，这里返回空字符串
    """
    if not data.get("routes"):
        raise RuntimeError("Routes API 未返回 routes。")

    r0 = data["routes"][0]

    dur = r0.get("duration", "0s")
    seconds = int(dur[:-1]) if isinstance(dur, str) and dur.endswith("s") else 0
    minutes = max(0, round(seconds / 60))

    fare_jpy = None
    adv = r0.get("travelAdvisory", {}) or {}
    tf = adv.get("transitFare")
    if isinstance(tf, dict) and tf.get("currencyCode") == "JPY":
        units = float(tf.get("units", 0) or 0)
        nanos = float(tf.get("nanos", 0) or 0)
        fare_jpy = units + nanos / 1e9

    summary = ""
    return minutes, fare_jpy, summary


def transit_route_with_retry(
    o_lat: float, o_lng: float,
    d_lat: float, d_lng: float,
    ts: int,
    api_key: str
) -> tuple[bool, dict, str]:
    """
    强制公共交通（TRANSIT）
    - 先 departureTime
    - 再 arrivalTime 重试（仍然 TRANSIT）
    """
    data = routes_compute_transit(o_lat, o_lng, d_lat, d_lng, ts, api_key, time_mode="departure")
    if data.get("routes"):
        data.setdefault("status", "OK")
        return True, data, "routes_transit_departure"

    data2 = routes_compute_transit(o_lat, o_lng, d_lat, d_lng, ts, api_key, time_mode="arrival")
    if data2.get("routes"):
        data2.setdefault("status", "OK")
        return True, data2, "routes_transit_arrival"

    # 失败：尽量给出可读错误
    err = extract_error_message(data2)
    if err:
        data2["status"] = "ERROR"
        data2["error_message"] = err
    else:
        data2["status"] = "NO_ROUTES"

    return False, data2, "routes_transit_arrival"


def weighted_merge(
    a_ok: bool, a_minutes: int | None, a_fare: float | None, a_w: float,
    b_ok: bool, b_minutes: int | None, b_fare: float | None, b_w: float,
) -> tuple[float, float | None]:
    """返回：加权平均单程 minutes、加权平均单程 fare（若至少一条有fare才给）"""
    w_total = 0.0
    minutes_total = 0.0

    fare_w_total = 0.0
    fare_total = 0.0

    if a_ok and a_w > 0 and a_minutes is not None:
        w_total += a_w
        minutes_total += a_minutes * a_w
        if a_fare is not None:
            fare_w_total += a_w
            fare_total += a_fare * a_w

    if b_ok and b_w > 0 and b_minutes is not None:
        w_total += b_w
        minutes_total += b_minutes * b_w
        if b_fare is not None:
            fare_w_total += b_w
            fare_total += b_fare * b_w

    if w_total <= 0:
        raise RuntimeError("A/B 都没有可用的公共交通结果，无法加权。")

    avg_minutes = minutes_total / w_total
    avg_fare = (fare_total / fare_w_total) if fare_w_total > 0 else None
    return avg_minutes, avg_fare


# =========================
# Sidebar
# =========================
with st.sidebar:
    st.header("设置")
    use_time_value = st.toggle("把通勤时间折算为成本（时间价值）", value=True)
    time_value = None
    if use_time_value:
        time_value = st.number_input("你的时间价值（日元/小时）", min_value=0, value=1500, step=100)

    debug = st.toggle("显示调试信息", value=False)


# =========================
# Listing Table
# =========================
st.subheader("房源表格（可添加多行对比）")

if "listings" not in st.session_state:
    st.session_state.listings = pd.DataFrame(
        [{
            "房源名称": "例：浅草 1K",
            "房租(月/日元)": 110000,
            "管理费(月/日元)": 8000,
            "水电网(月/日元)": 12000,
            "手机(月/日元)": 3000,
            "餐饮买菜(月/日元)": 40000,
            "其他(月/日元)": 5000,
            "加权单程通勤时间(分钟)": 0,
            "加权单程通勤费用(日元)": 0,
            "A每周次数": 1.0,
            "B每周次数": 0.5,
        }]
    )

st.session_state.listings = st.data_editor(
    st.session_state.listings,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)


# =========================
# Commute Section (TRANSIT only, 2 destinations)
# =========================
st.divider()
st.subheader("通勤自动计算（强制公共交通 + 双目的地加权）")

api_key = get_google_api_key()
if api_key is None:
    st.warning(
        "未检测到 GOOGLE_MAPS_API_KEY。\n"
        "Streamlit Cloud：App → Settings → Secrets 添加：\n"
        'GOOGLE_MAPS_API_KEY="你的key"'
    )

col_o, col_a, col_b = st.columns([1, 1, 1])

with col_o:
    origin = st.text_input("出发（住处地址/车站名）", value="浅草駅(東京)")

with col_a:
    destA_default = "日本〒169-0073 Tokyo, Shinjuku City, Hyakunincho, 2 Chome−24−12 光信ビル"
    destA = st.text_input("目的地 A（语校/新大久保）", value=destA_default)
    freqA = st.number_input("A 每周去几次", min_value=0.0, value=1.0, step=0.5)

with col_b:
    destB_default = "日本〒116-0013 Tokyo, Arakawa City, Nishinippori, 2-chōme−12−5 尚藝舎ビル１階"
    destB = st.text_input("目的地 B（私塾/西日暮里）", value=destB_default)
    freqB = st.number_input("B 每周去几次", min_value=0.0, value=0.5, step=0.5)

col_d, col_t, col_r = st.columns([1, 1, 1])
with col_d:
    depart_date = st.date_input("出发日期", value=dt.date.today())
with col_t:
    depart_time = st.time_input("出发时间", value=dt.time(8, 30))
with col_r:
    target_row = st.number_input("写入到房源第几行（从1开始）", min_value=1, value=1, step=1)

mapsA = maps_transit_link(origin, destA)
mapsB = maps_transit_link(origin, destB)

btn1, btn2, btn3 = st.columns([1, 1, 1])
with btn1:
    run_btn = st.button("计算通勤（公共交通）", type="primary", disabled=(api_key is None))
with btn2:
    st.link_button("Google Maps：去 A（公共交通）", mapsA)
with btn3:
    st.link_button("Google Maps：去 B（公共交通）", mapsB)

monthly_oneway_A = freqA * WEEKS_PER_MONTH
monthly_oneway_B = freqB * WEEKS_PER_MONTH
st.caption(
    f"按平均每月 {WEEKS_PER_MONTH:.2f} 周估算：A≈{monthly_oneway_A:.1f} 次/月，"
    f"B≈{monthly_oneway_B:.1f} 次/月（单程次数）。"
)

if run_btn:
    try:
        if not origin.strip():
            st.error("请填写出发（住处地址/车站名）。")
            st.stop()

       # ✅ 强制固定公共交通可用时间：明天 09:00（JST）
        tomorrow = (dt.datetime.now(tz=JST) + dt.timedelta(days=1)).date()
        fixed_time = dt.time(9, 0)
        ts = normalize_departure_ts_jst(tomorrow, fixed_time)
        adjusted = True
        st.info("为保证公共交通有结果，已强制使用：明天 09:00（JST）进行查询（仅用于估算）。")


        # Geocode
        o_lat, o_lng, o_fmt = geocode(enrich_jp_query(origin), api_key)
        a_lat, a_lng, a_fmt = geocode(enrich_jp_query(destA), api_key)
        b_lat, b_lng, b_fmt = geocode(enrich_jp_query(destB), api_key)

        # Transit A/B (Routes API) with retry
        okA, dataA, modeA = transit_route_with_retry(o_lat, o_lng, a_lat, a_lng, ts, api_key)
        okB, dataB, modeB = transit_route_with_retry(o_lat, o_lng, b_lat, b_lng, ts, api_key)

        if not okA:
            st.error(f"A 公共交通查询失败：{dataA.get('status','NO_ROUTES')}. {extract_error_message(dataA)}".strip())
            st.link_button("打开 Google Maps：A 公共交通导航", mapsA)
            if debug:
                st.subheader("Debug: A 返回原始数据")
                st.json(dataA)

        if not okB:
            st.error(f"B 公共交通查询失败：{dataB.get('status','NO_ROUTES')}. {extract_error_message(dataB)}".strip())
            st.link_button("打开 Google Maps：B 公共交通导航", mapsB)
            if debug:
                st.subheader("Debug: B 返回原始数据")
                st.json(dataB)

        if not (okA or okB):
            st.stop()

        a_minutes = a_fare = a_summary = None
        b_minutes = b_fare = b_summary = None

        if okA:
            a_minutes, a_fare, a_summary = parse_route(dataA)
            st.success(f"✅ A 单程公共交通：{a_minutes} 分钟（{modeA}）")
            if a_fare is not None:
                st.info(f"✅ A 单程票价：{money(a_fare)}")
            else:
                st.warning("A：API 未返回票价（常见情况），可点击 Google Maps 查看票价。")
            st.link_button("在 Google Maps 打开 A 公共交通导航", mapsA)

        if okB:
            b_minutes, b_fare, b_summary = parse_route(dataB)
            st.success(f"✅ B 单程公共交通：{b_minutes} 分钟（{modeB}）")
            if b_fare is not None:
                st.info(f"✅ B 单程票价：{money(b_fare)}")
            else:
                st.warning("B：API 未返回票价（常见情况），可点击 Google Maps 查看票价。")
            st.link_button("在 Google Maps 打开 B 公共交通导航", mapsB)

        # Weighted merge (one-way weighted avg)
        avg_minutes, avg_fare = weighted_merge(
            okA, a_minutes, a_fare, monthly_oneway_A,
            okB, b_minutes, b_fare, monthly_oneway_B
        )

        idx = int(target_row) - 1
        if 0 <= idx < len(st.session_state.listings):
            st.session_state.listings.loc[idx, "加权单程通勤时间(分钟)"] = int(round(avg_minutes))
            if avg_fare is not None:
                st.session_state.listings.loc[idx, "加权单程通勤费用(日元)"] = float(avg_fare)

            st.session_state.listings.loc[idx, "A每周次数"] = float(freqA)
            st.session_state.listings.loc[idx, "B每周次数"] = float(freqB)
            st.success(f"✅ 已写入到第 {target_row} 行（加权平均单程通勤）")
        else:
            st.warning("行号超出范围：请先在表格添加足够的房源行。")

        if debug:
            st.write("出发解析：", o_fmt)
            st.write("A解析：", a_fmt)
            st.write("B解析：", a_fmt)
            st.write("ts(JST)：", ts)
            st.write("A/B 每月单程次数：", monthly_oneway_A, monthly_oneway_B)
            st.write("加权平均单程分钟：", avg_minutes)
            st.write("加权平均单程票价：", avg_fare)

    except Exception as e:
        st.error(str(e))


# =========================
# Cost Comparison
# =========================
st.divider()
st.subheader("结果对比（含通勤时间折算）")


def row_total_cost(row: pd.Series, time_value_yph: float | None):
    fixed = (
        float(row.get("房租(月/日元)", 0))
        + float(row.get("管理费(月/日元)", 0))
        + float(row.get("水电网(月/日元)", 0))
        + float(row.get("手机(月/日元)", 0))
        + float(row.get("餐饮买菜(月/日元)", 0))
        + float(row.get("其他(月/日元)", 0))
    )

    a_w = float(row.get("A每周次数", 1.0)) * WEEKS_PER_MONTH
    b_w = float(row.get("B每周次数", 0.5)) * WEEKS_PER_MONTH
    monthly_oneway_total = a_w + b_w

    one_way_minutes = float(row.get("加权单程通勤时间(分钟)", 0))
    one_way_fare = float(row.get("加权单程通勤费用(日元)", 0))

    # 往返：*2
    monthly_commute_minutes = one_way_minutes * monthly_oneway_total * 2
    monthly_commute_cost = one_way_fare * monthly_oneway_total * 2

    cash_total = fixed + monthly_commute_cost

    time_cost = None
    total_with_time = None
    if time_value_yph is not None:
        monthly_commute_hours = monthly_commute_minutes / 60.0
        time_cost = monthly_commute_hours * float(time_value_yph)
        total_with_time = cash_total + time_cost

    return fixed, monthly_commute_cost, cash_total, monthly_commute_minutes, time_cost, total_with_time


rows = []
for _, r in st.session_state.listings.iterrows():
    fixed, commute_cost, cash_total, commute_minutes, time_cost, total_with_time = row_total_cost(r, time_value)
    rows.append({
        "房源名称": r.get("房源名称", ""),
        "固定支出/月": fixed,
        "通勤费用/月": commute_cost,
        "现金总成本/月": cash_total,
        "通勤时间/月(小时)": commute_minutes / 60.0,
        "时间折算成本/月": time_cost,
        "综合成本/月(现金+时间)": total_with_time,
    })

df = pd.DataFrame(rows)

sort_col = "综合成本/月(现金+时间)" if time_value is not None else "现金总成本/月"
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


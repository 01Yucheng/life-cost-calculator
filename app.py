# app.py
# ============================================================
# 生活成本计算器（租金 + 通勤成本 + 通勤时间）
# ✅ 通勤：强制公共交通（transit），双目的地按频率加权
# ✅ 公交结果不再依赖 lat/lng（避免 TRANSIT ZERO_RESULTS）
# ✅ 两级重试：严格（rail/subway/train + fewer_transfers）→ 放宽（只要 transit）
# ✅ 固定查询时间：下一个工作日 09:30 JST（更稳）
# ✅ 始终提供 Google Maps 公交导航跳转
# ✅ 可选：Static Maps 路线图（像“截图”那样的效果）
# ============================================================

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


def enrich_jp_query(text: str) -> str:
    """
    提高站名/地址解析稳定性：补上“Tokyo, Japan / 日本 東京都”类信息。
    不改变 UI 展示，只用于请求。
    """
    s = (text or "").strip()
    if not s:
        return s
    # 给站名/短文本补充上下文（东京 & 日本）
    if ("日本" not in s) and ("Japan" not in s) and ("Tokyo" not in s) and ("東京都" not in s):
        s += " Tokyo Japan"
    return s


def next_weekday_0930_jst_ts() -> tuple[int, str]:
    """固定查询时间：下一个工作日 09:30 JST（更容易有公交线路返回）"""
    now = dt.datetime.now(tz=JST)
    d = now.date()
    while True:
        d = d + dt.timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            break
    t = dt.time(9, 30)
    when = dt.datetime.combine(d, t).replace(tzinfo=JST)
    return int(when.timestamp()), f"{d.isoformat()} {t.strftime('%H:%M')}（JST）"


def static_map_url(api_key: str, origin_text: str, dest_text: str, polyline: str) -> str:
    """
    用 Google Static Maps 画路线（类似“截图”效果）
    需要启用：Maps Static API（没启用也不影响主功能）
    """
    # 路线（polyline 已是 encoded string）
    path = quote_plus(f"enc:{polyline}")

    # 标记点（用文本也行，Static Maps 会自己 geocode）
    o = quote_plus(origin_text.strip())
    d = quote_plus(dest_text.strip())

    # size 可调；scale=2 更清晰
    return (
        "https://maps.googleapis.com/maps/api/staticmap"
        f"?size=1200x650&scale=2"
        f"&markers=label:O|{o}"
        f"&markers=label:D|{d}"
        f"&path=weight:6|{path}"
        f"&key={quote_plus(api_key)}"
    )


# =========================
# Directions API (TRANSIT by TEXT)
# =========================
@st.cache_data(ttl=60 * 60 * 24)
def directions_transit_text(
    origin_text: str,
    dest_text: str,
    ts: int,
    api_key: str,
    time_mode: str,          # "departure" or "arrival"
    strict: bool,            # True=加 transit_mode + fewer_transfers
) -> dict:
    """
    ✅ 关键修复：transit 查询用“文本 origin/destination”，而不是 lat,lng
    这样通常更接近 Google Maps UI 的结果。
    """
    url = "https://maps.googleapis.com/maps/api/directions/json"

    params = {
        "origin": origin_text,
        "destination": dest_text,
        "mode": "transit",
        "language": "ja",
        "region": "jp",
        "alternatives": "true",
        "key": api_key,
    }

    # ✅ 严格模式：尽量走轨道交通、少换乘（但可能过滤掉少数结果）
    if strict:
        params["transit_mode"] = "rail|subway|train"
        params["transit_routing_preference"] = "fewer_transfers"

    if time_mode == "arrival":
        params["arrival_time"] = ts
    else:
        params["departure_time"] = ts

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def parse_route(data: dict) -> tuple[int, float | None, str, str | None]:
    """
    Directions API 解析：
    - minutes
    - fare_jpy（可能 None）
    - summary
    - overview_polyline（给 Static Maps 用）
    """
    route = data["routes"][0]
    leg = route["legs"][0]
    minutes = round(leg["duration"]["value"] / 60)

    fare_jpy = None
    fare = route.get("fare")
    if isinstance(fare, dict) and fare.get("currency") == "JPY" and "value" in fare:
        fare_jpy = float(fare["value"])

    summary = route.get("summary", "") or ""
    poly = None
    op = route.get("overview_polyline")
    if isinstance(op, dict):
        poly = op.get("points")
    return minutes, fare_jpy, summary, poly


def transit_route_with_retry_text(
    origin_text: str,
    dest_text: str,
    ts: int,
    api_key: str,
) -> tuple[bool, dict, str]:
    """
    强制 transit，但尽可能拿到结果：
    1) strict + departure
    2) strict + arrival（只在 ZERO_RESULTS 时）
    3) relaxed + departure
    4) relaxed + arrival（只在 ZERO_RESULTS 时）
    """
    # 1) strict departure
    d1 = directions_transit_text(origin_text, dest_text, ts, api_key, time_mode="departure", strict=True)
    s1 = d1.get("status")
    if s1 == "OK":
        return True, d1, "strict_departure"

    # 2) strict arrival
    if s1 == "ZERO_RESULTS":
        d2 = directions_transit_text(origin_text, dest_text, ts, api_key, time_mode="arrival", strict=True)
        if d2.get("status") == "OK":
            return True, d2, "strict_arrival"

    # 3) relaxed departure（放宽过滤条件）
    d3 = directions_transit_text(origin_text, dest_text, ts, api_key, time_mode="departure", strict=False)
    s3 = d3.get("status")
    if s3 == "OK":
        return True, d3, "relaxed_departure"

    # 4) relaxed arrival
    if s3 == "ZERO_RESULTS":
        d4 = directions_transit_text(origin_text, dest_text, ts, api_key, time_mode="arrival", strict=False)
        if d4.get("status") == "OK":
            return True, d4, "relaxed_arrival"
        return False, d4, "relaxed_arrival"

    return False, d3, "relaxed_departure"


def weighted_merge(
    a_ok: bool, a_minutes: int | None, a_fare: float | None, a_w: float,
    b_ok: bool, b_minutes: int | None, b_fare: float | None, b_w: float,
) -> tuple[float, float | None]:
    """返回：加权平均单程 minutes、加权平均单程 fare（至少一条有fare才返回）"""
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

    show_map_image = st.toggle("显示路线图（Static Maps）", value=True)
    debug = st.toggle("显示调试信息", value=False)


# =========================
# Listing Table
# =========================
st.subheader("房源表格（可添加多行对比）")

if "listings" not in st.session_state:
    st.session_state.listings = pd.DataFrame(
        [dict(
            房源名称="例：浅草 1K",
            **{
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
            }
        )]
    )

st.session_state.listings = st.data_editor(
    st.session_state.listings,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)


# =========================
# Commute Section
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

col_r1, col_r2, col_r3 = st.columns([1, 1, 1])
with col_r1:
    target_row = st.number_input("写入到房源第几行（从1开始）", min_value=1, value=1, step=1)
with col_r2:
    st.caption("（公交查询时间）")
    st.write("固定：下一个工作日 09:30（JST）")
with col_r3:
    st.caption("（票价提示）")
    st.write("API 可能不返票价，可点 Google Maps 看")

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

        ts, human_when = next_weekday_0930_jst_ts()
        st.info(f"为保证公共交通有结果，已强制使用：{human_when} 进行查询（仅用于估算）。")

        # ✅ transit 用“文本”请求（最关键修复）
        o_q = enrich_jp_query(origin)
        a_q = enrich_jp_query(destA)
        b_q = enrich_jp_query(destB)

        okA, dataA, modeA = transit_route_with_retry_text(o_q, a_q, ts, api_key)
        okB, dataB, modeB = transit_route_with_retry_text(o_q, b_q, ts, api_key)

        # --- 展示 A ---
        a_minutes = a_fare = a_summary = None
        a_poly = None
        if okA:
            a_minutes, a_fare, a_summary, a_poly = parse_route(dataA)
            st.success(f"✅ A 单程公共交通：{a_minutes} 分钟（{modeA}）")
            if a_fare is not None:
                st.info(f"✅ A 单程票价：{money(a_fare)}")
            else:
                st.warning("A：API 未返回票价（常见），可点击 Google Maps 查看票价。")
            if a_summary:
                st.caption(f"A 路线摘要：{a_summary}")
            st.link_button("在 Google Maps 打开 A 公共交通导航", mapsA)

            if show_map_image and a_poly:
                try:
                    st.image(static_map_url(api_key, origin, destA, a_poly), caption="A：路线图（Static Maps）")
                except Exception:
                    st.warning("路线图生成失败（可能未启用 Static Maps API），不影响通勤计算。")
        else:
            st.error(f"A 公共交通查询失败：{dataA.get('status')}.")
            st.link_button("打开 Google Maps：A 公共交通导航", mapsA)
            if debug:
                st.subheader("Debug: A 返回原始数据")
                st.json(dataA)

        # --- 展示 B ---
        b_minutes = b_fare = b_summary = None
        b_poly = None
        if okB:
            b_minutes, b_fare, b_summary, b_poly = parse_route(dataB)
            st.success(f"✅ B 单程公共交通：{b_minutes} 分钟（{modeB}）")
            if b_fare is not None:
                st.info(f"✅ B 单程票价：{money(b_fare)}")
            else:
                st.warning("B：API 未返回票价（常见），可点击 Google Maps 查看票价。")
            if b_summary:
                st.caption(f"B 路线摘要：{b_summary}")
            st.link_button("在 Google Maps 打开 B 公共交通导航", mapsB)

            if show_map_image and b_poly:
                try:
                    st.image(static_map_url(api_key, origin, destB, b_poly), caption="B：路线图（Static Maps）")
                except Exception:
                    st.warning("路线图生成失败（可能未启用 Static Maps API），不影响通勤计算。")
        else:
            st.error(f"B 公共交通查询失败：{dataB.get('status')}.")
            st.link_button("打开 Google Maps：B 公共交通导航", mapsB)
            if debug:
                st.subheader("Debug: B 返回原始数据")
                st.json(dataB)

        if not (okA or okB):
            st.stop()

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

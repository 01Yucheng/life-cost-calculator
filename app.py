# app.py
# 生活成本网页小程序（Streamlit）
# 运行：streamlit run app.py

import pandas as pd
import streamlit as st

st.set_page_config(page_title="生活成本计算器", layout="wide")

st.title("生活成本计算器（租金 + 通勤成本 + 通勤时间）")

st.markdown(
    "建议把**通勤时间**填成「门到门」：走路 + 等车 + 换乘 + 进出站 + 电车时间，这样更真实。"
)

def money(v):
    return f"¥{v:,.0f}"

with st.sidebar:
    st.header("全局参数")
    commute_days = st.number_input("每月通勤天数（上课/实习）", min_value=0, max_value=31, value=20, step=1)
    trips_per_day = st.number_input("每天通勤次数（去+回通常2）", min_value=0, max_value=6, value=2, step=1)

    use_time_value = st.toggle("把通勤时间折算成成本（时间价值）", value=True)
    time_value = None
    if use_time_value:
        time_value = st.number_input("你的时间价值（日元/小时）", min_value=0, value=1500, step=100)

    st.divider()
    st.caption("提示：如果你用月票，可把单程费用填成：月票价格 /（通勤天数 * 2）")

st.subheader("输入房源信息")

# 初始化表格
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
    money_total = fixed + commute_cost

    commute_minutes = float(row["单程通勤时间(分钟)"]) * trips_per_day * commute_days
    commute_hours = commute_minutes / 60.0

    time_cost = None
    total_with_time = None
    if time_value is not None:
        time_cost = commute_hours * float(time_value)
        total_with_time = money_total + time_cost

    return fixed, commute_cost, money_total, commute_hours, time_cost, total_with_time

if len(edited) == 0:
    st.info("请先在上面表格里添加至少一个房源。")
    st.stop()

results = []
for _, row in edited.iterrows():
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

st.subheader("结果对比")

# 排序
if time_value is None:
    sort_col = "现金总成本/月"
    df_sorted = df.sort_values(by=sort_col, ascending=True)
else:
    sort_col = "综合成本/月(现金+时间)"
    df_sorted = df.sort_values(by=sort_col, ascending=True)

# 格式化展示
df_show = df_sorted.copy()
for col in ["固定支出/月", "通勤费用/月", "现金总成本/月", "时间折算成本/月", "综合成本/月(现金+时间)"]:
    if col in df_show.columns:
        df_show[col] = df_show[col].apply(lambda x: "" if pd.isna(x) else money(float(x)))

df_show["通勤时间/月(小时)"] = df_show["通勤时间/月(小时)"].apply(lambda x: f"{float(x):.1f}")

st.caption(f"当前按「{sort_col}」从低到高排序。")
st.dataframe(df_show, use_container_width=True, hide_index=True)

# 小结：省10分钟单程值多少钱
if time_value is not None:
    hours_saved = (10 * trips_per_day * commute_days) / 60.0
    value = hours_saved * float(time_value)
    st.info(
        f"小结：如果单程通勤少 10 分钟，你每月大约省 {hours_saved:.1f} 小时，"
        f"按你的时间价值约等于 {money(value)}。"
    )

st.divider()
st.subheader("导出")
csv = df_sorted.to_csv(index=False).encode("utf-8-sig")
st.download_button("下载 CSV 结果", data=csv, file_name="生活成本对比.csv", mime="text/csv")

st.caption("隐私提示：这个小程序默认在你自己电脑本地运行，不会把数据上传到任何服务器。")

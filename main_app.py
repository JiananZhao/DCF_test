import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 核心逻辑函数更新 ---
@st.cache_data(ttl=3600)
def get_valuation_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    
    # 获取财务数据
    income_stmt = ticker.financials
    cash_flow = ticker.cashflow
    
    # 提取基础指标
    rev = income_stmt.loc["Total Revenue"].iloc[:3]
    if "Free Cash Flow" in cash_flow.index:
        fcf = cash_flow.loc["Free Cash Flow"].iloc[:3]
    else:
        fcf = (cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]).iloc[:3]
    
    metrics = pd.DataFrame({"Revenue": rev, "FCF": fcf})
    metrics["Margin (%)"] = (metrics["FCF"] / metrics["Revenue"]) * 100
    
    # 获取股价和股本 (用于每股估值)
    current_price = info.get("currentPrice")
    shares_outstanding = info.get("sharesOutstanding")
    
    return metrics.sort_index(), fcf.iloc[0], current_price, shares_outstanding

def calculate_dcf(fcf_m, g, r, tg):
    """通用的 DCF 计算逻辑"""
    pvs = [ (fcf_m * (1 + g)**t) / (1 + r)**t for t in range(1, 6) ]
    tv = (fcf_m * (1 + g)**5 * (1 + tg)) / (r - tg)
    pv_tv = tv / (1 + r)**5
    return sum(pvs) + pv_tv

# --- 2. Streamlit UI 布局 ---
st.set_page_config(page_title="Workbench", layout="wide")
st.title("DCF")

with st.sidebar:
    st.header("Main Parameters")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    g_base = st.slider("中性预期增长率 (g)", 0.0, 0.60, 0.25)
    r_rate = st.slider("折现率 (WACC)", 0.05, 0.20, 0.1)
    terminal_g = st.slider("永续增长率", 0.0, 0.05, 0.03)

try:
    history_df, latest_fcf, cur_price, shares = get_valuation_data(target_ticker)
    fcf_m = latest_fcf / 1e6
    shares_m = shares / 1e6

    # --- 3. 情景分析计算 ---
    scenarios = {
        "悲观 (Pessimistic)": g_base - 0.05,
        "中性 (Neutral)": g_base,
        "乐观 (Optimistic)": g_base + 0.05
    }
    
    results = []
    for name, g in scenarios.items():
        ev = calculate_dcf(fcf_m, g, r_rate, terminal_g)
        fair_value = ev / shares_m
        upside = (fair_value / cur_price - 1) * 100
        results.append({
            "情景": name,
            "预期增长率": f"{g*100:.1f}%",
            "内在价值 (每股)": f"${fair_value:.2f}",
            "潜在涨幅": f"{upside:.1f}%"
        })

    # --- 4. 核心指标展示 ---
    col1, col2, col3 = st.columns(3)
    col1.metric("当前市价", f"${cur_price:.2f}")
    col2.metric("最新 FCF (M)", f"${fcf_m:.2f}")
    col3.metric("总股本 (M)", f"{shares_m:.2f}")

    st.divider()

    # --- 5. 展示情景对比表 ---
    st.subheader("Comparison")
    res_df = pd.DataFrame(results)
    
    # 使用 st.dataframe 配合颜色高亮
    def highlight_upside(val):
        color = 'red' if '-' in val else 'green'
        return f'color: {color}'
    
    st.table(res_df)

    # --- 6. 瀑布图 (基于中性预期) ---
    st.subheader(f"Valuation ({g_base*100:.0f}% 增长)")
    pvs = [ (fcf_m * (1 + g_base)**t) / (1 + r_rate)**t for t in range(1, 6) ]
    pv_tv = (calculate_dcf(fcf_m, g_base, r_rate, terminal_g) - sum(pvs))
    
    fig = go.Figure(go.Waterfall(
        orientation = "v",
        measure = ["relative"] * 6 + ["total"],
        x = ["Year 1 PV", "Year 2 PV", "Year 3 PV", "Year 4 PV", "Year 5 PV", "Terminal Value PV", "Intrinsic EV"],
        y = pvs + [pv_tv, 0],
        totals = {"marker":{"color":"#2ca02c"}}
    ))
    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"数据处理异常: {e}")

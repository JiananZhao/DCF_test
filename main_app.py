import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 核心逻辑函数更新 ---
@st.cache_data(ttl=3600)
def get_full_financial_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    
    # 基础估值所需数据
    income_stmt = ticker.financials
    cash_flow = ticker.cashflow
    
    # 季度详细财务报表 (用于表格展示)
    q_income = ticker.quarterly_financials
    q_balance = ticker.quarterly_balance_sheet
    q_cash = ticker.quarterly_cashflow
    
    # 提取基础指标 (取最近一年)
    rev = income_stmt.loc["Total Revenue"].iloc[:3]
    if "Free Cash Flow" in cash_flow.index:
        fcf = cash_flow.loc["Free Cash Flow"].iloc[:3]
    else:
        fcf = (cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]).iloc[:3]
    
    metrics = pd.DataFrame({"Revenue": rev, "FCF": fcf})
    metrics["Margin (%)"] = (metrics["FCF"] / metrics["Revenue"]) * 100
    
    current_price = info.get("currentPrice")
    shares_outstanding = info.get("sharesOutstanding")
    
    return {
        "metrics": metrics.sort_index(),
        "latest_fcf": fcf.iloc[0],
        "current_price": current_price,
        "shares": shares_outstanding,
        "q_income": q_income,
        "q_balance": q_balance,
        "q_cash": q_cash
    }

def calculate_dcf(fcf_m, g, r, tg):
    pvs = [ (fcf_m * (1 + g)**t) / (1 + r)**t for t in range(1, 6) ]
    tv = (fcf_m * (1 + g)**5 * (1 + tg)) / (r - tg)
    pv_tv = tv / (1 + r)**5
    return sum(pvs) + pv_tv

# --- 2. Streamlit UI 布局 ---
st.set_page_config(page_title="精准量化估值工作台", layout="wide")
st.title("⚖️ 专业级 DCF 估值与财务审计看板")

# 侧边栏：改用数值输入框以提升精度
with st.sidebar:
    st.header("精准参数输入")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    
    # 使用 number_input，设置 step 为 0.001 (0.1%)
    g_base = st.number_input("中性预期增长率 (g)", value=0.250, min_value=0.0, max_value=1.0, step=0.005, format="%.3f")
    r_rate = st.number_input("折现率 (WACC)", value=0.100, min_value=0.01, max_value=0.30, step=0.005, format="%.3f")
    terminal_g = st.number_input("永续增长率 (tg)", value=0.030, min_value=0.0, max_value=0.10, step=0.001, format="%.3f")
    
    st.caption("注：0.010 代表 1.0%")

try:
    data = get_full_financial_data(target_ticker)
    fcf_m = data["latest_fcf"] / 1e6
    shares_m = data["shares"] / 1e6
    cur_price = data["current_price"]

    # --- 3. 情景分析与指标展示 ---
    scenarios = {"悲观": g_base - 0.05, "中性": g_base, "乐观": g_base + 0.05}
    results = []
    for name, g in scenarios.items():
        ev = calculate_dcf(fcf_m, g, r_rate, terminal_g)
        fair_v = ev / shares_m
        results.append({"情景": name, "增长率": f"{g*100:.1f}%", "内在价值": f"${fair_v:.2f}", "潜力": f"{(fair_v/cur_price-1)*100:.1f}%"})

    c1, c2, c3 = st.columns(3)
    c1.metric("当前市价", f"${cur_price:.2f}")
    c2.metric("中性预估价值", f"{results[1]['内在价值']}")
    c3.metric("FCF 利润率 (均值)", f"{data['metrics']['Margin (%)'].mean():.2f}%")

    st.table(pd.DataFrame(results))

    # --- 4. 财务审计中心 (季度数据表格) ---
    st.divider()
    st.subheader("📋 季度财务审计中心")
    
    tab1, tab2, tab3 = st.tabs(["利润表 (Quarterly)", "资产负债表 (Quarterly)", "现金流量表 (Quarterly)"])
    
    with tab1:
        st.dataframe(data["q_income"], use_container_width=True)
    with tab2:
        st.dataframe(data["q_balance"], use_container_width=True)
    with tab3:
        st.dataframe(data["q_cash"], use_container_width=True)

    # --- 5. 瀑布图构成 ---
    st.subheader("🎯 估值构成分析")
    pvs = [ (fcf_m * (1 + g_base)**t) / (1 + r_rate)**t for t in range(1, 6) ]
    pv_tv = (calculate_dcf(fcf_m, g_base, r_rate, terminal_g) - sum(pvs))
    
    fig = go.Figure(go.Waterfall(
        orientation = "v",
        x = ["Y1 PV", "Y2 PV", "Y3 PV", "Y4 PV", "Y5 PV", "TV PV", "Total EV"],
        y = pvs + [pv_tv, 0],
        measure = ["relative"]*6 + ["total"]
    ))
    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"分析出错：{e}")

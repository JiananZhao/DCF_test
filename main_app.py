import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- 1. 核心数据抓取 ---
@st.cache_data(ttl=3600)
def get_full_financial_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    
    # 获取年度报表 (用于计算 SBC 和 FCF)
    cash_flow = ticker.cashflow
    
    # 提取 SBC (Stock Based Compensation)
    sbc_series = cash_flow.loc["Stock Based Compensation"] if "Stock Based Compensation" in cash_flow.index else pd.Series(0, index=cash_flow.columns)
    
    # 提取 FCF
    if "Free Cash Flow" in cash_flow.index:
        fcf_raw_series = cash_flow.loc["Free Cash Flow"]
    else:
        fcf_raw_series = cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]
    
    # 自动计算历史股本 CAGR (Net Dilution/Buyback)
    shares_history = ticker.get_shares_full(start="2021-01-01")
    if not shares_history.empty:
        shares_latest = shares_history.iloc[-1]
        shares_start = shares_history.iloc[0]
        years = (shares_history.index[-1] - shares_history.index[0]).days / 365.25
        hist_dilution_rate = (shares_latest / shares_start) ** (1/years) - 1 if years > 0 else 0
    else:
        hist_dilution_rate = 0.0

    return {
        "fcf_raw": fcf_raw_series.iloc[0],
        "sbc": sbc_series.iloc[0],
        "current_price": info.get("currentPrice"),
        "shares": info.get("sharesOutstanding"),
        "net_debt": (info.get("totalDebt", 0) - info.get("totalCash", 0)),
        "hist_dilution_rate": float(hist_dilution_rate),
        "q_income": ticker.quarterly_financials,
        "q_balance": ticker.quarterly_balance_sheet,
        "q_cash": ticker.quarterly_cashflow
    }

def calculate_dcf(fcf_m, g, r, tg, net_debt_m, shares_m, dilution_rate):
    # 1. 计算未来 5 年 PV
    pvs = [ (fcf_m * (1 + g)**t) / (1 + r)**t for t in range(1, 6) ]
    # 2. 计算永续价值 (Terminal Value) PV
    tv = (fcf_m * (1 + g)**5 * (1 + tg)) / (r - tg)
    pv_tv = tv / (1 + r)**5
    # 3. 计算股权价值 (Equity Value)
    equity_value = (sum(pvs) + pv_tv) - net_debt_m
    # 4. 预测 5 年后的摊薄/回购后股本
    projected_shares = shares_m * ((1 + dilution_rate) ** 5)
    
    return equity_value / projected_shares

# --- 2. Streamlit UI 布局 ---
st.set_page_config(page_title="精准量化估值看板", layout="wide")
st.title("⚖️ 终极 DCF 估值模型：SBC、净债务与动态股本")

# 侧边栏：精准参数控制
with st.sidebar:
    st.header("1. 基础配置")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    
    st.divider()
    st.header("2. 核心假设")
    deduct_sbc = st.checkbox("扣除 SBC 影响", value=True)
    g_base = st.number_input("预期增长率 (g)", value=0.250, step=0.005, format="%.3f")
    r_rate = st.number_input("折现率 (WACC)", value=0.100, step=0.005, format="%.3f")
    terminal_g = st.number_input("永续增长率 (tg)", value=0.030, step=0.001, format="%.3f")
    
    st.divider()
    st.header("3. 股本变动预测")
    # 稍后在 try 块中根据抓取到的数据动态更新

try:
    data = get_full_financial_data(target_ticker)
    
    # 动态渲染股本变动输入框
    with st.sidebar:
        net_rate = st.number_input(
            "预期年化股本变动率", 
            value=data["hist_dilution_rate"], 
            step=0.001, 
            format="%.3f",
            help="正数代表增发/稀释，负数代表回购。"
        )

    # 单位换算
    raw_fcf_m = data["fcf_raw"] / 1e6
    sbc_m = data["sbc"] / 1e6
    shares_m = data["shares"] / 1e6
    net_debt_m = data["net_debt"] / 1e6
    cur_price = data["current_price"]

    # 现金流口径处理
    fcf_calc = (raw_fcf_m - sbc_m) if deduct_sbc else raw_fcf_m

    # --- 3. 核心指标卡 ---
    st.subheader("📌 核心锚点指标")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("当前市价", f"${cur_price:.2f}")
    c2.metric("历史变动率 (CAGR)", f"{data['hist_dilution_rate']*100:.2f}%")
    c3.metric("净债务 (M)", f"${net_debt_m:.1f}M", delta="净负债" if net_debt_m > 0 else "净现金", delta_color="inverse")
    c4.metric("计算用 FCF (M)", f"${fcf_calc:.1f}M", border=True)

    # --- 4. 情景分析 ---
    st.divider()
    st.subheader(f"📊 {target_ticker} 股权价值情景推演 (考虑 5 年股本趋势)")
    
    scenarios = {"悲观 (g-5%)": g_base - 0.05, "中性": g_base, "乐观 (g+5%)": g_base + 0.05}
    comparison_results = []
    
    for name, g in scenarios.items():
        fair_v = calculate_dcf(fcf_calc, g, r_rate, terminal_g, net_debt_m, shares_m, net_rate)
        comparison_results.append({
            "评估情景": name,
            "增长率假设": f"{g*100:.1f}%",
            "内在价值 (每股)": f"${fair_v:.2f}",
            "潜在涨幅/安全边际": f"{(fair_v/cur_price-1)*100:.1f}%"
        })
    st.table(pd.DataFrame(comparison_results))

    # --- 5. 报表展示 (已接回) ---
    st.divider()
    with st.expander("🔍 原始财务审计报表 (季度数据)"):
        t1, t2, t3 = st.tabs(["利润表", "资产负债表", "现金流量表"])
        t1.dataframe(data["q_income"], use_container_width=True)
        t2.dataframe(data["q_balance"], use_container_width=True)
        t3.dataframe(data["q_cash"], use_container_width=True)

except Exception as e:
    st.error(f"模型运行出错：{e}")

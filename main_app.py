import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- 1. 核心数据抓取：增加历史股本分析 ---
@st.cache_data(ttl=3600)
def get_full_financial_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    
    # 获取财务报表
    cash_flow = ticker.cashflow
    
    # 1. 提取 SBC 和原始 FCF
    sbc_series = cash_flow.loc["Stock Based Compensation"] if "Stock Based Compensation" in cash_flow.index else pd.Series(0, index=cash_flow.columns)
    if "Free Cash Flow" in cash_flow.index:
        fcf_raw_series = cash_flow.loc["Free Cash Flow"]
    else:
        fcf_raw_series = cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]
    
    # 2. 自动计算历史股本变动率 (Net Dilution/Buyback Rate)
    # 获取年度股本序列
    shares_history = ticker.get_shares_full(start="2021-01-01")
    if not shares_history.empty:
        # 取每年末的近似值计算 CAGR
        shares_latest = shares_history.iloc[-1]
        shares_start = shares_history.iloc[0]
        years = (shares_history.index[-1] - shares_history.index[0]).days / 365.25
        # 计算年化变动率 (CAGR)
        hist_dilution_rate = (shares_latest / shares_start) ** (1/years) - 1 if years > 0 else 0
    else:
        hist_dilution_rate = 0.0

    return {
        "fcf_raw": fcf_raw_series.iloc[0],
        "sbc": sbc_series.iloc[0],
        "current_price": info.get("currentPrice"),
        "shares": info.get("sharesOutstanding"),
        "net_debt": (info.get("totalDebt", 0) - info.get("totalCash", 0)),
        "hist_dilution_rate": hist_dilution_rate,
        "q_income": ticker.quarterly_financials,
        "q_balance": ticker.quarterly_balance_sheet,
        "q_cash": ticker.quarterly_cashflow
    }

def calculate_dcf(fcf_m, g, r, tg, net_debt_m, shares_m, dilution_rate):
    # 计算未来 5 年 PV
    pvs = [ (fcf_m * (1 + g)**t) / (1 + r)**t for t in range(1, 6) ]
    # 永续价值 PV
    tv = (fcf_m * (1 + g)**5 * (1 + tg)) / (r - tg)
    pv_tv = tv / (1 + r)**5
    equity_value = (sum(pvs) + pv_tv) - net_debt_m
    
    # 核心：预测 5 年后的股本总数
    # 如果 dilution_rate 为正，代表股本膨胀；为负，代表回购缩减
    projected_shares = shares_m * ((1 + dilution_rate) ** 5)
    
    return equity_value / projected_shares

# --- 2. Streamlit UI ---
st.set_page_config(page_title="全要素量化估值看板", layout="wide")
st.title("⚖️ 动态股本 DCF 估值模型")

with st.sidebar:
    st.header("1. 基础配置")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    
    st.divider()
    st.header("2. 核心假设")
    deduct_sbc = st.checkbox("扣除 SBC 影响", value=True)
    g_base = st.number_input("中性增速 (g)", value=0.250, step=0.005, format="%.3f")
    r_rate = st.number_input("折现率 (WACC)", value=0.100, step=0.005, format="%.3f")
    terminal_g = st.number_input("永续增速 (tg)", value=0.030, step=0.001, format="%.3f")
    
    st.divider()
    st.header("3. 股本变动 (自动计算)")
    # 这里的默认值将通过数据抓取后填充
    dilution_input = st.empty() # 占位符

try:
    data = get_full_financial_data(target_ticker)
    
    # 渲染股本变动输入框，默认使用抓取的历史值
    with st.sidebar:
        net_rate = st.number_input(
            "预期年化股本变动率", 
            value=float(data["hist_dilution_rate"]), 
            step=0.001, 
            format="%.3f",
            help="正数代表增发(稀释)，负数代表回购。已根据历史数据自动填入。"
        )

    # 单位换算
    raw_fcf_m = data["fcf_raw"] / 1e6
    sbc_m = data["sbc"] / 1e6
    shares_m = data["shares"] / 1e6
    net_debt_m = data["net_debt"] / 1e6
    cur_price = data["current_price"]

    # --- 3. 核心指标卡 ---
    st.subheader("📌 估值锚点")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("当前市价", f"${cur_price:.2f}")
    col2.metric("历史变动率", f"{data['hist_dilution_rate']*100:.2f}%", help="过去几年的年化股本增减率")
    col3.metric("净债务 (M)", f"${net_debt_m:.1f}M")
    
    fcf_calc = (raw_fcf_m - sbc_m) if deduct_sbc else raw_fcf_m
    col4.metric("计算用 FCF (M)", f"${fcf_calc:.1f}M")

    # --- 4. 情景分析 ---
    st.divider()
    st.subheader(f"📊 {target_ticker} 股权价值推演 (考虑 5 年后股本变动)")
    
    scenarios = {"悲观 (g-5%)": g_base - 0.05, "中性": g_base, "乐观 (g+5%)": g_base + 0.05}
    results = []
    for name, g in scenarios.items():
        fair_v = calculate_dcf(fcf_calc, g, r_rate, terminal_g, net_debt_m, shares_m, net_rate)
        results.append({
            "情景": name,
            "预期增速": f"{g*100:.1f}%",
            "内在价值": f"${fair_v:.2f}",
            "潜在涨幅": f"{(fair_v/cur_price-1)*100:.1f}%"
        })
    st.table(pd.DataFrame(results))

    # --- 5. 瀑布图：直观展示估值构成 ---
    pvs = [ (fcf_calc * (1 + g_base)**t) / (1 + r_rate)**t for t in range(1, 6) ]
    total_ev = sum(pvs) + ((fcf_calc * (1 + g_base)**5 * (1 + terminal_g)) / (r_rate - terminal_g) / (1 + r_rate)**5)
    
    fig = go.Figure(go.Waterfall(
        orientation = "v",
        x = ["Y1-Y5 PV", "终端价值 PV", "扣除净债务", "最终股权价值"],
        y = [sum(pvs), total_ev - sum(pvs), -net_debt_m, 0],
        measure = ["relative", "relative", "relative", "total"],
        totals = {"marker":{"color":"#2ca02c"}}
    ))
    fig.update_layout(title="估值从企业价值(EV)到股权价值的路径")
    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"分析出错：{e}")

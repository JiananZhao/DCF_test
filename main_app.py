import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 核心逻辑函数 ---
def get_valuation_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    # 获取财务数据（加入缓存避免频繁请求）
    income_stmt = ticker.financials
    cash_flow = ticker.cashflow
    
    rev = income_stmt.loc["Total Revenue"].iloc[:3]
    if "Free Cash Flow" in cash_flow.index:
        fcf = cash_flow.loc["Free Cash Flow"].iloc[:3]
    else:
        fcf = (cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]).iloc[:3]
    
    metrics = pd.DataFrame({"Revenue": rev, "FCF": fcf})
    metrics["Margin (%)"] = (metrics["FCF"] / metrics["Revenue"]) * 100
    return metrics.sort_index(), fcf.iloc[0]

# --- 2. Streamlit UI 布局 ---
st.set_page_config(page_title="TEAM/TTD 估值工作台", layout="wide")
st.title("🚀 量化分析利器：交互式 DCF 估值看板")

# 侧边栏参数调节
with st.sidebar:
    st.header("模型参数设置")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    g_rate = st.slider("前 5 年增长率 (g)", 0.0, 0.50, 0.25)
    r_rate = st.slider("折现率 (WACC/r)", 0.05, 0.20, 0.10)
    terminal_g = st.slider("永续增长率", 0.0, 0.05, 0.03)

# 获取数据
try:
    history_df, latest_fcf = get_valuation_data(target_ticker)
    
    # 计算 DCF
    fcf_m = latest_fcf / 1e6
    pvs = [ (fcf_m * (1 + g_rate)**t) / (1 + r_rate)**t for t in range(1, 6) ]
    tv = (fcf_m * (1 + g_rate)**5 * (1 + terminal_g)) / (r_rate - terminal_g)
    pv_tv = tv / (1 + r_rate)**5
    total_ev = sum(pvs) + pv_tv

    # --- 展示指标 ---
    col1, col2, col3 = st.columns(3)
    col1.metric("最新 FCF (M)", f"${fcf_m:.2f}")
    col2.metric("平均 FCF 利润率", f"{history_df['Margin (%)'].mean():.2f}%")
    col3.metric("估值企业价值 (M)", f"${total_ev:.2f}")

    # --- Plotly 瀑布图 ---
    fig = go.Figure(go.Waterfall(
        name = "DCF Components", orientation = "v",
        measure = ["relative"] * 6 + ["total"],
        x = ["Year 1 PV", "Year 2 PV", "Year 3 PV", "Year 4 PV", "Year 5 PV", "Terminal Value PV", "Intrinsic Value"],
        textposition = "outside",
        text = [f"${v:.1f}" for v in pvs] + [f"${pv_tv:.1f}", f"${total_ev:.1f}"],
        y = pvs + [pv_tv, 0], # 最后一个设为0因为是total
        connector = {"line":{"color":"rgb(63, 63, 63)"}},
        increasing = {"marker":{"color":"#1f77b4"}},
        totals = {"marker":{"color":"#2ca02c"}}
    ))

    fig.update_layout(title=f"{target_ticker} 估值构成瀑布图", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    # 展示历史利润率
    st.subheader("历史财务数据趋势")
    st.line_chart(history_df['Margin (%)'])

except Exception as e:
    st.error(f"无法加载数据，请检查代码或网络: {e}")

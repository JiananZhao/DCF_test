import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# --- 1. 数据抓取增强 ---
@st.cache_data(ttl=3600)
def get_full_financial_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    
    # 获取财务报表
    income_stmt = ticker.financials
    cash_flow = ticker.cashflow
    q_income = ticker.quarterly_financials
    q_balance = ticker.quarterly_balance_sheet
    q_cash = ticker.quarterly_cashflow
    
    # 计算季度收入增长 (YoY)
    # yfinance 的季度数据通常按时间倒序排列，我们需要计算 (T / T-4) - 1
    rev_q = q_income.loc["Total Revenue"].sort_index()
    rev_growth_yoy = rev_q.pct_change(periods=4) * 100 
    
    growth_df = pd.DataFrame({
        "Revenue (M)": rev_q / 1e6,
        "YoY Growth (%)": rev_growth_yoy
    }).dropna()

    # 基础估值指标
    if "Free Cash Flow" in cash_flow.index:
        fcf = cash_flow.loc["Free Cash Flow"].iloc[:3]
    else:
        fcf = (cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]).iloc[:3]
    
    return {
        "latest_fcf": fcf.iloc[0],
        "current_price": info.get("currentPrice"),
        "shares": info.get("sharesOutstanding"),
        "q_income": q_income,
        "q_balance": q_balance,
        "q_cash": q_cash,
        "growth_trend": growth_df,
        "margin": (fcf.iloc[0] / income_stmt.loc["Total Revenue"].iloc[0]) * 100
    }

# --- 2. 页面布局 ---
st.set_page_config(page_title="精准量化看板", layout="wide")
st.title("📈 财务趋势与 DCF 深度分析")

with st.sidebar:
    st.header("精准参数输入")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    g_base = st.number_input("中性预期增长率 (g)", value=0.250, step=0.005, format="%.3f")
    r_rate = st.number_input("折现率 (WACC)", value=0.100, step=0.005, format="%.3f")
    terminal_g = st.number_input("永续增长率 (tg)", value=0.030, step=0.001, format="%.3f")

try:
    data = get_full_financial_data(target_ticker)
    
    # --- 3. 新增：季度收入增长曲线 ---
    st.subheader("🚀 收入增长动能分析")
    
    fig_growth = go.Figure()
    # 柱状图展示收入绝对值
    fig_growth.add_trace(go.Bar(
        x=data["growth_trend"].index,
        y=data["growth_trend"]["Revenue (M)"],
        name="Revenue (M)",
        marker_color='rgba(31, 119, 180, 0.6)',
        yaxis="y"
    ))
    # 折线图展示同比增长率
    fig_growth.add_trace(go.Scatter(
        x=data["growth_trend"].index,
        y=data["growth_trend"]["YoY Growth (%)"],
        name="YoY Growth (%)",
        line=dict(color='#ff7f0e', width=3),
        yaxis="y2"
    ))

    fig_growth.update_layout(
        hovermode="x unified",
        yaxis=dict(title="Revenue (Millions)"),
        yaxis2=dict(title="YoY Growth (%)", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_growth, use_container_width=True)

    # --- 4. 估值核心指标展示 ---
    st.divider()
    res_val = (data["latest_fcf"] / 1e6 * (1+g_base)) / (r_rate - terminal_g) # 简化展示用
    
    c1, c2, c3 = st.columns(3)
    c1.metric("当前市价", f"${data['current_price']:.2f}")
    c2.metric("最新 FCF 利润率", f"{data['margin']:.2f}%")
    c3.metric("季度平均增速", f"{data['growth_trend']['YoY Growth (%)'].mean():.1f}%")

    # --- 5. 财务审计中心 (Tabs) ---
    st.subheader("📋 季度原始报表审计")
    tab1, tab2, tab3 = st.tabs(["利润表", "资产负债表", "现金流量表"])
    with tab1: st.dataframe(data["q_income"])
    with tab2: st.dataframe(data["q_balance"])
    with tab3: st.dataframe(data["q_cash"])

except Exception as e:
    st.error(f"分析出错：{e}")

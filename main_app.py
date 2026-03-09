import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 核心逻辑函数更新 ---
@st.cache_data(ttl=3600)
def get_full_financial_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    
    # 财务报表
    income_stmt = ticker.financials
    cash_flow = ticker.cashflow
    q_income = ticker.quarterly_financials
    q_balance = ticker.quarterly_balance_sheet
    q_cash = ticker.quarterly_cashflow
    
    # 提取基础指标
    if "Free Cash Flow" in cash_flow.index:
        fcf = cash_flow.loc["Free Cash Flow"].iloc[:3]
    else:
        fcf = (cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]).iloc[:3]
    
    # 提取净债务相关数据 (从 info 获取最新数据)
    total_cash = info.get("totalCash", 0)
    total_debt = info.get("totalDebt", 0)
    net_debt = total_debt - total_cash
    
    current_price = info.get("currentPrice")
    shares_outstanding = info.get("sharesOutstanding")
    
    return {
        "latest_fcf": fcf.iloc[0],
        "current_price": current_price,
        "shares": shares_outstanding,
        "net_debt": net_debt,
        "total_cash": total_cash,
        "total_debt": total_debt,
        "q_income": q_income,
        "q_balance": q_balance,
        "q_cash": q_cash,
        "fcf_history": fcf
    }

def calculate_intrinsic_value(fcf_m, g, r, tg, net_debt_m, shares_m):
    # 计算企业价值 (EV)
    pvs = [ (fcf_m * (1 + g)**t) / (1 + r)**t for t in range(1, 6) ]
    tv = (fcf_m * (1 + g)**5 * (1 + tg)) / (r - tg)
    pv_tv = tv / (1 + r)**5
    ev = sum(pvs) + pv_tv
    
    # EV -> Equity Value
    equity_value = ev - net_debt_m
    return equity_value / shares_m, ev, pv_tv

# --- 2. Streamlit UI 布局 ---
st.set_page_config(page_title="精准量化估值工作台", layout="wide")
st.title("⚖️ 专业级 DCF 估值看板 (含净债务调整)")

with st.sidebar:
    st.header("精准参数输入")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    g_base = st.number_input("中性预期增长率 (g)", value=0.250, step=0.005, format="%.3f")
    r_rate = st.number_input("折现率 (WACC)", value=0.100, step=0.005, format="%.3f")
    terminal_g = st.number_input("永续增长率 (tg)", value=0.030, step=0.001, format="%.3f")

try:
    data = get_full_financial_data(target_ticker)
    fcf_m = data["latest_fcf"] / 1e6
    shares_m = data["shares"] / 1e6
    net_debt_m = data["net_debt"] / 1e6
    cur_price = data["current_price"]

    # --- 3. 核心指标展示 ---
    st.subheader("🏦 资产负债表核心项 (Millions)")
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("现金储备", f"${data['total_cash']/1e6:.1f}M")
    m_col2.metric("总债务", f"${data['total_debt']/1e6:.1f}M")
    m_col3.metric("净债务 (Net Debt)", f"${net_debt_m:.1f}M", delta=f"债务缺口" if net_debt_m > 0 else "净现金", delta_color="inverse")
    m_col4.metric("当前市价", f"${cur_price:.2f}")

    # --- 4. 情景分析 ---
    scenarios = {"悲观": g_base - 0.05, "中性": g_base, "乐观": g_base + 0.05}
    results = []
    for name, g in scenarios.items():
        fair_v, _, _ = calculate_intrinsic_value(fcf_m, g, r_rate, terminal_g, net_debt_m, shares_m)
        results.append({"情景": name, "增长率": f"{g*100:.1f}%", "内在价值": f"${fair_v:.2f}", "涨跌幅": f"{(fair_v/cur_price-1)*100:.1f}%"})

    st.divider()
    st.subheader("📊 股权价值情景分析")
    st.table(pd.DataFrame(results))

    # --- 5. 财务审计中心 ---
    st.subheader("📋 季度财务审计中心")
    tab1, tab2, tab3 = st.tabs(["利润表", "资产负债表", "现金流量表"])
    with tab1: st.dataframe(data["q_income"])
    with tab2: st.dataframe(data["q_balance"])
    with tab3: st.dataframe(data["q_cash"])

except Exception as e:
    st.error(f"分析出错：{e}")

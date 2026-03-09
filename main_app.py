import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 核心逻辑函数：增加 SBC 提取 ---
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
    
    # --- SBC 处理逻辑 ---
    # 尝试从现金流量表中提取 Stock Based Compensation
    if "Stock Based Compensation" in cash_flow.index:
        sbc_series = cash_flow.loc["Stock Based Compensation"]
    else:
        # 如果 yfinance 字段名不一致，尝试匹配
        sbc_series = pd.Series(0, index=cash_flow.columns)
    
    # --- FCF 计算与调整 ---
    if "Free Cash Flow" in cash_flow.index:
        fcf_raw = cash_flow.loc["Free Cash Flow"]
    else:
        ocf = cash_flow.loc["Operating Cash Flow"]
        capex = cash_flow.loc["Capital Expenditures"]
        fcf_raw = ocf + capex 
    
    # 核心：计算 Adjusted FCF (去水分现金流)
    adj_fcf_series = fcf_raw - sbc_series
    
    # 提取最新数据
    latest_adj_fcf = adj_fcf_series.iloc[0]
    latest_sbc = sbc_series.iloc[0]
    
    # 资产负债表项
    total_cash = info.get("totalCash", 0)
    total_debt = info.get("totalDebt", 0)
    net_debt = total_debt - total_cash
    
    current_price = info.get("currentPrice")
    shares_outstanding = info.get("sharesOutstanding")
    
    return {
        "latest_adj_fcf": latest_adj_fcf,
        "latest_sbc": latest_sbc,
        "fcf_raw": fcf_raw.iloc[0],
        "current_price": current_price,
        "shares": shares_outstanding,
        "net_debt": net_debt,
        "total_cash": total_cash,
        "total_debt": total_debt,
        "q_income": q_income,
        "q_balance": q_balance,
        "q_cash": q_cash
    }

def calculate_intrinsic_value(adj_fcf_m, g, r, tg, net_debt_m, shares_m):
    pvs = [ (adj_fcf_m * (1 + g)**t) / (1 + r)**t for t in range(1, 6) ]
    tv = (adj_fcf_m * (1 + g)**5 * (1 + tg)) / (r - tg)
    pv_tv = tv / (1 + r)**5
    ev = sum(pvs) + pv_tv
    equity_value = ev - net_debt_m
    return equity_value / shares_m, ev, pv_tv

# --- 2. Streamlit UI 布局 ---
st.set_page_config(page_title="SBC 调整后精准估值", layout="wide")
st.title("⚖️ 精准估值：SBC 调整后 DCF 模型")

with st.sidebar:
    st.header("模型核心参数")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    g_base = st.number_input("中性预期增长率 (g)", value=0.250, step=0.005, format="%.3f")
    r_rate = st.number_input("折现率 (WACC)", value=0.100, step=0.005, format="%.3f")
    terminal_g = st.number_input("永续增长率 (tg)", value=0.030, step=0.001, format="%.3f")

try:
    data = get_full_financial_data(target_ticker)
    
    adj_fcf_m = data["latest_adj_fcf"] / 1e6
    sbc_m = data["latest_sbc"] / 1e6
    raw_fcf_m = data["fcf_raw"] / 1e6
    shares_m = data["shares"] / 1e6
    net_debt_m = data["net_debt"] / 1e6
    cur_price = data["current_price"]

    # --- 3. 现金流质量审计面板 ---
    st.subheader("🔍 现金流质量审计 (Cash Flow Quality)")
    q1, q2, q3 = st.columns(3)
    q1.metric("原始 FCF (M)", f"${raw_fcf_m:.1f}M")
    q2.metric("SBC 支出 (M)", f"- ${sbc_m:.1f}M")
    sbc_ratio = (sbc_m / raw_fcf_m * 100) if raw_fcf_m != 0 else 0
    q3.metric("调整后 FCF (M)", f"${adj_fcf_m:.1f}M", delta=f"SBC 占比 {sbc_ratio:.1f}%", delta_color="inverse")

    # --- 4. 情景分析 (基于调整后的 FCF) ---
    st.divider()
    st.subheader(f"📊 {target_ticker} 股权价值情景分析 (已扣除 SBC)")
    scenarios = {"悲观 (g-5%)": g_base - 0.05, "中性": g_base, "乐观 (g+5%)": g_base + 0.05}
    results = []
    for name, g in scenarios.items():
        fair_v, _, _ = calculate_intrinsic_value(adj_fcf_m, g, r_rate, terminal_g, net_debt_m, shares_m)
        results.append({"情景": name, "增长率": f"{g*100:.1f}%", "内在价值": f"${fair_v:.2f}", "安全边际/涨幅": f"{(fair_v/cur_price-1)*100:.1f}%"})
    st.table(pd.DataFrame(results))

    # --- 5. 财务报表审计 ---
    st.subheader("📋 季度报表审计")
    tab1, tab2, tab3 = st.tabs(["利润表", "资产负债表", "现金流量表"])
    with tab1: st.dataframe(data["q_income"])
    with tab2: st.dataframe(data["q_balance"])
    with tab3: st.dataframe(data["q_cash"])

except Exception as e:
    st.error(f"模型运行出错：{e}")

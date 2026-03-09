import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 核心数据抓取 ---
@st.cache_data(ttl=3600)
def get_full_financial_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    
    # 获取财务报表
    cash_flow = ticker.cashflow
    income_stmt = ticker.financials
    
    # 提取 SBC (Stock Based Compensation)
    sbc_series = cash_flow.loc["Stock Based Compensation"] if "Stock Based Compensation" in cash_flow.index else pd.Series(0, index=cash_flow.columns)
    
    # 提取原始 FCF
    if "Free Cash Flow" in cash_flow.index:
        fcf_raw_series = cash_flow.loc["Free Cash Flow"]
    else:
        fcf_raw_series = cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]
    
    # 计算最新数据
    latest_fcf_raw = fcf_raw_series.iloc[0]
    latest_sbc = sbc_series.iloc[0]
    
    return {
        "fcf_raw": latest_fcf_raw,
        "sbc": latest_sbc,
        "current_price": info.get("currentPrice"),
        "shares": info.get("sharesOutstanding"),
        "net_debt": (info.get("totalDebt", 0) - info.get("totalCash", 0)),
        "q_income": ticker.quarterly_financials,
        "q_balance": ticker.quarterly_balance_sheet,
        "q_cash": ticker.quarterly_cashflow
    }

def calculate_dcf(fcf_m, g, r, tg, net_debt_m, shares_m):
    pvs = [ (fcf_m * (1 + g)**t) / (1 + r)**t for t in range(1, 6) ]
    tv = (fcf_m * (1 + g)**5 * (1 + tg)) / (r - tg)
    pv_tv = tv / (1 + r)**5
    equity_value = (sum(pvs) + pv_tv) - net_debt_m
    return equity_value / shares_m

# --- 2. Streamlit UI ---
st.set_page_config(page_title="SBC 敏感度估值工具", layout="wide")
st.title("⚖️ 估值分歧：SBC 敏感度分析看板")

# 侧边栏
with st.sidebar:
    st.header("1. 输入参数")
    target_ticker = st.text_input("股票代码", value="TEAM").upper()
    
    st.divider()
    st.header("2. 估值口径切换")
    # 核心功能：勾选框
    deduct_sbc = st.checkbox("扣除 SBC 影响 (更保守/真实)", value=True)
    
    st.divider()
    st.header("3. 模型假设")
    g_base = st.number_input("预期增长率 (g)", value=0.250, step=0.005, format="%.3f")
    r_rate = st.number_input("折现率 (WACC)", value=0.100, step=0.005, format="%.3f")
    terminal_g = st.number_input("永续增长率 (tg)", value=0.030, step=0.001, format="%.3f")

try:
    data = get_full_financial_data(target_ticker)
    
    # 单位换算为 Millions
    raw_fcf_m = data["fcf_raw"] / 1e6
    sbc_m = data["sbc"] / 1e6
    shares_m = data["shares"] / 1e6
    net_debt_m = data["net_debt"] / 1e6
    cur_price = data["current_price"]

    # 决定使用的 FCF 口径
    final_fcf_m = (raw_fcf_m - sbc_m) if deduct_sbc else raw_fcf_m
    mode_text = "已扣除 SBC" if deduct_sbc else "未扣除 SBC (原始)"

    # --- 3. 核心指标展示 ---
    st.subheader(f"🔍 现金流对比 ({mode_text})")
    c1, c2, c3 = st.columns(3)
    c1.metric("原始 FCF (M)", f"${raw_fcf_m:.1f}M")
    c2.metric("SBC 支出 (M)", f"- ${sbc_m:.1f}M", delta="稀释风险", delta_color="inverse")
    c3.metric("最终计算用 FCF", f"${final_fcf_m:.1f}M", border=True)

    # --- 4. 情景分析对比表 ---
    st.divider()
    st.subheader(f"📊 {target_ticker} 内在价值推演")
    
    scenarios = {"悲观": g_base - 0.05, "中性": g_base, "乐观": g_base + 0.05}
    comparison_results = []
    
    for name, g in scenarios.items():
        # 当前口径下的估值
        val_current = calculate_dcf(final_fcf_m, g, r_rate, terminal_g, net_debt_m, shares_m)
        # 另一种口径作为参考
        alt_fcf = raw_fcf_m if deduct_sbc else (raw_fcf_m - sbc_m)
        val_alt = calculate_dcf(alt_fcf, g, r_rate, terminal_g, net_debt_m, shares_m)
        
        comparison_results.append({
            "情景": name,
            "预期增速": f"{g*100:.1f}%",
            "当前口径估值": f"${val_current:.2f}",
            "另一种口径参考": f"${val_alt:.2f}",
            "当前涨跌幅": f"{(val_current/cur_price-1)*100:.1f}%"
        })
    
    st.table(pd.DataFrame(comparison_results))

    # --- 5. 报表展示 ---
    with st.expander("查看原始财务报表 (季度)"):
        t1, t2, t3 = st.tabs(["利润表", "资产负债表", "现金流量表"])
        t1.dataframe(data["q_income"])
        t2.dataframe(data["q_balance"])
        t3.dataframe(data["q_cash"])

except Exception as e:
    st.error(f"模型加载失败，请检查 Ticker 是否正确: {e}")

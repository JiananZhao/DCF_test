import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# -----------------------------
# Helpers (robust data handling)
# -----------------------------
def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        if isinstance(x, (np.floating, np.integer)):
            return float(x)
        if isinstance(x, (int, float)):
            return float(x)
        return float(pd.to_numeric(x))
    except Exception:
        return default


def _latest_cols_first(df: pd.DataFrame) -> pd.DataFrame:
    """Sort statement columns newest -> oldest (yfinance columns are usually datetime)."""
    if df is None or df.empty:
        return df
    try:
        return df.sort_index(axis=1, ascending=False)
    except Exception:
        return df


def _get_latest_value(df: pd.DataFrame, row_candidates: list[str]) -> float | None:
    """Get the most recent single-period value for the first row name that exists."""
    if df is None or df.empty:
        return None
    df2 = _latest_cols_first(df)
    for name in row_candidates:
        if name in df2.index:
            s = df2.loc[name].dropna()
            if len(s) >= 1:
                return _safe_float(s.iloc[0], None)
    return None


def _get_ttm_value(df: pd.DataFrame, row_candidates: list[str]) -> float | None:
    """Get TTM by summing latest 4 columns for the first row name that exists."""
    if df is None or df.empty:
        return None
    df2 = _latest_cols_first(df)
    for name in row_candidates:
        if name in df2.index:
            s = df2.loc[name].dropna()
            if len(s) >= 4:
                return _safe_float(s.iloc[:4].sum(), None)
            elif len(s) >= 1:
                # fallback: if not enough quarters, take latest
                return _safe_float(s.iloc[0], None)
    return None


@st.cache_data(ttl=3600)
def get_rf_rate() -> float:
    """
    Robust 10Y risk-free proxy from ^TNX.
    Yahoo often shows ~4.13 (meaning 4.13%), but some feeds can show ~41.3.
    """
    try:
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="10d")
        if hist is None or hist.empty:
            return 0.042
        last = float(hist["Close"].dropna().iloc[-1])

        # Scale guard:
        # - Typical: 3.5 ~ 6.0
        # - Possible alt scale: 35 ~ 60 (10x)
        if last > 20:
            return last / 1000.0
        return last / 100.0
    except Exception:
        return 0.042


def _calc_hist_dilution_rate(ticker: yf.Ticker, start="2021-01-01") -> float:
    """
    Historical share count CAGR from yfinance get_shares_full().
    Returns annualized rate, e.g. 0.02 for +2%/yr.
    """
    try:
        sh = ticker.get_shares_full(start=start)
        if sh is None or sh.empty:
            return 0.0
        sh = sh.dropna()
        if len(sh) < 2:
            return 0.0

        t0, t1 = sh.index[0], sh.index[-1]
        years = (t1 - t0).days / 365.25
        if years <= 0:
            return 0.0

        s0, s1 = float(sh.iloc[0]), float(sh.iloc[-1])
        if s0 <= 0 or s1 <= 0:
            return 0.0

        return (s1 / s0) ** (1 / years) - 1
    except Exception:
        return 0.0


def _fallback_current_price(ticker: yf.Ticker, info: dict) -> float | None:
    px = info.get("currentPrice")
    px = _safe_float(px, None)
    if px is not None:
        return px
    try:
        hist = ticker.history(period="5d")
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].dropna().iloc[-1])
    except Exception:
        return None


# -----------------------------
# Data Fetch (cached)
# -----------------------------
@st.cache_data(ttl=3600)
def get_valuation_data(ticker_symbol: str) -> dict:
    tkr = yf.Ticker(ticker_symbol)
    info = tkr.info or {}

    # Statements
    annual_cf = tkr.cashflow
    annual_is = tkr.financials
    annual_bs = tkr.balance_sheet

    q_cf = tkr.quarterly_cashflow
    q_is = tkr.quarterly_financials
    q_bs = tkr.quarterly_balance_sheet

    rf_rate = get_rf_rate()

    beta = _safe_float(info.get("beta"), 1.2)
    mkt_cap = _safe_float(info.get("marketCap"), 0.0) or 0.0
    total_debt = _safe_float(info.get("totalDebt"), 0.0) or 0.0
    total_cash = _safe_float(info.get("totalCash"), 0.0) or 0.0
    shares_out = _safe_float(info.get("sharesOutstanding"), None)

    current_price = _fallback_current_price(tkr, info)

    # Cash flow components (TTM preferred)
    cfo_ttm = _get_ttm_value(q_cf, [
        "Operating Cash Flow",
        "Total Cash From Operating Activities",
        "Net Cash Provided By Operating Activities",
        "Cash Flow From Continuing Operating Activities",
    ])
    capex_ttm = _get_ttm_value(q_cf, [
        "Capital Expenditures",
        "Capital Expenditure",
    ])
    fcf_ttm = _get_ttm_value(q_cf, [
        "Free Cash Flow",
        "FreeCashFlow",
    ])

    # Annual fallbacks if quarterlies missing
    if cfo_ttm is None:
        cfo_ttm = _get_latest_value(annual_cf, [
            "Operating Cash Flow",
            "Total Cash From Operating Activities",
            "Net Cash Provided By Operating Activities",
            "Cash Flow From Continuing Operating Activities",
        ])
    if capex_ttm is None:
        capex_ttm = _get_latest_value(annual_cf, ["Capital Expenditures", "Capital Expenditure"])
    if fcf_ttm is None:
        # only use annual if exists
        fcf_ttm = _get_latest_value(annual_cf, ["Free Cash Flow", "FreeCashFlow"])

    # SBC (TTM preferred)
    sbc_ttm = _get_ttm_value(q_cf, ["Stock Based Compensation", "Stock-Based Compensation"])
    if sbc_ttm is None:
        sbc_ttm = _get_latest_value(annual_cf, ["Stock Based Compensation", "Stock-Based Compensation"])
    sbc_ttm = _safe_float(sbc_ttm, 0.0) or 0.0

    # Interest expense (TTM preferred)
    # NOTE: Sign can vary in yfinance; we take abs for magnitude.
    interest_ttm = _get_ttm_value(q_is, [
        "Interest Expense",
        "Interest Expense Non Operating",
        "Interest Expense, Net",
        "InterestExpense",
    ])
    if interest_ttm is None:
        interest_ttm = _get_latest_value(annual_is, [
            "Interest Expense",
            "Interest Expense Non Operating",
            "Interest Expense, Net",
            "InterestExpense",
        ])
    interest_ttm = abs(_safe_float(interest_ttm, 0.0) or 0.0)

    # Levered FCF proxy:
    # - Prefer reported Free Cash Flow if present (rare in quarterlies)
    # - Else CFO + CapEx (CapEx typically negative)
    fcf_levered = None
    if fcf_ttm is not None:
        fcf_levered = _safe_float(fcf_ttm, None)
    elif cfo_ttm is not None and capex_ttm is not None:
        fcf_levered = _safe_float(cfo_ttm + capex_ttm, None)

    # Historical dilution
    hist_dilution = _calc_hist_dilution_rate(tkr, start="2021-01-01")

    # Net debt
    net_debt = (total_debt - total_cash)

    # Rough Rd estimate (can be very noisy; still better than hardcoding only)
    # Use interest_ttm / total_debt if feasible, else fallback 5%
    if total_debt and total_debt > 0:
        rd = interest_ttm / total_debt
        # sanity clamp (0%~20%)
        rd = float(np.clip(rd, 0.0, 0.20))
        if rd == 0.0:
            rd = 0.05
    else:
        rd = 0.05

    return {
        "ticker": ticker_symbol,
        "info": info,
        "rf_rate": rf_rate,
        "beta": beta,
        "mkt_cap": mkt_cap,
        "total_debt": total_debt,
        "total_cash": total_cash,
        "net_debt": net_debt,
        "rd": rd,
        "current_price": current_price,
        "shares": shares_out,
        "hist_dilution": float(hist_dilution),

        # cash flow / income components (TTM-ish)
        "cfo_ttm": _safe_float(cfo_ttm, None),
        "capex_ttm": _safe_float(capex_ttm, None),
        "fcf_levered_ttm": _safe_float(fcf_levered, None),
        "sbc_ttm": sbc_ttm,
        "interest_ttm": interest_ttm,

        # raw tables for display
        "q_income": q_is,
        "q_balance": q_bs,
        "q_cash": q_cf,
        "annual_income": annual_is,
        "annual_balance": annual_bs,
        "annual_cash": annual_cf,
    }


# -----------------------------
# DCF Core (FCFF + WACC)
# -----------------------------
def run_dcf_fcff(
    fcff0: float,
    g: float,
    wacc: float,
    tg: float,
    net_debt: float,
    shares0: float,
    dr: float,
    apply_dilution: bool = True,
    years: int = 5,
):
    """
    FCFF DCF:
      EV = PV(FCFF_1..N) + PV(TV_N)
      Equity = EV - NetDebt
      Price = Equity / EffectiveShares

    Dilution handling (if apply_dilution):
      Compute PV-weighted effective time t_eff, then shares_eff = shares0*(1+dr)^t_eff
      This avoids the "divide by year-5 shares" over-penalty.
    """
    if wacc <= tg:
        raise ValueError("WACC 必须大于永续增长率 tg，否则终值发散。请调高 WACC 或调低 tg。")

    # Project & discount FCFF
    pv_list = []
    for t in range(1, years + 1):
        fcff_t = fcff0 * (1 + g) ** t
        pv_t = fcff_t / (1 + wacc) ** t
        pv_list.append(pv_t)

    # Terminal value at year N
    fcff_n = fcff0 * (1 + g) ** years
    tv_n = fcff_n * (1 + tg) / (wacc - tg)
    pv_tv = tv_n / (1 + wacc) ** years

    firm_pv = float(np.sum(pv_list) + pv_tv)
    equity_pv = firm_pv - net_debt

    # Effective shares
    if apply_dilution and dr != 0:
        weights = pv_list + [pv_tv]
        times = list(range(1, years + 1)) + [years]
        denom = float(np.sum(weights))
        if denom <= 0:
            # fallback: if weights weird/negative, just use year-N
            t_eff = years
        else:
            t_eff = float(np.sum([w * t for w, t in zip(weights, times)]) / denom)

        shares_eff = shares0 * (1 + dr) ** t_eff
    else:
        shares_eff = shares0

    if shares_eff <= 0:
        raise ValueError("股本数据异常（shares_eff<=0），无法计算每股价值。")

    return equity_pv / shares_eff


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="DCF Model", layout="wide")
st.title("FCFF-DCF Model")

with st.sidebar:
    st.header("1. Symbol")
    ticker_input = st.text_input("Ticker", value="TEAM").upper().strip()

    st.divider()
    st.header("2. WACC Calc")
    erp = st.number_input("股权风险溢价 (ERP %)", value=5.5, step=0.1) / 100
    tax_rate = st.number_input("企业所得税率 (%)", value=21.0, step=1.0) / 100

    st.divider()
    st.header("3. 现金流口径 & 稀释/SBC")
    sbc_mode = st.radio(
        "SBC 处理方式（避免双重计提）",
        [
            "稀释法（不扣SBC，用股本增长体现）",
            "费用法（扣SBC，股本不再外推稀释）",
        ],
        index=0,
        help=(
            "稀释法：现金流不扣 SBC，但用股本增长率体现经济代价。\n"
            "费用法：从 FCFF 中扣 SBC（近似当作现金成本/回购对冲成本），同时不再外推稀释率。"
        ),
    )

    st.divider()
    st.header("4. Assumption")
    g_base = st.number_input("中性增长率 (g)", value=0.200, step=0.005, format="%.3f")
    terminal_g = st.number_input("永续增长率 (tg)", value=0.030, step=0.001, format="%.3f")


try:
    if not ticker_input:
        st.stop()

    data = get_valuation_data(ticker_input)

    # Basic sanity
    if data["current_price"] is None:
        st.warning("未能从数据源取得 currentPrice，已尝试用近5日收盘价回退；仍失败则无法计算“潜力”。")

    # --- WACC calc ---
    re = data["rf_rate"] + data["beta"] * erp

    v = (data["mkt_cap"] or 0.0) + (data["total_debt"] or 0.0)
    w_e = (data["mkt_cap"] / v) if v > 0 else 1.0
    w_d = (data["total_debt"] / v) if v > 0 else 0.0
    calculated_wacc = (w_e * re) + (w_d * data["rd"] * (1 - tax_rate))

    with st.sidebar:
        final_wacc = st.number_input(
            "最终折现率 (WACC)",
            value=float(calculated_wacc),
            step=0.001,
            format="%.3f",
            help="已根据 CAPM + 债务成本自动计算，可手动覆盖。",
        )

        if sbc_mode.startswith("稀释法"):
            net_rate = st.number_input(
                "预期年化股本变动率（净稀释率）",
                value=float(data["hist_dilution"]),
                step=0.001,
                format="%.3f",
                help="来自历史股本 CAGR 的粗略外推。用于“稀释法”情形。",
            )
        else:
            net_rate = 0.0
            st.caption("费用法已启用：为避免双重计提，稀释率自动设为 0。")

    # --- Guardrails ---
    if final_wacc <= terminal_g:
        st.error("参数错误：WACC 必须大于永续增长率 tg，否则终值会发散。请调高 WACC 或调低 tg。")
        st.stop()

    if data["shares"] is None or data["shares"] <= 0:
        st.error("无法获得有效 sharesOutstanding（股本），无法输出每股估值。")
        st.stop()

    # --- Build FCFF (self-consistent with WACC) ---
    # Levered FCF proxy:
    fcf_levered = data["fcf_levered_ttm"]
    if fcf_levered is None:
        st.error("无法从现金流表得到 FCF/CFO/CapEx（TTM或最新）。请更换标的或稍后重试。")
        st.stop()

    # Unlever to FCFF approx: add back after-tax interest
    # Note: This is a practical approximation when full EBIT/D&A/NWC not reliably available.
    fcff = float(fcf_levered + data["interest_ttm"] * (1 - tax_rate))

    apply_dilution = sbc_mode.startswith("稀释法")
    if sbc_mode.startswith("费用法"):
        # Expense-method: treat SBC as cash-like cost (or buyback needed), so subtract it
        fcff = float(fcff - (data["sbc_ttm"] or 0.0))

    # Units: convert to millions for display & computations (keeps numbers readable)
    fcff_m = fcff / 1e6
    net_debt_m = (data["net_debt"] or 0.0) / 1e6
    shares_m = data["shares"] / 1e6

    # --- Audit panel ---
    st.subheader("📊 自动化参数审计（关键口径已自洽：FCFF + WACC）")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("无风险利率 (10Y)", f"{data['rf_rate']*100:.2f}%")
    c2.metric("Beta", f"{data['beta']:.2f}")
    c3.metric("股权成本 (Re)", f"{re*100:.2f}%")
    c4.metric("计算所得 WACC", f"{calculated_wacc*100:.2f}%", border=True)

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("债务成本 (Rd)", f"{data['rd']*100:.2f}%")
    c6.metric("E/(D+E)", f"{w_e*100:.1f}%")
    c7.metric("D/(D+E)", f"{w_d*100:.1f}%")
    c8.metric("最终 WACC（用于折现）", f"{final_wacc*100:.2f}%")

    st.caption(
        "现金流口径：先用 (CFO + CapEx) 作为“杠杆后 FCF 近似”，再加回税后利息得到 FCFF 近似；"
        "随后按你选择的 SBC 模式（稀释法/费用法）处理。"
    )

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("FCFF (TTM 近似, $m)", f"{fcff_m:,.1f}")
    d2.metric("SBC (TTM, $m)", f"{(data['sbc_ttm']/1e6):,.1f}")
    d3.metric("净负债 Net Debt ($m)", f"{net_debt_m:,.1f}")
    d4.metric("股本 Shares (m)", f"{shares_m:,.1f}")

    # --- DCF scenarios ---
    st.divider()
    st.subheader("🧮 5年显性期 + 永续终值：情景估值（每股内在价值）")

    scenarios = {
        "悲观 (g-5%)": g_base - 0.05,
        "中性": g_base,
        "乐观 (g+5%)": g_base + 0.05,
    }

    rows = []
    for name, g in scenarios.items():
        try:
            intrinsic = run_dcf_fcff(
                fcff0=fcff_m,
                g=g,
                wacc=final_wacc,
                tg=terminal_g,
                net_debt=net_debt_m,
                shares0=shares_m,
                dr=net_rate,
                apply_dilution=apply_dilution,
                years=5,
            )
        except Exception as ex:
            intrinsic = np.nan

        px = data["current_price"]
        if px is not None and np.isfinite(intrinsic):
            upside = (intrinsic / px - 1) * 100
            upside_str = f"{upside:.1f}%"
        else:
            upside_str = "N/A"

        rows.append({
            "情景": name,
            "显性期增速 g": f"{g*100:.1f}%",
            "WACC": f"{final_wacc*100:.2f}%",
            "永续增速 tg": f"{terminal_g*100:.2f}%",
            "SBC模式": "稀释法" if apply_dilution else "费用法",
            "净稀释率": f"{net_rate*100:.2f}%" if apply_dilution else "0.00%",
            "内在价值": (f"${intrinsic:,.2f}" if np.isfinite(intrinsic) else "计算失败"),
            "潜力 vs 当前价": upside_str,
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # --- Optional: sensitivity surface (g x WACC) ---
    st.divider()
    st.subheader("📈 敏感性分析（g × WACC）")

    g_grid = np.array([g_base - 0.06, g_base - 0.03, g_base, g_base + 0.03, g_base + 0.06])
    w_grid = np.array([final_wacc - 0.02, final_wacc - 0.01, final_wacc, final_wacc + 0.01, final_wacc + 0.02])

    sens = []
    for gg in g_grid:
        row = []
        for ww in w_grid:
            try:
                if ww <= terminal_g:
                    row.append(np.nan)
                else:
                    val = run_dcf_fcff(
                        fcff0=fcff_m,
                        g=float(gg),
                        wacc=float(ww),
                        tg=terminal_g,
                        net_debt=net_debt_m,
                        shares0=shares_m,
                        dr=net_rate,
                        apply_dilution=apply_dilution,
                        years=5,
                    )
                    row.append(val)
            except Exception:
                row.append(np.nan)
        sens.append(row)

    sens_df = pd.DataFrame(
        sens,
        index=[f"g={x*100:.1f}%" for x in g_grid],
        columns=[f"WACC={x*100:.2f}%" for x in w_grid],
    )

    st.dataframe(sens_df.style.format("{:.2f}"), use_container_width=True)

    # Heatmap
    fig = go.Figure(
        data=go.Heatmap(
            z=sens_df.values,
            x=sens_df.columns.tolist(),
            y=sens_df.index.tolist(),
            hoverongaps=False,
            colorbar=dict(title="$/share"),
        )
    )
    fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Raw statements ---
    with st.expander("🔍 查看原始财务数据（季度 & 年度）"):
        tabs = st.tabs(["季度利润表", "季度资产负债表", "季度现金流表", "年度利润表", "年度资产负债表", "年度现金流表"])
        tabs[0].dataframe(data["q_income"], use_container_width=True)
        tabs[1].dataframe(data["q_balance"], use_container_width=True)
        tabs[2].dataframe(data["q_cash"], use_container_width=True)
        tabs[3].dataframe(data["annual_income"], use_container_width=True)
        tabs[4].dataframe(data["annual_balance"], use_container_width=True)
        tabs[5].dataframe(data["annual_cash"], use_container_width=True)

    # --- Extra: show the core numeric inputs used ---
    with st.expander("🧾 关键取数明细（用于排错）"):
        st.write({
            "current_price": data["current_price"],
            "rf_rate": data["rf_rate"],
            "beta": data["beta"],
            "ERP": erp,
            "Re": re,
            "marketCap": data["mkt_cap"],
            "totalDebt": data["total_debt"],
            "totalCash": data["total_cash"],
            "netDebt": data["net_debt"],
            "interest_ttm": data["interest_ttm"],
            "Rd_est": data["rd"],
            "CFO_ttm": data["cfo_ttm"],
            "CapEx_ttm": data["capex_ttm"],
            "FCF_levered_proxy_ttm": data["fcf_levered_ttm"],
            "SBC_ttm": data["sbc_ttm"],
            "FCFF_used": fcff,
            "hist_dilution": data["hist_dilution"],
            "apply_dilution": apply_dilution,
            "net_rate_used": net_rate,
            "WACC_auto": calculated_wacc,
            "WACC_final": final_wacc,
            "g_base": g_base,
            "terminal_g": terminal_g,
        })

except Exception as e:
    st.error(f"分析出错：{e}")

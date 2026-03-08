import yfinance as yf
import pandas as pd

def get_valuation_metrics(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    
    # 获取财务报表
    income_stmt = ticker.financials
    cash_flow = ticker.cashflow
    
    # 提取收入和自由现金流 (取最近3年)
    revenue = income_stmt.loc["Total Revenue"].iloc[:3]
    
    if "Free Cash Flow" in cash_flow.index:
        fcf = cash_flow.loc["Free Cash Flow"].iloc[:3]
    else:
        fcf = (cash_flow.loc["Operating Cash Flow"] + cash_flow.loc["Capital Expenditures"]).iloc[:3]
    
    # 构建指标表格
    metrics_df = pd.DataFrame({
        "Revenue (M)": revenue / 1e6,
        "FCF (M)": fcf / 1e6,
        "FCF Margin (%)": (fcf / revenue) * 100
    })
    
    return metrics_df.sort_index()

# 示例：查看 TEAM 的利润率
team_metrics = get_valuation_metrics("TEAM")
print("TEAM 过去三年财务指标：")
print(team_metrics)

def run_basic_dcf(ticker_symbol, growth_rate=0.20, discount_rate=0.10, terminal_growth=0.03):
    # 1. 获取最新 FCF 数据
    metrics = get_valuation_metrics(ticker_symbol)
    current_fcf = metrics["FCF (M)"].iloc[-1]
    
    # 2. 预测未来 5 年现金流
    forecast_fcf = []
    for t in range(1, 6):
        projected_fcf = current_fcf * (1 + growth_rate)**t
        pv_fcf = projected_fcf / (1 + discount_rate)**t
        forecast_fcf.append(pv_fcf)
    
    # 3. 计算终值 (Terminal Value) 及其现值
    fcf_year_5 = current_fcf * (1 + growth_rate)**5
    tv = (fcf_year_5 * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv_tv = tv / (1 + discount_rate)**5
    
    # 4. 计算企业价值 (Enterprise Value)
    enterprise_value = sum(forecast_fcf) + pv_tv
    
    return {
        "Ticker": ticker_symbol,
        "Current FCF (M)": round(current_fcf, 2),
        "PV of 5Y Cash Flows (M)": round(sum(forecast_fcf), 2),
        "PV of Terminal Value (M)": round(pv_tv, 2),
        "Intrinsic Enterprise Value (M)": round(enterprise_value, 2)
    }

# 运行估值
dcf_result = run_basic_dcf("TEAM", growth_rate=0.25) # 假设 25% 的高增长
print("\nDCF 估值分析结果：")
for key, value in dcf_result.items():
    print(f"{key}: {value}")

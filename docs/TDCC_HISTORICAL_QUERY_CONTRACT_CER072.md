# TDCC Historical Query Contract (CER-072)

Verified against the official TDCC shareholder-distribution historical query page:

- Product: 集保戶股權分散表
- Official page: https://www.tdcc.com.tw/portal/zh/smWeb/qryStock
- Official product/API listing: https://openapi.tdcc.com.tw/swagger-ui/index.html?configUrl=%2Ftdcc-opendata-api-docs
- Current open-data endpoint: /v1/opendata/1-5 (current snapshot only; not used for historical replay)
- Historical transport: POST https://www.tdcc.com.tw/portal/zh/smWeb/qryStock
- Granularity: SYMBOL_DATE
- Form fields: SYNCHRONIZER_TOKEN, SYNCHRONIZER_URI, method=submit, firDate, scaDate (YYYYMMDD), sqlMethod=StockNo, stockNo, stockName
- Response: UTF-8 HTML with the selected security, ROC-formatted 資料日期, and a tier table containing 序 / 持股/單位數分級 / 人數 / 股數/單位數 / 占集保庫存數比例 (%)
- Required tiers: 1–15; tier 16 (差異數調整) and tier 17 (合計) are excluded from holder_pct_400.
- Identity checks: the response symbol and normalized Gregorian response date must equal the requested symbol/date.
- Historical periods are discovered from the official select options. Replay dates use only the five latest listed periods with period_end <= replay_session; no weekday or fixed seven-day assumptions.

Live transport observation recorded during CER-072 engineering: official form GET and subsequent POST returned HTTP 200; the POST for symbol 2313 and requested period 2026-09-04 returned UTF-8 HTML, the same symbol, and official period 115年09月04日 with the tier table. Synchronizer tokens and cookies are runtime-only and are never stored in source or evidence.

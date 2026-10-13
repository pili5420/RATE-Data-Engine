# RATE M-H History-Only Acquisition Wiring V1

CR: `RATE-MH-HISTORY-ACQUISITION-WIRING-001`.
Engineering base: `54c318c2a72fbd87fa3d03f3f19fa1284e6426f6`.
Planning semantic SHA256: `c5478807f9851be605f73b6115e234687cfe18c215fac5e9529279955f553341`.

This additive, opt-in path is not warmup, First Refresh, ranking, Production
publication or authorization for any live request. Existing source and
normalization owners, strategies, weights, scheduler and state owners are unchanged.

## Sources and Ownership

| Family | Existing source owner | Endpoint / method / parameters |
|---|---|---|
| TWSE stock | TWSEAdapter.fetch_historical_symbol | GET `https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY`, date=YYYYMM01,stockNo=symbol,response=json |
| TPEX stock | TPExAdapter.fetch_historical_symbol | POST `https://www.tpex.org.tw/www/en-us/afterTrading/tradingStock`, code=symbol,date=YYYY/MM/01,response=json |
| TWSE benchmark | TWSEAdapter.fetch_historical_benchmark | GET `https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST`, date=YYYYMM01,response=json |
| TPEX benchmark | TPExAdapter.fetch_historical_benchmark | POST `https://www.tpex.org.tw/www/zh-tw/indexInfo/inx`, date=YYYY/MM/01,response=json,id= |

The dedicated transport reuses these products, not legacy network methods.
Those methods' retry/redirect/fallback behavior is never invoked. Exactly one
standard-library opener call, verified TLS, disabled environment proxies,
NoRedirect, timeout30, credentialsNONE, retry0, fallbackfalse. GET query and POST
form are generated from fixed owner-bound endpoints, not caller URLs. Every
entry must match the canonical generator before the opener is constructed.

Existing `normalize_stock_record`, `extract_symbol_month_rows`,
`normalize_benchmark` and date/numeric ownership remain authoritative. The new
validation boundary accounts for every row first, then calls the existing owner.
No legacy catch-and-drop month helper is used. Raw fields, raw row index and JSON
locator remain bound to exact original bytes. In-memory normalizer inputs are
explicitly derived and never presented as raw responses.

TWSE stock requires explicit source company identity. A title-only or otherwise
unqualified schema fails closed rather than inventing a company match. TPEx uses
exact code or the existing subtitle identity with strict token boundaries. Future
real historical response qualification must verify this boundary against exact
bytes before any full-history execution; engineering fixtures do not prove it.

## Lifecycle and Budget

`plan -> seal -> pending candidate -> external Control Center authorization ->
trusted authorization pin -> exclusive single-use claim -> sequential requests ->
checkpoints -> PASS evidence-only result or persistent STOP`.

There is no authorize operation. The CLI never changes candidate status and has
no synthetic-execution flag. Production execution requires clean main matching
origin/main and the approved plan head, every owner matching its committed Git
blob, external evidence/consumption roots, a new immediate-child execution root,
and an independently supplied trusted authorization semantic SHA256. Synthetic
scope can only run through an explicitly injected mock transport in tests and is
rejected by the real CLI execution preflight.

All requests are enumerated before authorization: benchmarks first, market,
symbol, descending month, then deterministic ordinal. Request keys are unique.
Required universe is exactly1085+893 with the accepted universe hash, not a
Fundamental-ready subset. Maximum budget equals the exact list length and cannot
exceed the planning envelope23760 or12 months. Budget is checked again before
each dispatch. No adaptive request expansion, provider substitution or extra
Fundamental/institutional/TDCC request can occur. Current live grant remains0.

DispatchGate enforces>=13s at CAPTURE_CALL_NOT_HTTP_WIRE_START, checks again before
capture, compensates early sleep, records monotonic/UTC/session evidence, and
waits conservatively on the first dispatch of every process. Different clock
domains are not compared. No schedule or automatic continuation is added.

## Immutable Evidence and Replay

Two OS-held writer locks protect evidence and consumption roots. Claim is an
exclusive-create/fsync record before the first intent/network call; it is never
deleted or reset, even when execution crashes before recording a response.

Every request has an immutable ordinal intent and content-addressed exact raw
bytes plus receipt. Receipt includes request ordinal/key, market/product/symbol,
month, HTTP method/query/form, endpoint/final URL, requested/request-start/received/
validated timestamps, raw byte length/SHA256, intent and all owner identities,
content type/status, redirect/retry/fallback facts. Hashing decoded/re-serialized
JSON cannot replace raw evidence.

Events bind original intent, raw, receipt, complete validation/normalization,
previous ledger head and semantic event hash. Checkpoints bind the exact completed
ordinal sequence and new head. Existing records are never overwritten. All
expected objects must remain present; unreferenced raw/receipt objects are rejected.

Offline replay repeats source parsing and normalization, checks plan/seal/current
owners/consumption, intent dispatch digests/time/session continuity, raw/receipt
bindings, checkpoints, ledger and full result. CLI replay installs the existing
network-denial guard. A killed process without RESULT remains consumed and replay
returns HISTORY_UNKNOWN_OUTCOME_NO_RESUME. No replay operation sends a request or
repairs a ledger. No resume API is authorized.

HTTP/network/timeout/redirect/schema/identity/period/hash/date/duplicate/owner
failure stops immediately after saving available exact response evidence, a
hashed STOP and traceback. Unknown outcomes stop permanently. The first failing
request is the last transport call. Legitimate missing values are retained as
explicit missing rows, not fabricated prices. Empty period semantics are not
qualified by this engineering change and fail closed.

## Readiness and Unresolved Gates

Benchmark chains are independently source-native; no same-latest-date rule is
introduced in this history path. Distinct validated completed benchmark dates
can establish>=180, but calendar readiness additionally requires stock-source
confirmation. This is not an inference from weekdays or another market. No real
180-session calendar is claimed by synthetic tests.

Every result contains1978 issuers, READY/NOT_READY, explicit reasons, valid partial
records and missing required sessions. No zero/forward fill, older-date fishing,
cross-market replacement, silent issuer removal or synthetic history. Input
readiness never grants ranking or Production eligibility. New listing/suspension
causes are not inferred from absent rows.

Stock dates outside the verified own-market benchmark chain are preserved as
unconfirmed sessions, make that issuer NOT_READY, and cannot grant calendar
credit. A stock response never silently invents or expands a benchmark session.

TPEx stock parsing preserves the original numeric scale and always emits
`TPEX_UNIT_SCALE_QUALIFICATION_REQUIRED`; no unit multiplier is applied. The
existing `Trade unit` / `Trade Amt.(NTD1000)` copying behavior cannot establish
common share/NTD scale by itself. TPEx stock evidence remains NOT_READY until a
separately approved deterministic unit qualification boundary is provided. A
schema-positive synthetic test is not a unit-qualification PASS.

The existing Phase M decision contract is deliberately unchanged:
`src/full_market_component_evidence.py::build` requires `dates[-1] == target`,
`latest_official_session[market] == target` under
COMPONENT_LATEST_VERIFIED_SESSION_REQUIRED, and equal final12 session dates under
COMPONENT_CROSS_MARKET_SESSION_ALIGNMENT. Its accepted source scope is fixed in
`docs/contracts/RATE_FULL_MARKET_COMPONENT_EVIDENCE_V1.json`. Relaxing this owner
would change controlled cross-sectional semantics, so the downstream status is
`CONTROL_CENTER_SPEC_DECISION_REQUIRED`, not an engineering policy decision.

## Verification and Governance

New tests are synthetic-only, including all four products, strict negative gates,
claim-before-dispatch, consumed reuse, process interruption, conservative pacing,
missingness, unit blocking, exact-byte/receipt/checkpoint/ledger/result tampering,
and independent-process cold replay. Windows/Linux exact-head CI reuses all current
inherited regression groups and the current-main replacement continuity gate.
The new verifier requires exactly nine additive files and preserves every base
Git blob; it does not import a historical PR diff allowlist as this PR's gate.

Historical PIT=UNPROVEN; original eight-quarter credit0; Intraday=BLOCKED_EXTERNAL;
fallbackfalse; ranking0; Production publication0; decision/production eligibility
false. No old evidence root, historical pin, activation binding, state, portfolio,
transaction ledger, model, strategy, ranking owner or formula is changed.

Next gate: Control Center engineering review, explicit common-cutoff policy
decision, and separately authorized small historical schema/unit qualification.
No consumed discovery authorization is reusable. No full-history live run, merge,
schedule, warmup or ranking activation is performed by this CR.

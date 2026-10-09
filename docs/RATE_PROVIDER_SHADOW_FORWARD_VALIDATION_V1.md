# Provider Shadow Observed-Forward Validation V1

Candidate paper validation only. Existing financial feature/Shadow formula,
50/30/20 weights, pctl, competition ties, universe and missing rules unchanged.
No acquisition, model search, formal score, trade signal or Production integration.
Contract: `contracts/RATE_PROVIDER_SHADOW_FORWARD_VALIDATION_V1.json`.

## Registration and Time

Use externally pinned existing Shadow manifest and original producer binding;
replay feature delivery and all financial sources through the existing consumers.
The official-revenue snapshot embeds its producer checkout's absolute parser path.
Invoke the original exact-clean, hash-pinned producer consumer in a subprocess;
do not substitute the new Forward checkout into that old source plan. Preserve
the original Producer and record the new Forward Execution separately, including
the source consumer command/hash/result. No original code or evidence is changed.
Seal a new compact baseline without regenerating/rebinding the old Shadow package.
Keep source content identities/population, original available/observation time,
execution Head, universe identity, contract/effective/seal time and all1978 members.
Only source-filtered scoring members enter score buckets; unscored remain null and
are evaluated separately for missingness bias. Real material remains local.

A new baseline must register within5 seconds of its actual seal, after all source
verification. This prohibits retroactive enrollment using past closes. Repeat
registration of the same source package is idempotent, not another observation.
New snapshots must have strictly increasing seal times and distinct package IDs.
Earliest entry is the first verified official market close strictly after BOTH
baseline seal and Shadow availability. Old historical PIT remains UNPROVEN.

## Append-Only Persistence

Three directories: SHADOW_FORWARD_SNAPSHOT_LEDGER, SHADOW_FORWARD_RETURN_LEDGER,
SHADOW_FORWARD_EVALUATION_LEDGER. Each event is exclusively created, numbered and
SHA256 linked to the previous event. Schema: kind,sequence,previous_sha256,
recorded_at,payload,event_sha256. External checkpoint SHA256 pins all three terminal
heads, so deletion/truncation is detectable; hashes alone are not a signature or
proof against an attacker who can also replace the trusted checkpoint. Preserve
checkpoints in controlled evidence storage. OS writer lock is exact runtime
`.scan.lock`, outside content hashing, and never disables ledger source checks.

Snapshots cannot change. PENDING records transition by NEW events to FINALIZED or
FAIL_CLOSED; old records remain intact. Identical replay adds no event. A different
second finalization, old-entry revision or duplicate logical finalization fails.
Completed rows may be carried identically in later full-state events, not changed.
Source integrity failures append a persistent FAIL_CLOSED stop event; no retry or
automatic repair clears it. Verification replays source bytes/receipts and price
values and checks market session offsets, original references and observation times.

## Official Price Bridge (No Collector)

Only existing RATE TWSE STOCK_DAY/MI_5MINS_HIST and TPEX tradingStock/indexInfo/inx
monthly JSON products. Reuse materialize_production_history_store normalizers with
an offline ArchivedAdapter; no HTTP methods are invoked. No alternative feeds.
Future evaluations require a trusted external SHA of a
RATE_OFFICIAL_FORWARD_PRICE_ARCHIVE_MANIFEST_V1 with sessions_complete_through and
sources [{receipt_path,receipt_sha256}]. Each receipt binds raw_path/raw_sha256/bytes,
HTTP200/final_url/endpoint, market,stock or benchmark domain, symbol,YYYYMM,
request_method/request_params, and actual observed_at. Only authenticated controlled
source evidence is an acceptable trust anchor; a user-supplied self-hash is not
permission to fabricate official receipts. Existing producer identity must be
retained in controlled acquisition evidence; this bridge does not authorize one.

Benchmark archive months must cover every month from enrollment through the
verified coverage date for BOTH markets. Trading sessions are actual benchmark
rows, never weekdays or the old single-holiday acceptance calendar. Stock dates
must belong to those sessions. Use market close13:30+08:00, observed only after
close. Entry plus5/20/60 MARKET sessions, not five calendar dates or next five
stock quotes. Pending dates are unknown until supported by session evidence.
Administrative next evaluation check is one calendar day later; not an asserted
trading day, a maturity prediction or an automatically installed schedule.

Missing first entry, delisted/suspended/unknown missing daily path or exit fails
closed for that company-horizon; no late-entry selection, zero loss assumption,
carry forward or survivor-only population replacement. All failure counts and
denominators remain visible. Freeze observed entries and earlier used price points;
later revised values cannot replace them. Existing official close prices are
UNADJUSTED price returns, not dividend-inclusive total returns. Corporate actions,
share changes and gaps can confound interpretation; no alternative adjustment
source is invented. Keep outliers and show influence diagnostics, not remove them.

## Frozen Evaluation

Top10/Top20: competition rank <=ceil(fraction*N). Bottom uses reverse competition
rank. Include all boundary ties, even if bucket size grows; symbols only sort
display. Middle excludes both Top20 and Bottom20. Mark tie-overlap/undefined IC.
All five buckets report mean,median,positive-return win rate,cross-sectional sample
volatility, equal-weight buy-and-hold normalized daily-close max drawdown, sample
count,expected count,pending/failure and coverage. Volatility is not annualized or
portfolio volatility. Drawdown uses only finalized available full paths and its
coverage is explicit; missing firms are not silently valued at zero.

Spearman IC is Pearson correlation of average tie ranks on matched scored returns.
Top10-Bottom10/Top20-Bottom20 spreads are arithmetic means. Score/rank correlation,
Top10/20 retention and one-way turnover compare consecutive frozen snapshots on
common membership. Selection bias compares scored versus unscored returns with
separate source coverage, not zero-imputed scores. Keep every company and all
primary returns; leave-one-out IC/spreads and return extremes diagnose influence.
Overlapping forward windows are dependent, not20 independent experiments; series
and coverage are supplied without naive independence/significance claims.

GateA/B/C each need20 valid matured snapshots at5/20/60 days. Until then INCONCLUSIVE.
Even at20, quantitative evidence is INCONCLUSIVE pending Control Center adjudication:
IC direction/stability,spreads,monotonicity,coverage,turnover,missingness bias,outliers.
Source integrity failure is FAIL, not a predictive-performance result. No automatic
PASS threshold or Production qualification is invented. Future hypotheses belong
only to FUTURE_EXPERIMENT_CANDIDATE and cannot change this V1.

## CLI and Isolation

scripts/run_provider_shadow_forward.py modes baseline/verify/evaluate require exact
clean Base/Head, external candidate ledger/new report path and trusted source pins
or checkpoint SHA. Offline sockets are disabled. Cold verify rebuilds the original
baseline from original producer/source inputs; it never rewrites or regenerates it.
Existing211 regressions plus new synthetic forward tests run on Windows/Linux.
All prior tracked files are protected byte/blob unchanged; no formal reverse imports.
Real baseline/returns/receipts stay local; public CI uploads synthetic evidence only.
READY_FOR_REVIEW, no merge/schedule, Production, Portfolio, Run-5 or rebaseline.

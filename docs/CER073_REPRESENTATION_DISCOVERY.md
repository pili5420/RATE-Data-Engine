# CER-073 official representation discovery

Scope: an isolated, read-only discovery workflow. It writes only the two JSON
evidence artifacts and never invokes the historical bootstrap, full assembly,
stock/institutional/TDCC/Stage replay, source bundle, Phase A2, or decision state.
No production adapter, historical layer, model weights, scoring, percentile
methodology, or ranking logic is changed.

Baseline: `5ca982c7bffa86d38434fec2d08ac69cbd63e2f2`.
As-of date: `2026-09-19` (the continued CER request date).

## Revenue

The official MOPS `nas/t21/{sii,otc}/t21sc03_115_{6,7,8}_{0,1}.html`
representations are probed, not inferred authoritative from filename suffixes.
Their report heading supplies response-owned revenue period; the table supplies
company symbol and year-over-year percentage. The `_1` TWSE representation
returns 3661. The header's `出表日期` is the report generation date and is
explicitly rejected as historical company disclosure date. `_0` remains
`OFFICIAL_VALUE_ARCHIVE_REACHABLE / LINEAGE_INCOMPLETE` by itself.

MOPS `POST /mops/web/ezsearch_query`, `step=00`, `RADIO_CM=2`,
`CO_ID=<symbol>`, `PRO_ITEM=F22`, `lang=TW`, returns official announcement
records. Each accepted date record independently establishes `COMPANY_ID`,
`SUBJECT` revenue year/month, matching `HYPERLINK` company/year/month, and
`CDATE`/`CTIME`. The join uses only `(symbol, revenue_period)`. Retrieval
timestamps, header dates, HTTP dates, and filing deadlines do not participate.

The resulting evidence is `OFFICIAL_DUAL_SOURCE_LINEAGE`. Both source hashes,
exact endpoints, announcement evidence, and a combined content hash are retained.
Missing, conflicting, ambiguous, and post-as-of records fail closed. Coverage
requires each symbol to appear in all three requested months. The 90 event
records are evidence in the discovery artifact, not an historical-store bootstrap.

## EPS

The t163 response is diagnosed using HTML tag counts independently of schema
matching. Only the sanitized first 2 KiB and structural metadata are retained.
No complete raw HTML is persisted and no new t163 period regex is introduced.

MOPSFin's official page defines `POST https://mopsfin.twse.com.tw/compare/data`
with form parameters:

```
compareItem=EPS
companyId=<2330|6274|3661>
quarter=true
ylabel=元
ys=0
revenue=false
bcodeAvg=false
companyAvg=false
qnumber=
```

`showNameList[0]` and the series label prove company identity. A point's explicit
index maps to `xaxisList`, which contains year/quarter labels. Only the requested
2026Q2, 2026Q1, 2025Q4, 2025Q3 values are retained. `quarter=false` and
`qnumber=3` or `4` return the cumulative Q3 or full-year series for an independent
Q4 subtraction check. The official `/terms` methodology and actual responses
jointly establish semantics; documentation alone is insufficient.

Official `doc.twse.com.tw/server-java/t57sb01`, `mtype=A`, supplies the
consolidated filing's symbol, fiscal period, exact filename, upload date, and
correction indicator. Corrected filings additionally require matching MOPS
`ajax_t56sb31_q1` company, response-owned year/quarter, consolidated report type,
and actual correction announcement date. Conservative availability is the later
of upload and correction dates. It is not a claim about the first earnings
announcement or the original pre-correction vintage. Local discovery identified
6274 2025Q4 (correction 2026-03-18) and 3661 2025Q3 (2025-12-02).

MOPSFin exposes normalized EPS without consumer-side accounting category
parameters. That consumer does not require raw statement taxonomy routing;
raw MOPS statements and any future XBRL consumer still do. The current test
scope covers only the requested three companies and four quarters. A verified
MOPSFin transport leaves XBRL fallback `NOT_RUN`.

## Execution and isolation

```
python -m unittest tests.test_cer073_representation_discovery
python scripts/discover_fundamental_representations.py --as-of-date 2026-09-19
```

The Actions workflow is `RATE CER-073 Fundamental Representation Discovery`.
Publish its commit with `[skip ci]` to suppress the existing staging push
workflows, then explicitly dispatch only this workflow. Keep main unchanged.
Both artifacts being verified makes discovery eligible for a separately
authorized bootstrap follow-up; this workflow never launches that follow-up.

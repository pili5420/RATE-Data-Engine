# RATE M-H TWSE Title Identity Fix V1

CR: `RATE-MH-TWSE-TITLE-IDENTITY-001`.
Base: `8471bf53bec15a82da7976ac9be86ac0f9faff5f`.
Scope: engineering only, saved exact-byte replay and synthetic CI; no live request.

## Qualified Saved Shape

Saved raw SHA256: `940808b14a658103aacd5a7b430c65406fcad646e25e420a688984bdb8eb2ab0`.
Receipt SHA256: `c8ae4c475d8409e8b71618be7cb8a336b56d91f376bb3ea17e75ee2312a420bf`.
TWSE STOCK_DAY, requested1101 /202609, HTTP200, fields/data20 rows. Exact title:

```text
115年09月 1101 台泥             各日成交資訊
```

UTF-8 hex:
`313135e5b9b43039e69c88203131303120e58fb0e6b3a520202020202020202020202020e59084e697a5e68890e4baa4e8b387e8a88a`.

Tokens: ROC month prefix, one ASCII space, four-digit issuer token, one ASCII
space, CJK company-name token,13 ASCII padding spaces, literal product suffix.
The title does not begin with the issuer code; the entire form is anchored.
This is source-shape evidence, not a general proof of other title formats.

## Narrow Acceptance

Only `market=TWSE, product=stock`, with no explicit `code/stockNo/symbol`, may
use top-level `payload.title`. Existing explicit fields retain highest priority;
any mismatch fails even if the title contains the requested symbol.

`re.fullmatch` grammar:

```text
[1-9][0-9]{2}年(0[1-9]|1[0-2])月 [0-9]{4} [\u4e00-\u9fff]+ +各日成交資訊
```

The captured issuer token must equal the requested symbol. ROC year+1911 and
the title month must equal the requested period. Company name is opaque, never
the sole identity proof. Padding may be one or more ASCII spaces; the source
string is never trimmed or rewritten. Other whitespace, prefixes/suffixes,
extra issuer tokens, unsupported company-token forms and malformed titles fail
closed. `1101` cannot match `11010`, `A1101` or `1101A`.

Independent row-period, schema, duplicate/future date, OHLC, numeric and
missingness validation still runs unchanged. Title PASS does not bypass them.
TPEx subtitle and benchmark logic remain unchanged.

## Verification and Historical Boundary

Saved real bytes remain local. Before-edit old-main replay reproduces
HISTORY_SYMBOL_IDENTITY_REQUIRED. New-parser same-byte replay must pass all
existing gates with20 normalized rows, no loss or raw/receipt mutation.
This verifies only those exact captured bytes under the new parser; it does not
rewrite or promote the old STOP result, old owner pins or acquisition timestamps.
Old authorization remains CONSUMED / NOT_REUSABLE. No execute/resume is called.

Public CI contains synthetic values only. The current-main verifier reuses all
1651 inherited tests and adds focused title tests. It requires exactly one
runtime change, this documentation/test/verifier and the necessary CI binding.
AST proofs preserve all non-identity functions, explicit identities, TPEx
subtitle and benchmark branches. Historical PR67 verifier stays unchanged;
the workflow now uses this CR's actual base and scope, not its old diff allowlist.
Current-main replacement and continuity checks remain mandatory on both OSes.

Endpoints, transport, timeout30, interval>=13, retry0, redirectfalse, fallbackfalse,
budget, authorization lifecycle, Phase M common-cutoff and TPEx units unchanged.
Historical PIT UNPROVEN; calendar180false; Ranking NOT_AUTHORIZED;
Intraday BLOCKED_EXTERNAL; TPEX_UNIT_SCALE_QUALIFICATION_REQUIRED.
No ranking/Production/state/Portfolio/Ledger/strategy/model changes or publication.

Next: Control Center engineering review. No merge, fix-to-live automatic retry,
fresh authorization or live source qualification is performed by this CR.

# RATE_PRODUCTION_LOGIC_SPEC V1.1
Status: PRODUCTION_READY / FROZEN
Owner: RATE / OIS AI Control Center
System: RATE V11

## Controlled Modules
1. M7
2. MHE
3. Stage
4. Rotation
5. Smart Money
6. Top50 / Short-Term Top30 / Long-Term Top30

## M7
All components normalized to 0–100.

M7 = 0.20*PT + 0.15*PV + 0.15*MO + 0.15*FI + 0.10*IT + 0.15*LH + 0.10*RS

Components:
- Price Trend 20%
- Price/Volume 15%
- Momentum 15%
- Foreign Institutional 15%
- Investment Trust 10%
- Large Holder 15%
- Relative Strength 10%

Classification:
- 80–100: STRONG_CONFIRM
- 65–<80: STRENGTHENING
- 50–<65: NEUTRAL
- 35–<50: WEAKENING
- 0–<35: WEAK

## MHE
H5/H20/H60/H120 normalized to 0–100.

MHE = 0.20*H5 + 0.30*H20 + 0.30*H60 + 0.20*H120

Classification:
- >=75: MULTI_HORIZON_BULLISH
- 60–<75: BULLISH
- 45–<60: MIXED_NEUTRAL
- 30–<45: BEARISH
- <30: MULTI_HORIZON_BEARISH

Conflict states:
- NONE
- SHORT_BULL_LONG_BEAR
- SHORT_BEAR_LONG_BULL

## Stage
Allowed lifecycle states:
- BASE_BUILDING / 築底期
- STRENGTHENING / 轉強期
- PRE_MARKUP / 主升準備期
- MARKUP / 主升期
- HIGH_ROTATION / 高檔輪動期
- HIGH_CONSOLIDATION / 高檔整理期
- CONSOLIDATION / 整理期
- DEFENSIVE / 防禦期

Evidence basis:
MA20 / MA60 / MA120, MA slopes, Relative Strength, M7, MHE, price structure.

Default transition is adjacent-stage only.
Structural failure may override directly to DEFENSIVE, with stage_override_reason required.

## Rotation
Rotation = 0.30*RS_CHANGE + 0.25*VOL_CHANGE + 0.25*SMART_MONEY + 0.20*MOMENTUM_CHANGE

Classification:
- >=80: ACCELERATING
- 65–<80: STRENGTHENING
- 45–<65: FLAT
- 30–<45: WEAKENING
- <30: WARNING

## Smart Money
SmartMoney = 0.30*FI + 0.25*IT + 0.25*LH + 0.20*FC

Classification:
- >=75: STRONG_INFLOW
- 60–<75: INFLOW
- 45–<60: NEUTRAL
- 30–<45: OUTFLOW
- <30: STRONG_OUTFLOW

## Top50 Composite
RATE_SCORE =
0.20*M7 +
0.15*MHE +
0.15*Stage +
0.15*Rotation +
0.15*SmartMoney +
0.10*Fundamental +
0.10*RelativeStrength

Eligible candidate pool is ranked first; Top50 is the top 50 results.

## Short-Term Top30
ShortScore =
0.25*M7 +
0.20*Rotation +
0.20*SmartMoney +
0.15*MHE +
0.10*Stage +
0.10*RelativeStrength

## Long-Term Top30
LongScore =
0.25*Fundamental +
0.20*Stage +
0.20*MHE +
0.15*SmartMoney +
0.10*RelativeStrength +
0.10*M7

## Tie-break
1. Smart Money
2. MHE
3. Relative Strength
4. Liquidity
5. Symbol ascending

## Missing Data
NULL must not be silently converted to 0 or previous value.
Blocking data missing => DATA_INCOMPLETE.

## Determinism
Same spec + input snapshot + engine version must produce identical results.

## Governance
No change to formula, weights, thresholds, classifications, candidate filters, or ranking logic is allowed without a Control Center Change Request.

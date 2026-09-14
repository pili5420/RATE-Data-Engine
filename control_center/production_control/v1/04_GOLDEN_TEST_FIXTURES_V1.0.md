# GOLDEN_TEST_FIXTURES V1.0
Status: FROZEN

## M7-01 Bullish
Input: PT=90, PV=80, MO=85, FI=75, IT=70, LH=80, RS=90
Expected M7=82.75
Expected state=STRONG_CONFIRM

## M7-02 Neutral
Input: PT=55, PV=50, MO=55, FI=50, IT=50, LH=55, RS=50
Expected M7=52.75
Expected state=NEUTRAL

## M7-03 Bearish
Input: PT=20, PV=30, MO=25, FI=20, IT=30, LH=25, RS=20
Expected M7=24.00
Expected state=WEAK

## M7-04 Boundary
All components=65
Expected M7=65.00
Expected state=STRENGTHENING

## M7-05 Missing
LH=NULL
Expected:
calculation_status=DATA_INCOMPLETE
validation_status=DATA_INCOMPLETE
m7_score=NULL

## MHE-01 Bullish
H5=80, H20=85, H60=80, H120=75
Expected MHE=80.50
State=MULTI_HORIZON_BULLISH
Conflict=NONE

## MHE-02 Short Bull / Long Bear
H5=80, H20=75, H60=35, H120=30
Expected MHE=55.00
State=MIXED_NEUTRAL
Conflict=SHORT_BULL_LONG_BEAR

## MHE-03 Short Bear / Long Bull
H5=25, H20=35, H60=75, H120=80
Expected MHE=54.00
Conflict=SHORT_BEAR_LONG_BULL

## ROT-01 Acceleration
RS_CHANGE=90, VOL_CHANGE=80, SMART_MONEY=85, MOMENTUM_CHANGE=80
Expected Rotation=84.25
State=ACCELERATING

## ROT-02 Warning
RS_CHANGE=20, VOL_CHANGE=25, SMART_MONEY=30, MOMENTUM_CHANGE=25
Expected Rotation=24.75
State=WARNING

## SM-01 Strong Inflow
FI=85, IT=80, LH=75, FC=80
Expected SmartMoney=80.25
State=STRONG_INFLOW

## SM-02 Outflow
FI=35, IT=30, LH=40, FC=35
Expected SmartMoney=35.00
State=OUTFLOW

## STAGE-01 Markup
Evidence:
Price > MA20, MA60, MA120
MA20 > MA60
MA20 slope > 0
M7=82
MHE=72
RS=strong
previous_stage=PRE_MARKUP
Expected stage_current=MARKUP

## STAGE-02 High Consolidation
Evidence:
Long-term structure bullish
Price near MA20/MA60
MHE=52
M7=58
previous_stage=HIGH_ROTATION
Expected stage_current=HIGH_CONSOLIDATION

## STAGE-03 Defensive Override
Evidence:
Price < MA60
M7=28
structural_failure=true
previous_stage=MARKUP
Expected:
stage_current=DEFENSIVE
stage_override=true
stage_override_reason != NULL

## TOP50-01
M7=80, MHE=70, Stage=85, Rotation=75, SM=80, Fundamental=70, RS=80
Expected RATE Composite=78.25

## SHORT30-01
M7=80, Rotation=75, SM=80, MHE=70, Stage=85, RS=80
Expected ShortScore=78.00

## LONG30-01
Fundamental=70, Stage=85, MHE=70, SM=80, RS=80, M7=80
Expected LongScore=76.50

## TIEBREAK-01
A and B Composite=80.00
A: SM=78, MHE=76, RS=80, Liquidity=90
B: SM=75, MHE=90, RS=90, Liquidity=95
Expected: A ranks above B due to Smart Money first tie-break.

## DETERMINISM-01
Spec=RATE-PLS-V1.1
Data Contract=RATE-DC-V1.0
Engine Version=X
Input Snapshot=SNAPSHOT-001

Run at least twice.
Expected identical:
M7, MHE, Stage, Rotation, Smart Money, Top50 order, Short Top30, Long Top30.
Any difference => DETERMINISTIC_VALIDATION=FAIL.

import copy
import unittest
from datetime import date, timedelta

from src.stage_history import build_stage_feature_histories
from src.stage_evidence import build_production_stage_evidence


def _fixture():
    symbols=[f'{1000+i}' for i in range(30)]
    dates=[(date(2026,1,1)+timedelta(days=i)).isoformat() for i in range(180)]
    stocks={}; benchmarks={}; inst={}; tdcc={}
    for n,symbol in enumerate(symbols):
        stocks[symbol]=[]
        for i,day in enumerate(dates):
            close=100.0+i*.01+(.3 if i%2==0 else -.3)
            stocks[symbol].append({'symbol':symbol,'trade_date':day,'open':close,'high':close,'low':close-.5,'close':close,'volume':10000,'turnover':10000*close,'source_timestamp':day+'T18:00:00Z'})
        benchmarks[symbol]=[{'trade_date':day,'close':100+i*.01+(.3 if i%2==0 else -.3),'source_timestamp':day+'T18:00:00Z'} for i,day in enumerate(dates)]
        inst[symbol]=[{'trading_date':day,'foreign_net_shares':1,'investment_trust_net_shares':1,'close':stocks[symbol][i]['close'],'turnover':stocks[symbol][i]['turnover'],'source_timestamp':day+'T18:00:00Z'} for i,day in enumerate(dates[:160])]
        tdcc[symbol]=[{'period_end':dates[i],'holder_pct_400':40.0,'source_timestamp':dates[i]+'T12:00:00Z'} for i in range(0,155,7)]
    return stocks,benchmarks,inst,tdcc,dates


class StageHistoryTests(unittest.TestCase):
    def test_same_date_replay_lineage_is_30_of_30(self):
        stocks,bench,inst,tdcc,dates=_fixture(); asof=dates[159]
        histories=build_stage_feature_histories(stocks,bench,inst,tdcc,as_of_date=asof,sessions=7)
        self.assertEqual(len(histories),30)
        accepted=0
        for symbol,history in histories.items():
            latest=history[-1]
            output=build_production_stage_evidence(symbol=symbol,stock_history=[r for r in stocks[symbol] if r['trade_date']<=asof],
                technical_record=latest['technical_record'],technical_features=latest['technical_features'],
                m7_score=latest['M7'],mhe_score=latest['MHE'],rotation_score=latest['Rotation'],
                prior_state=None,input_snapshot_id=None,feature_history=history)
            fields=output['stage_field_lineage']
            complete=all(fields.get(k,{}).get('source_session') and fields.get(k,{}).get('source_type') and fields.get(k,{}).get('calculation_definition') and fields.get(k,{}).get('spec_version') for k in output['stage_inputs'])
            accepted+=complete and output['calculation_status']=='PASS'
        self.assertEqual(accepted,30)

    def test_explicit_replay_calendar_must_be_common_and_is_used(self):
        stocks,bench,inst,tdcc,dates=_fixture(); asof=dates[159]
        selected=dates[153:160]
        histories=build_stage_feature_histories(stocks,bench,inst,tdcc,as_of_date=asof,sessions=7,
            session_dates=selected)
        self.assertEqual([r['trade_date'] for r in histories['1000']],selected)
        bench['1000']=[r for r in bench['1000'] if r['trade_date']!=selected[0]]
        with self.assertRaisesRegex(ValueError,'STAGE_HISTORY_SESSION_DATE_NOT_COMMON'):
            build_stage_feature_histories(stocks,bench,inst,tdcc,as_of_date=asof,sessions=7,
                session_dates=selected)

    def test_reconstructed_prior_stage_has_no_lookahead(self):
        stocks,bench,inst,tdcc,dates=_fixture(); asof=dates[159]
        one=build_stage_feature_histories(stocks,bench,inst,tdcc,as_of_date=asof,sessions=7)
        changed=copy.deepcopy(stocks); changed_b=copy.deepcopy(bench); changed_i=copy.deepcopy(inst); changed_t=copy.deepcopy(tdcc)
        for symbol in changed:
            for row in changed[symbol]:
                if row['trade_date']>asof: row.update(close=row['close']*3,low=row['low']*.1,volume=row['volume']*20,turnover=row['turnover']*60)
            for row in changed_b[symbol]:
                if row['trade_date']>asof: row['close']*=.1
            for row in changed_i[symbol]:
                if row['trading_date']>asof: row['foreign_net_shares']*=1000; row['investment_trust_net_shares']*=1000
            for row in changed_t[symbol]:
                if row['period_end']>asof: row['holder_pct_400']=99
        two=build_stage_feature_histories(changed,changed_b,changed_i,changed_t,as_of_date=asof,sessions=7)
        self.assertEqual(one,two)
        symbol='1000'; latest=one[symbol][-1]
        args={'symbol':symbol,'stock_history':[r for r in stocks[symbol] if r['trade_date']<=asof],
          'technical_record':latest['technical_record'],'technical_features':latest['technical_features'],
          'm7_score':latest['M7'],'mhe_score':latest['MHE'],'rotation_score':latest['Rotation'],
          'prior_state':None,'input_snapshot_id':None,'feature_history':one[symbol]}
        stage1=build_production_stage_evidence(**args)
        latest2=two[symbol][-1]
        args.update(technical_record=latest2['technical_record'],technical_features=latest2['technical_features'],
          m7_score=latest2['M7'],mhe_score=latest2['MHE'],rotation_score=latest2['Rotation'],feature_history=two[symbol])
        stage2=build_production_stage_evidence(**args)
        self.assertEqual((stage1['stage_current'],stage1['previous_stage'],stage1['stage_inputs']),
                         (stage2['stage_current'],stage2['previous_stage'],stage2['stage_inputs']))


if __name__=='__main__': unittest.main()

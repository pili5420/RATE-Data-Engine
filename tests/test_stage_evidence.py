import unittest
from src.stage_evidence import (build_stage_evidence, build_production_stage_evidence,
    rotation_deteriorated, rotation_class, STAGE_SPEC_GAP_FIELDS)


class StageEvidenceTests(unittest.TestCase):
    def base(self):
        return {'price':110,'ma20':100,'ma60':90,'ma120':80,'m7_score':80,'mhe_score':70,
            'relative_strength_strong':True,'ma20_slope_positive':True,'ma60_trend_non_negative':True,
            'price_above_ma60':True,'price_near_ma20_ma60':False,'long_term_bullish':True,
            'short_swing_mhe_improving':True,'m7_rising':True,'mhe_rising':True,
            'recent_low_no_longer_deteriorating':True,'rotation_deteriorated':False,
            'structural_failure':False,'evidence_state_mixed':False}
    def stage(self, updates=None, previous='CONSOLIDATION', prior=70):
        x=self.base(); x.update(updates or {})
        return build_stage_evidence(symbol='2330',stage_inputs=x,previous_stage=previous,prior_m7=prior,
            source_state_id='s0',input_snapshot_id='i0')

    def feature_history(self):
        rows=[]
        for i in range(7):
            rows.append({'trade_date':f'2026-09-{i+1:02d}','M7':70+i,'MHE':60+i,
                'Rotation':64+i/2,'RotationClass':'STRENGTHENING','close':110+i,
                'technical_features':{'RelativeStrength':65},
                'technical_record':{'MA20':100+i,'MA60':90+i,'MA120':80+i},
                'stock_low_values':[{'trade_date':f'2026-08-{j+1:02d}','low':80+j/10} for j in range(25+i)],
                'calculation_spec_version':'RATE-SPEC-20260919-004','source_type':'DERIVED_FROM_HISTORICAL_FEATURE_REPLAY'})
        return rows

    def test_original_classifier_cases_remain(self):
        self.assertEqual(self.stage()['stage_current'],'MARKUP')
        self.assertEqual(self.stage({'relative_strength_strong':False,'m7_score':70})['stage_current'],'PRE_MARKUP')
        self.assertEqual(self.stage({'price':90,'ma20':100,'ma60':100,'ma120':120,'m7_score':55})['stage_current'],'BASE_BUILDING')
        self.assertEqual(self.stage({'structural_failure':True},previous='MARKUP')['stage_current'],'DEFENSIVE')
        self.assertTrue(self.stage({'structural_failure':True},previous='MARKUP')['stage_override'])

    def test_stage_gap_closed_and_full_field_lineage_created(self):
        self.assertEqual(STAGE_SPEC_GAP_FIELDS,())
        result=self.stage()
        self.assertEqual(result['calculation_status'],'PASS')
        self.assertEqual(set(result['stage_field_lineage']),set(result['stage_inputs']))
        self.assertTrue(all({'value','source_session','source_type','calculation_definition','spec_version'} <= set(v) for v in result['stage_field_lineage'].values()))

    def test_price_near_boundary_uses_unrounded_values(self):
        from src.stage_evidence import _stage_inputs_from_history
        h=self.feature_history(); cur=h[-1]; old=h[-6]
        cur.update(close=103.0,technical_record={'MA20':100.0,'MA60':80.0,'MA120':70.0})
        inputs,_=_stage_inputs_from_history(cur,old,'X'); self.assertTrue(inputs['price_near_ma20_ma60'])
        cur['close']=103.0001
        inputs,_=_stage_inputs_from_history(cur,old,'X'); self.assertFalse(inputs['price_near_ma20_ma60'])

    def test_low20_equality_stable_and_lower_is_deteriorating(self):
        history=self.feature_history(); current=history[-1]; prior=history[-6]
        current['stock_low_values']=[{'trade_date':str(i),'low':10.0} for i in range(25)]
        # direct values are asserted through the same deterministic production formula
        from src.stage_evidence import _stage_inputs_from_history
        inputs, inter=_stage_inputs_from_history(current,prior,'X')
        self.assertEqual(inter['CURRENT_LOW20'],inter['PRIOR_LOW20'])
        self.assertTrue(inputs['recent_low_no_longer_deteriorating'])
        current['stock_low_values'][-5:]=[{'trade_date':str(i),'low':9.0} for i in range(5)]
        inputs,_=_stage_inputs_from_history(current,prior,'X')
        self.assertFalse(inputs['recent_low_no_longer_deteriorating'])

    def test_structural_failure_and_mixed_evidence_exact_rules(self):
        from src.stage_evidence import _stage_inputs_from_history
        history=self.feature_history(); current=history[-1]; prior=history[-6]
        current.update(close=70,technical_record={'MA20':80,'MA60':90,'MA120':100},M7=50,MHE=44)
        i,_=_stage_inputs_from_history(current,prior,'X')
        self.assertTrue(i['structural_failure']); self.assertTrue(i['evidence_state_mixed'])
        current['M7']=44; current['MHE']=60
        i,_=_stage_inputs_from_history(current,prior,'X'); self.assertTrue(i['evidence_state_mixed'])

    def test_rs_threshold_and_long_term_definition(self):
        from src.stage_evidence import _stage_inputs_from_history
        h=self.feature_history(); cur=h[-1]; old=h[-6]
        cur['technical_features']['RelativeStrength']=64.99
        i,_=_stage_inputs_from_history(cur,old,'X'); self.assertFalse(i['relative_strength_strong'])
        cur['technical_features']['RelativeStrength']=65
        i,_=_stage_inputs_from_history(cur,old,'X'); self.assertTrue(i['relative_strength_strong'])
        cur.update(close=95,technical_record={'MA20':90,'MA60':100,'MA120':95})
        i,_=_stage_inputs_from_history(cur,old,'X'); self.assertFalse(i['long_term_bullish'])

    def test_m7_mhe_lookback_strict_and_class_level_rotation(self):
        from src.stage_evidence import _stage_inputs_from_history
        h=self.feature_history(); cur=h[-1]; old=h[-6]
        cur['M7']=old['M7']; cur['MHE']=old['MHE']
        i,_=_stage_inputs_from_history(cur,old,'X')
        self.assertFalse(i['m7_rising']); self.assertFalse(i['mhe_rising']); self.assertFalse(i['short_swing_mhe_improving'])
        self.assertFalse(rotation_deteriorated('STRENGTHENING','STRENGTHENING'))
        self.assertTrue(rotation_deteriorated('FLAT','STRENGTHENING'))
        self.assertEqual(rotation_class(66),'STRENGTHENING')
        self.assertEqual(rotation_class(65),'STRENGTHENING')
        self.assertFalse(rotation_deteriorated(rotation_class(65),rotation_class(66)))
        self.assertTrue(rotation_deteriorated(rotation_class(64),rotation_class(65)))

    def test_ma60_t_vs_t5_and_long_bullish_are_exact(self):
        from src.stage_evidence import _stage_inputs_from_history
        h=self.feature_history(); cur=h[-1]; old=h[-6]
        cur['technical_record']['MA60']=old['technical_record']['MA60']
        i,_=_stage_inputs_from_history(cur,old,'X'); self.assertTrue(i['ma60_trend_non_negative'])
        cur['technical_record']['MA60']=old['technical_record']['MA60']-.01
        i,_=_stage_inputs_from_history(cur,old,'X'); self.assertFalse(i['ma60_trend_non_negative'])
        cur.update(close=110,technical_record={'MA20':100,'MA60':100,'MA120':100})
        i,_=_stage_inputs_from_history(cur,old,'X'); self.assertTrue(i['long_term_bullish'])

    def test_persistent_previous_stage_wins_after_first_bootstrap(self):
        history=self.feature_history(); low=[{'trade_date':f'2026-08-{i+1:02d}','low':80+i/10} for i in range(30)]
        stock=[{'trade_date':f'2026-08-{i+1:02d}','low':80+i/10,'close':100+i} for i in range(30)]
        for row in history: row['stock_low_values']=low
        latest=history[-1]
        out=build_production_stage_evidence(symbol='2330',stock_history=stock,technical_record=latest['technical_record'],
          technical_features=latest['technical_features'],m7_score=latest['M7'],mhe_score=latest['MHE'],rotation_score=latest['Rotation'],
          prior_state={'state_id':'persisted-state','symbols':{'2330':{'stage_current':'BASE_BUILDING'}}},input_snapshot_id=None,feature_history=history)
        self.assertEqual(out['previous_stage'],'BASE_BUILDING')
        self.assertEqual(out['prior_stage_source'],'DERIVED_FROM_PERSISTENT_PRIOR_STATE')

    def test_first_run_reconstructs_prior_stage_from_history_not_genesis_evidence(self):
        history=self.feature_history(); low=[{'trade_date':f'2026-08-{i+1:02d}','low':80+i/10} for i in range(30)]
        stock=[{'trade_date':f'2026-08-{i+1:02d}','low':80+i/10,'close':100+i} for i in range(30)]
        for row in history: row['stock_low_values']=low
        latest=history[-1]
        output=build_production_stage_evidence(symbol='2330',stock_history=stock,technical_record=latest['technical_record'],
            technical_features=latest['technical_features'],m7_score=latest['M7'],mhe_score=latest['MHE'],
            rotation_score=latest['Rotation'],prior_state=None,input_snapshot_id=None,feature_history=history)
        self.assertEqual(output['prior_stage_source'],'RECONSTRUCTED_FROM_AUTHORIZED_HISTORICAL_EVIDENCE')
        self.assertEqual(output['source_state_id'],'GENESIS_STATE_ID')
        self.assertEqual(output['input_snapshot_id'],None)
        self.assertIn(output['stage_current'],('MARKUP','PRE_MARKUP','STRENGTHENING','HIGH_ROTATION','HIGH_CONSOLIDATION','BASE_BUILDING','CONSOLIDATION','DEFENSIVE'))

    def test_first_run_fails_closed_without_feature_history(self):
        with self.assertRaisesRegex(ValueError,'STAGE_FEATURE_HISTORY'):
            build_production_stage_evidence(symbol='2330',stock_history=[],technical_record={},technical_features={},
              m7_score=50,mhe_score=50,rotation_score=50,prior_state=None,input_snapshot_id=None,feature_history=[])


if __name__=='__main__': unittest.main()

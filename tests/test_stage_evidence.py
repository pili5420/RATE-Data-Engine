import unittest
from src.stage_evidence import build_stage_evidence


class StageEvidenceTests(unittest.TestCase):
    def base(self):
        return {'price': 110, 'ma20': 100, 'ma60': 90, 'ma120': 80,
                'm7_score': 80, 'mhe_score': 70, 'relative_strength_strong': True,
                'ma20_slope_positive': True, 'ma60_trend_non_negative': True,
                'price_above_ma60': True, 'price_near_ma20_ma60': False,
                'long_term_bullish': True, 'short_swing_mhe_improving': True,
                'm7_rising': True, 'mhe_rising': True,
                'recent_low_no_longer_deteriorating': True,
                'rotation_deteriorated': False, 'structural_failure': False,
                'evidence_state_mixed': False}
    def stage(self, updates=None, previous='CONSOLIDATION', prior=70):
        x=self.base(); x.update(updates or {})
        return build_stage_evidence(symbol='2330', stage_inputs=x, previous_stage=previous, prior_m7=prior, source_state_id='s0', input_snapshot_id='i0')
    def test_base_building(self): self.assertEqual(self.stage({'price':90,'ma20':100,'ma60':100,'ma120':120,'m7_score':55,'mhe_score':50,'m7_rising':True})['stage_current'],'BASE_BUILDING')
    def test_strengthening(self): self.assertEqual(self.stage({'price':110,'ma120':120,'m7_score':70,'mhe_score':65})['stage_current'],'STRENGTHENING')
    def test_pre_markup(self): self.assertEqual(self.stage({'relative_strength_strong':False,'m7_score':70})['stage_current'],'PRE_MARKUP')
    def test_markup(self): self.assertEqual(self.stage()['stage_current'],'MARKUP')
    def test_high_rotation(self): self.assertEqual(self.stage({'price':100,'ma20':110,'prior_m7':90,'m7_score':70,'rotation_deteriorated':True})['stage_current'],'HIGH_ROTATION')
    def test_high_consolidation(self): self.assertEqual(self.stage({'price':100,'ma20':100,'ma60':95,'long_term_bullish':True,'price_near_ma20_ma60':True,'m7_score':55,'mhe_score':50,'mhe_improving':False})['stage_current'],'HIGH_CONSOLIDATION')
    def test_consolidation(self): self.assertEqual(self.stage({'m7_score':50,'mhe_score':40,'evidence_state_mixed':True,'ma20_slope_positive':False})['stage_current'],'CONSOLIDATION')
    def test_defensive(self): self.assertEqual(self.stage({'structural_failure':True}, previous='MARKUP')['stage_current'],'DEFENSIVE')
    def test_adjacent_transition(self): self.assertEqual(self.stage({'m7_score':70,'mhe_score':65}, previous='PRE_MARKUP')['previous_stage'],'PRE_MARKUP')
    def test_structural_override(self): self.assertTrue(self.stage({'structural_failure':True}, previous='MARKUP')['stage_override'])
    def test_mixed_evidence(self): self.assertEqual(self.stage({'m7_score':50,'evidence_state_mixed':True,'ma20_slope_positive':False})['stage_current'],'CONSOLIDATION')
    def test_rotation_deterioration(self): self.assertEqual(self.stage({'price':100,'ma20':110,'m7_score':70,'prior_m7':90,'rotation_deteriorated':True})['stage_current'],'HIGH_ROTATION')
    def test_lineage(self):
        out=self.stage(); self.assertEqual(out['calculation_status'],'PASS'); self.assertEqual(out['source_state_id'],'s0'); self.assertIn('stage_inputs',out); self.assertIn('stage_normalized_score',out)

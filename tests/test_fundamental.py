import unittest
from src.fundamental import calculate_fundamental
class FundamentalTests(unittest.TestCase):
 def test_score(self):
  rows=[{'symbol':str(i),'revenue_yoy':[i,i+1,i+2],'quarterly_eps':[i]*8} for i in range(20)]; out=calculate_fundamental(rows); self.assertEqual(len(out),20); self.assertIn('Fundamental',out[-1])
 def test_missing(self):
  rows=[{'symbol':str(i),'revenue_yoy':[1,2,3],'quarterly_eps':[1]*8} for i in range(19)]; self.assertRaises(ValueError,calculate_fundamental,rows)

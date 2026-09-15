import unittest
from schedule import delays

class Tests(unittest.TestCase):
    def test_count(self): self.assertEqual(delays(1,10,4),[1,2,4,8])
    def test_cap(self): self.assertEqual(delays(2,3,3),[2,3,3])
    def test_zero(self): self.assertEqual(delays(1,10,0),[])
    def test_negative(self):
        for args in [(-1,2,3),(1,-2,3),(1,2,-3)]:
            with self.assertRaises(ValueError): delays(*args)

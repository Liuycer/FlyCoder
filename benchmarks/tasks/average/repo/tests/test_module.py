import unittest
from module import solve

class Tests(unittest.TestCase):
    def test_mean(self): self.assertEqual(solve([2,4]),3)
    def test_negative(self): self.assertEqual(solve([-4,2]),-1)
    def test_empty(self):
        with self.assertRaises(ValueError): solve([])

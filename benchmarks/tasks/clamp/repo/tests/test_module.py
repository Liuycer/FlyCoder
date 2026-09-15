import unittest
from module import solve

class Tests(unittest.TestCase):
    def test_inside(self): self.assertEqual(solve(2,0,4),2)
    def test_edges(self):
        self.assertEqual(solve(-2,0,4),0)
        self.assertEqual(solve(7,0,4),4)
    def test_bounds(self):
        with self.assertRaises(ValueError): solve(2,4,0)

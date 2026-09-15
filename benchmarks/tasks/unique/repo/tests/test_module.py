import unittest
from module import solve

class Tests(unittest.TestCase):
    def test_order(self): self.assertEqual(solve([3,1,3,2]),[3,1,2])
    def test_empty(self): self.assertEqual(solve([]),[])
    def test_lists(self): self.assertEqual(solve([[1],[1],[2]]),[[1],[2]])

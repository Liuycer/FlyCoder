import unittest
from module import solve

class Tests(unittest.TestCase):
    def test_tail(self): self.assertEqual(solve([1,2,3],2),[[1,2],[3]])
    def test_empty(self): self.assertEqual(solve([],2),[])
    def test_size(self):
        with self.assertRaises(ValueError): solve([1],0)
        with self.assertRaises(ValueError): solve([1],-1)

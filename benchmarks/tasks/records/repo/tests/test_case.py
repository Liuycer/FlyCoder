import unittest
from parser import parse_rows

class Tests(unittest.TestCase):
    def test_spaces(self): self.assertEqual(parse_rows([" Alice , 2 "]),[("alice",2)])
    def test_blanks(self): self.assertEqual(parse_rows([" ","Bob,3"]),[("bob",3)])
    def test_order(self): self.assertEqual(parse_rows(["B,2","A,1"]),[("b",2),("a",1)])
    def test_bad(self):
        for row in [",1","a,1,x","a,no","a"]:
            with self.assertRaises(ValueError): parse_rows([row])

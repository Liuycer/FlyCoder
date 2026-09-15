import unittest
from decimal import Decimal
from invoice import invoice_total
from money import cents

class Tests(unittest.TestCase):
    def test_quantity(self): self.assertEqual(invoice_total([("2.25",3)],0),Decimal("6.75"))
    def test_tax(self): self.assertEqual(invoice_total([("10",2)],"0.1"),Decimal("22.00"))
    def test_half_cent(self): self.assertEqual(cents("1.005"),Decimal("1.01"))
    def test_empty(self): self.assertEqual(invoice_total([],0),Decimal("0.00"))

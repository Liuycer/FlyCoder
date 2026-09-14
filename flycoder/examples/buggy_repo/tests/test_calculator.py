import unittest

from calculator import average


class AverageTests(unittest.TestCase):
    def test_many(self):
        self.assertEqual(average([2, 4, 6]), 4)

    def test_single(self):
        self.assertEqual(average([7]), 7)

    def test_negative(self):
        self.assertEqual(average([-4, -2]), -3)

    def test_fraction(self):
        self.assertAlmostEqual(average([1, 2]), 1.5)

    def test_empty(self):
        with self.assertRaises(ValueError):
            average([])

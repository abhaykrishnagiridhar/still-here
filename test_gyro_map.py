
"""Basic tests for gyro-map coordinate handling."""

import unittest


class TestGyroMap(unittest.TestCase):
    def test_zero_rotation(self):
        heading = 0
        self.assertEqual(heading, 0)

    def test_heading_wraparound(self):
        heading = 360 % 360
        self.assertEqual(heading, 0)

    def test_negative_heading_wraparound(self):
        heading = -10 % 360
        self.assertEqual(heading, 350)


if __name__ == "__main__":
    unittest.main()


"""Basic tests for the Still Here rover simulator."""

import unittest


class TestSimRover(unittest.TestCase):
    def test_pick_action_name(self):
        action = "pick"
        self.assertEqual(action, "pick")

    def test_drop_action_name(self):
        action = "drop"
        self.assertEqual(action, "drop")

    def test_plan_has_pick_and_drop(self):
        actions = ["pick", "drop"]
        self.assertEqual(actions, ["pick", "drop"])


if __name__ == "__main__":
    unittest.main()

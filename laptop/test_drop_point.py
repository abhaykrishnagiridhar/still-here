"""Where picked blocks are put down must not be somewhere the camera will count as "in the way"."""

from operator_core import BLOCK_HEIGHT_MM, DROP_POINT_MM
from route import DEFAULT_CORRIDOR_MM
from sim_rover import BLOCK_SIZE, solve_pose

FLAT_SCALE_PX_PER_MM = 1.5  # what 40 mm blocks measure as in a 640 pixel wide picture
PICTURE_WIDTH_PX = 640
CLEARANCE_MM = 20.0  # spare room between a dropped block and the corridor's edge


def test_a_dropped_block_lands_outside_the_corridor_so_the_way_can_read_as_clear():
    _, y = DROP_POINT_MM

    # The route treats a block as in the way up to half a block plus half the corridor from the centre line.
    assert abs(y) >= DEFAULT_CORRIDOR_MM / 2 + BLOCK_SIZE / 2 + CLEARANCE_MM


def test_the_arm_can_reach_the_drop_point():
    x, y = DROP_POINT_MM

    assert solve_pose(x, y, BLOCK_HEIGHT_MM / 2, 0.0) is not None


def test_the_drop_point_is_inside_the_camera_picture():
    _, y = DROP_POINT_MM

    half_width_mm = PICTURE_WIDTH_PX / FLAT_SCALE_PX_PER_MM / 2
    assert abs(y) + BLOCK_SIZE / 2 < half_width_mm


# ---- several slots, so blocks are never dropped on top of one another ----------------------

from math import hypot

from demo_world import SIDE_BLOCK_XY
from operator_core import DROP_SLOTS_MM


def test_the_first_slot_is_the_drop_point():
    assert DROP_SLOTS_MM[0] == DROP_POINT_MM


def test_every_slot_is_outside_the_corridor_reachable_and_in_the_picture():
    half_width_mm = PICTURE_WIDTH_PX / FLAT_SCALE_PX_PER_MM / 2
    for x, y in DROP_SLOTS_MM:
        assert abs(y) >= DEFAULT_CORRIDOR_MM / 2 + BLOCK_SIZE / 2 + CLEARANCE_MM, (x, y)
        assert solve_pose(x, y, BLOCK_HEIGHT_MM / 2, 0.0) is not None, (x, y)
        assert abs(y) + BLOCK_SIZE / 2 < half_width_mm, (x, y)


def test_slots_are_far_enough_apart_for_blocks_to_sit_side_by_side():
    for i, (ax, ay) in enumerate(DROP_SLOTS_MM):
        for bx, by in DROP_SLOTS_MM[i + 1 :]:
            assert hypot(ax - bx, ay - by) >= BLOCK_SIZE + 10.0


def test_no_slot_is_on_top_of_the_block_left_at_the_side():
    sx, sy = SIDE_BLOCK_XY
    for x, y in DROP_SLOTS_MM:
        assert hypot(x - sx, y - sy) >= BLOCK_SIZE + 10.0

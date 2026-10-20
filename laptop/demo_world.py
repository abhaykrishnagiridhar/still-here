"""The scene of the autonomy demo, in one place, so the Blender twin and the laptop agree on it.

Coordinates are millimetres in the arm frame (origin at the arm base, x forward, y to the left), the same
frame docs/protocol.md uses. The top-down camera in Blender looks straight down with the rover at the bottom
middle of the picture, so the picture shows x from 0 to 320 mm and y from -213 to 213 mm at 1.5 pixels per
millimetre, which is what the camera code assumes for 40 mm blocks.

  * a wall of four blocks across the path to the survivor (ids 1 to 4): the planner must remove these
  * one block just off to the side (id 5): the planner leaves it, because by its own measurements the buggy
    clears it. The buggy is really a little wider than the planner was told (BUGGY_TRUE_HALF_WIDTH_MM), so it
    brushes this block on the way to the survivor. The rover reports that, the laptop learns from it, widens
    the corridor, and on the next run removes this block too. That is the demo's learning loop.
  * a fire pad off the path: the route has to keep clear of it
  * the survivor straight ahead, with a pulsing light
"""

from models import Block

BLOCK_MM = 40.0
FRAME_MM = (-10.0, -200.0, 320.0, 200.0)  # x min, y min, x max, y max: the area the planner may use

WALL_X = 150.0
WALL_Y = (-75.0, -25.0, 25.0, 75.0)
SIDE_BLOCK_XY = (110.0, 145.0)  # 5 mm beyond the planner's keep-clear line (140 mm from the centre line)

BLOCKS = tuple(Block(i, i, WALL_X, y, 1) for i, y in enumerate(WALL_Y, start=1)) + (
    Block(5, 5, SIDE_BLOCK_XY[0], SIDE_BLOCK_XY[1], 1),
)
PATH_BLOCK_IDS = (1, 2, 3, 4)
SIDE_BLOCK_IDS = (5,)

FIRE_MM = (230.0, -178.0, 28.0)  # x, y, half the pad's width
# How far from the pad the planner keeps blocks and the buggy. The project's default (100 mm) is for a real fire; for a
# 56 mm pad on a table it would fill the picture. The route keeps this plus half the corridor (165 mm) clear of the pad.
HEAT_RADIUS_MM = 45.0
SURVIVOR_MM = (300.0, 0.0)

# The hidden truth the planner is never told: half the buggy's real swept width (mm). The configured corridor
# is 240 mm wide (120 each side), so the planner thinks a block 140 mm or more off the centre line is safe.
# The buggy actually needs 135 mm each side, so the side block (edge 125 mm off the line) is brushed. After
# one learned widening of 10 mm each side the planner keeps 150 mm clear of centres, and removes it.
BUGGY_TRUE_HALF_WIDTH_MM = 135.0

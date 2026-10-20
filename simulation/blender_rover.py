"""Blender digital twin for the STILL HERE rover.

Start Blender with this file:
    blender --python simulation/blender_rover.py

It creates a rover, a 4-DOF arm and a small obstacle scene, then listens on UDP
127.0.0.1:8766 for packets produced by ``phone_bridge.py``.  The simulation
uses the same ``SimRover`` protocol and kinematics as the eventual firmware.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
LAPTOP = ROOT / "laptop"
SIMULATION = Path(__file__).resolve().parent
for path in (str(ROOT), str(LAPTOP), str(SIMULATION)):
    if path not in sys.path:
        sys.path.insert(0, path)

from demo_world import BLOCKS, BUGGY_TRUE_HALF_WIDTH_MM, FIRE_MM, SURVIVOR_MM
from models import Block
from sim_rover import ARM_BASE_HEIGHT, ARM_LINK_1, ARM_LINK_2, SimRover
from snapshot_protocol import parse_snapshot

MM = 0.001
SURVIVOR_XY = (SURVIVOR_MM[0] * MM, SURVIVOR_MM[1] * MM)  # metres: straight ahead, at the end of the path
PULSE_HZ = 1.5  # the survivor's light flashes this many times a second
OVERVIEW_BOARD_LOCATION = (0.25, -0.15, 0.15)  # where the board for the overview camera stands (metres)
OVERVIEW_BOARD_TURN = -1.15  # radians about the vertical: turns that board to face the overview camera
TOPDOWN_PX_PER_MM = 1.5  # what the vision code assumes for 40 mm blocks in a 640 pixel wide picture
UDP_HOST = "127.0.0.1"
UDP_PORT = int(os.environ.get("STILL_HERE_UDP_PORT", "8766"))
TIMER_SECONDS = 1 / 60
FRAMES_DIR = SIMULATION / "frames"  # snapshots are written here only; git ignores this folder

# Linear RGBA values, shared by solid viewport shading and rendered materials.
SCENE_COLORS = {
    "Rover white": (0.92, 0.94, 0.96, 1.0),
    "Arm green": (0.045, 0.42, 0.13, 1.0),
    "Wheel yellow": (1.0, 0.68, 0.015, 1.0),
    "Claw red": (0.8, 0.025, 0.035, 1.0),
    "Box black": (0.012, 0.015, 0.02, 1.0),
    "Ground grey": (0.19, 0.22, 0.26, 1.0),
    "Survivor skin": (0.80, 0.55, 0.40, 1.0),
    "Survivor shirt": (0.04, 0.50, 0.46, 1.0),
    "Survivor trousers": (0.05, 0.10, 0.38, 1.0),
    "Survivor hair": (0.06, 0.035, 0.02, 1.0),
    "Block red": (0.85, 0.02, 0.02, 1.0),
    "Fire pad": (1.0, 0.58, 0.0, 1.0),
    "Survivor light": (0.72, 0.88, 1.0, 1.0),
    "Corridor green": (0.05, 0.95, 0.25, 1.0),
    "Bump red": (1.0, 0.1, 0.7, 1.0),
    "Board yellow": (1.0, 0.92, 0.2, 1.0),
}


def apply_scene_colors() -> None:
    """Give each visible robot component a material for viewport and render."""
    materials = {}
    for name, color in SCENE_COLORS.items():
        material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        material.diffuse_color = color
        material.use_nodes = True
        shader = material.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Roughness'].default_value = 0.82
        materials[name] = material

    for obj in bpy.context.scene.objects:
        if obj.type == 'FONT':  # the run board
            obj.data.materials.clear()
            obj.data.materials.append(materials['Board yellow'])
            continue
        if obj.type != 'MESH':
            continue
        if obj.name.startswith('Overlay_Rail'):
            name = 'Corridor green'
        elif obj.name == 'Overlay_Bump':
            name = 'Bump red'
        elif obj.name.startswith('Block_'):
            name = 'Block red'
        elif obj.name == 'HeatPad':
            name = 'Fire pad'
        elif obj.name == 'SurvivorLight':
            name = 'Survivor light'
        elif obj.name.startswith('Wheel'):
            name = 'Wheel yellow'
        elif obj.name in ('LeftFinger', 'RightFinger'):
            name = 'Claw red'
        elif obj.name in ('ArmBase', 'UpperArm', 'Forearm'):
            name = 'Arm green'
        elif obj.name == 'RoverBody':
            name = 'Rover white'
        elif obj.name.startswith('Survivor_'):
            name = {'skin': 'Survivor skin', 'shirt': 'Survivor shirt', 'hair': 'Survivor hair'}.get(obj.name.split('_')[1], 'Survivor trousers')
        else:
            name = 'Ground grey'
        obj.data.materials.clear()
        obj.data.materials.append(materials[name])
        obj.color = SCENE_COLORS[name]


def metres(mm: float) -> float:
    return mm * MM


def make_cube(name: str, size: tuple[float, float, float], location: tuple[float, float, float], parent=None):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.parent = parent
    return obj


def make_sphere(name: str, radius: float, location: tuple[float, float, float], parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    return obj


def make_cylinder(name: str, radius: float, depth: float, location: tuple[float, float, float], parent=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    return obj


def add_rigid_body(obj, body_type: str, *, mass: float = 1.0, kinematic: bool = False) -> None:
    """Add a deliberately simple collision shape with predictable friction."""
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.rigidbody.object_add()
    obj.rigid_body.type = body_type
    obj.rigid_body.mass = mass
    obj.rigid_body.friction = 0.9
    obj.rigid_body.restitution = 0.05
    obj.rigid_body.collision_shape = "BOX" if obj.type == "MESH" else "CONVEX_HULL"
    obj.rigid_body.kinematic = kinematic
    obj.select_set(False)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


class BlenderTwin:
    def __init__(self) -> None:
        # The autonomy demo's world (laptop/demo_world.py): a wall of blocks across the path, one block off to the
        # side, a fire pad and the survivor. The laptop's planner works from what the camera sees of it.
        # The buggy is really a little wider than the planner is told (demo_world.BUGGY_TRUE_HALF_WIDTH_MM), so a
        # block the planner leaves beside the path can be brushed on the way to the survivor. That is what the
        # laptop learns from. The rover also knows where the survivor is, to drive towards.
        self.rover = SimRover(BLOCKS, survivor=SURVIVOR_MM, buggy_half_width_mm=BUGGY_TRUE_HALF_WIDTH_MM)
        self.peer = None  # where the operator server listens for the rover's messages
        self.sim_spots: dict[int, tuple[float, float, float]] = {}  # where the rover model last had each block (mm)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.socket.bind((UDP_HOST, UDP_PORT))
        self.last_clock = time.monotonic()
        self.drive_position = Vector((0.0, 0.0))
        self.held_block_id: int | None = None
        self.grab_constraint = None
        self.last_tip_location = Vector((0.0, 0.0, 0.0))
        bpy.context.scene.render.fps = 60
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = 1_000_000
        bpy.context.scene.frame_set(1)
        self.blocks: dict[int, bpy.types.Object] = {}
        self.create_scene()
        apply_scene_colors()
        self.update_objects()
        self.frame_viewports()

    def frame_viewports(self) -> None:
        """Show the centimetre-sized rover at a useful zoom on startup."""
        target = Vector((0.12, 0.0, 0.06))
        eye = Vector((0.65, -0.65, 0.48))
        rotation = (target - eye).to_track_quat('-Z', 'Y')
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    space = area.spaces.active
                    space.clip_start = 0.001
                    space.shading.type = 'SOLID'
                    space.shading.color_type = 'MATERIAL'
                    space.region_3d.view_location = target
                    space.region_3d.view_distance = 0.85
                    space.region_3d.view_rotation = rotation
                    space.region_3d.view_perspective = 'PERSP'

    def create_scene(self) -> None:
        clear_scene()
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.length_unit = "METERS"
        bpy.context.scene.world.color = (0.025, 0.035, 0.05)
        bpy.context.scene.render.film_transparent = False
        bpy.context.scene.view_settings.exposure = -1.25
        ground = make_cube("Ground", (1.5, 1.5, 0.02), (0.25, 0, -0.01))
        add_rigid_body(ground, "PASSIVE")

        self.body = make_cube("RoverBody", (0.24, 0.18, 0.07), (0, 0, 0.035))
        add_rigid_body(self.body, "PASSIVE", kinematic=True)
        self.base = make_cylinder("ArmBase", 0.045, 0.06, (0, 0, metres(ARM_BASE_HEIGHT)), self.body)
        self.shoulder = bpy.data.objects.new("ShoulderPivot", None)
        bpy.context.collection.objects.link(self.shoulder)
        self.shoulder.parent = self.base
        self.shoulder.location = (0, 0, metres(ARM_BASE_HEIGHT) - self.base.location.z)
        self.upper = make_cube("UpperArm", (metres(ARM_LINK_1), 0.032, 0.032), (metres(ARM_LINK_1 / 2), 0, 0), self.shoulder)
        self.elbow = bpy.data.objects.new("ElbowPivot", None)
        bpy.context.collection.objects.link(self.elbow)
        self.elbow.parent = self.shoulder
        self.elbow.location = (metres(ARM_LINK_1), 0, 0)
        self.forearm = make_cube("Forearm", (metres(ARM_LINK_2), 0.028, 0.028), (metres(ARM_LINK_2 / 2), 0, 0), self.elbow)
        self.gripper = bpy.data.objects.new("Gripper", None)
        bpy.context.collection.objects.link(self.gripper)
        self.gripper.parent = self.elbow
        self.gripper.location = (metres(ARM_LINK_2), 0, 0)
        self.left_finger = make_cube("LeftFinger", (0.045, 0.012, 0.014), (0.02, 0.026, 0), self.gripper)
        self.right_finger = make_cube("RightFinger", (0.045, 0.012, 0.014), (0.02, -0.026, 0), self.gripper)
        self.wheels = []
        for x in (-0.07, 0.07):
            for y in (-0.105, 0.105):
                wheel = make_cylinder("Wheel", 0.038, 0.025, (x, y, 0.035), self.body)
                wheel.rotation_euler[0] = 1.5708
                self.wheels.append(wheel)

        for world_block in self.rover.blocks.values():
            x, y = metres(world_block.block.x), metres(world_block.block.y)
            block = make_cube(
                f"Block_{world_block.block.id}",
                (0.04, 0.04, 0.04),
                (x, y, 0.02),
            )
            add_rigid_body(block, "ACTIVE", mass=0.07)
            self.blocks[world_block.block.id] = block

        self.create_survivor()
        self.create_heat_pad()
        self.create_overlay()
        bpy.ops.object.light_add(type="AREA", location=(0.28, -0.30, 0.55))
        bpy.context.object.data.energy = 90
        bpy.context.object.data.shape = "DISK"
        bpy.context.object.data.size = 0.45
        bpy.ops.object.camera_add(location=(-0.52, -0.34, 0.46))
        camera = bpy.context.object
        camera.rotation_euler = (Vector((0.20, -0.02, 0.03)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.lens = 27
        camera.name = "OverviewCamera"
        self.overview_camera = camera
        bpy.context.scene.camera = camera
        self.create_rover_camera()
        self.create_topdown_camera()
        self.rover_objects = [self.body, *self.body.children_recursive]

        # Bullet cannot constrain to an Empty, so use a tiny mesh target.
        self.gripper_anchor = make_cube("GripperPhysicsAnchor", (0.002, 0.002, 0.002), (0.0, 0.0, -1.0))
        self.gripper_anchor.hide_render = True
        add_rigid_body(self.gripper_anchor, "PASSIVE", kinematic=True)
        bpy.context.scene.rigidbody_world.substeps_per_frame = 10
        bpy.context.scene.rigidbody_world.solver_iterations = 20

    def create_survivor(self) -> None:
        """A doll-sized person (about 24 cm) standing beyond the blocks, with human proportions: a head one
        seventh of the height, a neck, shoulders, arms with hands, legs and feet. The person detector looks
        for this figure in pictures from the rover's camera."""
        x, y = SURVIVOR_XY
        self.survivor_parts = [
            make_cube("Survivor_trousers_footL", (0.034, 0.020, 0.010), (x + 0.006, y + 0.014, 0.005)),
            make_cube("Survivor_trousers_footR", (0.034, 0.020, 0.010), (x + 0.006, y - 0.014, 0.005)),
            make_cylinder("Survivor_trousers_legL", 0.0105, 0.105, (x, y + 0.014, 0.0625)),
            make_cylinder("Survivor_trousers_legR", 0.0105, 0.105, (x, y - 0.014, 0.0625)),
            make_cube("Survivor_shirt_torso", (0.034, 0.052, 0.085), (x, y, 0.1575)),
            make_cylinder("Survivor_shirt_armL", 0.0078, 0.080, (x, y + 0.034, 0.158)),
            make_cylinder("Survivor_shirt_armR", 0.0078, 0.080, (x, y - 0.034, 0.158)),
            make_sphere("Survivor_skin_handL", 0.0095, (x, y + 0.034, 0.112)),
            make_sphere("Survivor_skin_handR", 0.0095, (x, y - 0.034, 0.112)),
            make_cylinder("Survivor_skin_neck", 0.0075, 0.014, (x, y, 0.207)),
            make_sphere("Survivor_skin_head", 0.0165, (x, y, 0.2265)),
            make_sphere("Survivor_hair_cap", 0.0172, (x - 0.002, y, 0.2315)),
        ]

    def create_heat_pad(self) -> None:
        """A flat orange pad: the fire. The vision code finds it by colour and the route keeps clear of it."""
        x, y, radius = FIRE_MM
        make_cube("HeatPad", (2 * radius * MM, 2 * radius * MM, 0.004), (x * MM, y * MM, 0.002))

    def create_overlay(self) -> None:
        """What the autonomy demo writes over the table: two green rails for the corridor the planner keeps clear,
        a board with the run number and what was learned, and a red frame that marks a block the buggy brushed.
        The laptop's autopilot sends these (laptop/autopilot.py). They are drawn in the 3D view and in overview
        pictures, but hidden from the top-down camera, because the vision code reads that picture by colour."""
        length = 0.27
        self.rails = [
            make_cube(f"Overlay_Rail{side}", (length, 0.006, 0.004), (0.02 + length / 2, y, 0.002))
            for side, y in (("L", 0.12), ("R", -0.12))
        ]
        # A bright pink pad under the brushed block, a little bigger than it, so it shows as a frame round its base.
        self.bump_marker = make_cube("Overlay_Bump", (0.076, 0.076, 0.002), (0.0, 0.0, -1.0))
        self.bump_marker.hide_viewport = True
        curve = bpy.data.curves.new("OverlayBoardCurve", type="FONT")
        curve.body = "STILL HERE"
        curve.size = 0.034
        curve.align_x = "LEFT"
        self.board = bpy.data.objects.new("Overlay_Board", curve)
        bpy.context.collection.objects.link(self.board)
        # Standing up on the dark ground in front of the rover, facing the 3D view's starting position (which looks
        # from the front right), so bright text has a dark background. Outside the top-down camera's picture.
        self.board.location = (0.17, -0.45, 0.12)  # lines run downwards from here
        self.board.rotation_euler = (1.5708, 0.0, 0.68)
        # The overview camera (the one the recorded video uses) looks from the other side, so it gets its own board,
        # turned to face it. That board is only drawn in overview pictures, never in the 3D view or other cameras.
        self.board_overview = bpy.data.objects.new("Overlay_BoardOverview", curve.copy())
        bpy.context.collection.objects.link(self.board_overview)
        self.board_overview.location = OVERVIEW_BOARD_LOCATION
        self.board_overview.rotation_euler = (1.5708, 0.0, OVERVIEW_BOARD_TURN)
        self.board_overview.scale = (0.8, 0.8, 0.8)
        self.board_overview.hide_viewport = True
        self.overlay_objects = [*self.rails, self.bump_marker]
        for obj in (*self.overlay_objects, self.board, self.board_overview):
            obj.hide_render = True

    def apply_overlay(self, message: dict) -> None:
        """Show the laptop's board: the corridor width, the run, and any block that was brushed."""
        try:
            half = float(message["corridor_mm"]) * MM / 2
            text = str(message["text"])[:120]
        except (KeyError, TypeError, ValueError):
            return
        if not 0.0 < half < 0.5:
            return
        self.rails[0].location.y = half + 0.003
        self.rails[1].location.y = -half - 0.003
        for board in (self.board, self.board_overview):
            board.data.body = text.replace(" | ", "\n")
        brushed = message.get("brushed")
        block = None
        if isinstance(brushed, str) and brushed.startswith("block_") and brushed[6:].isdigit():
            block = self.blocks.get(int(brushed[6:]))
        if block is None:
            self.bump_marker.hide_viewport = True
        else:
            self.bump_marker.location = (block.location.x, block.location.y, 0.0015)
            self.bump_marker.hide_viewport = False

    def create_topdown_camera(self) -> None:
        """A camera straight above the table, as the vision code expects: the rover at the bottom middle of
        the picture, forward is up, left is left, and a 40 mm block is 60 pixels wide in a 640 pixel picture.
        It looks at the table only: the rover is hidden from it, as the real camera would not see its own rover."""
        width_m = 640 / TOPDOWN_PX_PER_MM * MM
        height_m = 480 / TOPDOWN_PX_PER_MM * MM
        bpy.ops.object.camera_add(location=(height_m / 2, 0.0, 1.0), rotation=(0.0, 0.0, -1.5707963))
        camera = bpy.context.object
        camera.name = "TopDownCamera"
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = width_m
        self.topdown_camera = camera
        # The survivor's light sits above the figure's head and flashes while the topdown camera takes pictures.
        self.survivor_light = make_sphere("SurvivorLight", 0.011, (SURVIVOR_XY[0], SURVIVOR_XY[1], 0.27))

    def create_rover_camera(self) -> None:
        """The camera on the rover's front, looking forward and slightly down, as the real one does."""
        location = Vector((0.13, 0.0, 0.11))
        bpy.ops.object.camera_add(location=location)
        camera = bpy.context.object
        camera.name = "RoverCamera"
        camera.data.lens = 24
        camera.rotation_euler = (location + Vector((1.0, 0.0, -0.10)) - location).to_track_quat('-Z', 'Y').to_euler()
        camera.parent = self.body
        self.rover_camera = camera

    def survivor_box(self, scene, camera, width: int, height: int):
        """Where the survivor is in the camera's picture, in pixels: the box around all of its parts, or
        None when it is not in view. The simulation knows this exactly, so it stands in for a detector
        that a cartoon figure cannot satisfy (a model trained on photographs does not see it as a person)."""
        bpy.context.view_layer.update()
        xs, ys = [], []
        for part in self.survivor_parts:
            for corner in part.bound_box:
                point = world_to_camera_view(scene, camera, part.matrix_world @ Vector(corner))
                if point.z <= 0:
                    return None  # behind the camera
                xs.append(point.x * width)
                ys.append((1.0 - point.y) * height)
        x0, x1 = max(min(xs), 0.0), min(max(xs), float(width))
        y0, y1 = max(min(ys), 0.0), min(max(ys), float(height))
        if x1 <= x0 or y1 <= y0:
            return None
        return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}

    def render_snapshot(self, path, camera_name: str = "rover", width: int = 640, height: int = 480) -> None:
        """Write the picture the named camera sees to `path` (a PNG), and beside it a .json with where the survivor
        is in the picture. Uses the fast Workbench engine, which shows the same material colours as the viewport."""
        scene = bpy.context.scene
        cameras = {"rover": self.rover_camera, "overview": self.overview_camera, "topdown": self.topdown_camera}
        camera = cameras[camera_name]
        saved = (scene.camera, scene.render.engine, scene.render.filepath, scene.render.resolution_x,
                 scene.render.resolution_y, scene.render.resolution_percentage, scene.view_settings.exposure,
                 tuple(scene.world.color), scene.view_settings.view_transform, scene.view_settings.look,
                 scene.display.render_aa, scene.render.image_settings.compression)
        hidden = []
        try:
            scene.camera = camera
            scene.render.engine = "BLENDER_WORKBENCH"
            # Flat light keeps colours true for the top-down camera, which the vision code reads by colour.
            scene.display.shading.light = "FLAT" if camera_name == "topdown" else "STUDIO"
            scene.display.shading.color_type = "MATERIAL"
            scene.view_settings.exposure = 0.0
            scene.view_settings.view_transform = "Standard"  # the default tone mapping washes colours out
            scene.view_settings.look = "None"
            scene.world.color = (0.42, 0.46, 0.52)
            scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = width, height, 100
            scene.render.image_settings.file_format = "PNG"
            scene.render.filepath = str(path)
            for obj in self.overlay_objects:  # the rails and marker are for people; the vision code must not see them
                hidden.append((obj, obj.hide_render))
                obj.hide_render = camera_name == "topdown"
            if camera_name == "overview":  # the board that faces this camera
                hidden.append((self.board_overview, self.board_overview.hide_render))
                self.board_overview.hide_render = False
                self.board_overview.hide_viewport = False
            if camera_name == "topdown":
                # The vision code reads this picture by colour, so smooth edges and small files are not needed. Without
                # them a render takes about 40 ms instead of 215, which gives the camera the frame rate it expects.
                scene.display.render_aa = "OFF"
                scene.render.image_settings.compression = 0
                for obj in self.rover_objects:
                    hidden.append((obj, obj.hide_render))
                    obj.hide_render = True
                self.survivor_light.hide_render = int(time.monotonic() * 2 * PULSE_HZ) % 2 != 0
            else:
                scene.display.render_aa = "FXAA"  # smooth enough to look at, and much cheaper than full anti-aliasing
                self.survivor_light.hide_render = False
            bpy.ops.render.render(write_still=True)
            # Written after the picture, so a program that waits for this file finds the picture too.
            truth = {"camera": camera_name, "width": width, "height": height,
                     "survivor_box": self.survivor_box(scene, camera, width, height)}
            Path(path).with_suffix(".json").write_text(json.dumps(truth), encoding="utf-8")
        finally:
            for obj, was_hidden in hidden:
                obj.hide_render = was_hidden
            self.board_overview.hide_viewport = True
            self.survivor_light.hide_render = False
            (scene.camera, scene.render.engine, scene.render.filepath, scene.render.resolution_x,
             scene.render.resolution_y, scene.render.resolution_percentage, scene.view_settings.exposure,
             scene.world.color, scene.view_settings.view_transform, scene.view_settings.look,
             scene.display.render_aa, scene.render.image_settings.compression) = saved

    def start_lift_showcase(self) -> None:
        """Run one visible pick-and-lift sequence whenever the scene opens."""
        self.rover.handle(
            {
                "type": "plan",
                "plan_id": 1,
                "steps": [{"id": 1, "action": "pick", "x": 145, "y": 0, "z": 20}],
            }
        )
        self.rover.handle({"type": "plan_start", "plan_id": 1})

    def constrain_to_gripper(self, block_id: int) -> None:
        """Attach an active box to the moving gripper with a Bullet constraint."""
        if self.held_block_id == block_id:
            return
        self.release_gripper()
        box = self.blocks[block_id]
        constraint = bpy.data.objects.new("GripperHoldConstraint", None)
        bpy.context.collection.objects.link(constraint)
        constraint.location = self.gripper_anchor.location
        bpy.context.view_layer.objects.active = constraint
        constraint.select_set(True)
        bpy.ops.rigidbody.constraint_add()
        constraint.rigid_body_constraint.type = "FIXED"
        constraint.rigid_body_constraint.object1 = box
        constraint.rigid_body_constraint.object2 = self.gripper_anchor
        constraint.select_set(False)
        self.grab_constraint = constraint
        self.held_block_id = block_id

    def release_gripper(self) -> None:
        if self.grab_constraint is not None:
            bpy.data.objects.remove(self.grab_constraint, do_unlink=True)
        self.grab_constraint = None
        self.held_block_id = None

    def sync_gripper_physics(self, arm: dict, desired_carried: int | None) -> None:
        """Make manual phone gripper input and planned pick/drop both affect boxes."""
        bpy.context.view_layer.update()
        self.gripper_anchor.matrix_world = self.gripper.matrix_world
        if desired_carried is not None:
            self.constrain_to_gripper(desired_carried)
            return
        if arm["gripper"] >= 45.0:
            self.release_gripper()
            return
        if self.held_block_id is not None:
            return
        tip = self.gripper.matrix_world.translation
        if not self.blocks:
            return
        nearest_id = min(self.blocks, key=lambda block_id: (Vector(self.blocks[block_id].location) - tip).length_squared)
        if (Vector(self.blocks[nearest_id].location) - tip).length <= 0.065:
            self.constrain_to_gripper(nearest_id)

    def receive(self) -> None:
        while True:
            try:
                raw, address = self.socket.recvfrom(4096)
            except BlockingIOError:
                return
            except ConnectionResetError:
                continue  # Windows: an earlier answer reached nobody. The sender may simply have left.
            try:
                packet = json.loads(raw.decode("utf-8"))
                if packet.get("kind") == "command":
                    if packet["message"].get("type") == "overlay":
                        self.apply_overlay(packet["message"])
                    outputs = self.rover.handle(packet["message"])
                    if packet.get("reply") is True:
                        self.peer = address  # the operator server: tell it everything the rover says
                    self.forward(outputs)
                elif packet.get("kind") == "snapshot":
                    request = parse_snapshot(packet, FRAMES_DIR)
                    if request is not None:
                        request.path.parent.mkdir(parents=True, exist_ok=True)
                        self.render_snapshot(request.path, request.camera)
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
                pass

    def forward(self, messages) -> None:
        """Send what the rover said to the operator server, if one has introduced itself."""
        if self.peer is None:
            return
        for message in messages:
            try:
                self.socket.sendto(json.dumps({"kind": "rover", "message": message}).encode("utf-8"), self.peer)
            except OSError:
                self.peer = None  # it has gone; wait for the next one to say hello
                return

    def update_rover_position(self, rover: dict) -> None:
        """Position the rover on the single flat collision floor."""
        desired = Vector((metres(rover["x"]), metres(rover["y"])))
        movement = desired - self.drive_position
        self.drive_position = desired
        heading = rover["heading"]
        self.body.location = (
            self.drive_position.x,
            self.drive_position.y,
            0.003,
        )
        self.body.rotation_euler = (0.0, 0.0, heading)
        wheel_turn = movement.length / 0.038
        for wheel in self.wheels:
            wheel.rotation_euler[1] += wheel_turn

    def mirror_plan_blocks(self, state: dict) -> None:
        """Put each block where the rover model says it is. The model carries a picked block with the gripper
        and sets it down where it drops it, so the camera sees exactly what the laptop's plan did. A block the
        model has not moved is left alone. Moved blocks are animated (kinematic) so physics never fights this."""
        for entry in state["blocks"]:
            block_id = entry["id"]
            obj = self.blocks.get(block_id)
            if obj is None:
                continue
            spot = (round(entry["x"], 1), round(entry["y"], 1), round(entry["z"], 1))
            known = self.sim_spots.get(block_id)
            self.sim_spots[block_id] = spot
            if known is None or known == spot:
                continue  # first look, or it has not moved
            obj.rigid_body.kinematic = True
            obj.location = (metres(spot[0]), metres(spot[1]), metres(spot[2]))

    def update_objects(self) -> None:
        state = self.rover.snapshot()
        rover = state["rover"]
        self.update_rover_position(rover)
        arm = state["arm"]
        self.base.rotation_euler[2] = arm["base"] * 0.0174533
        self.shoulder.rotation_euler[1] = -arm["shoulder"] * 0.0174533
        self.elbow.rotation_euler[1] = -arm["elbow"] * 0.0174533
        spread = metres(8 + arm["gripper"] * 0.25)
        self.left_finger.location.y = spread
        self.right_finger.location.y = -spread
        self.mirror_plan_blocks(state)
        if self.rover.plan_running or self.rover.carrying is not None:
            self.release_gripper()  # a plan is in charge: the phone's grab-by-closeness must not also hold a block
        else:
            self.sync_gripper_physics(arm, None)

    def tick(self) -> float:
        now = time.monotonic()
        dt = min(now - self.last_clock, 0.1)
        self.last_clock = now
        self.receive()
        self.forward(self.rover.step(dt))
        self.update_objects()
        # Timers update transforms but do not advance Bullet by themselves.
        # Advancing one Blender frame makes dynamic boxes collide and fall.
        bpy.context.scene.frame_set(bpy.context.scene.frame_current + 1)
        return TIMER_SECONDS


TWIN = BlenderTwin()
bpy.app.timers.register(TWIN.tick, first_interval=TIMER_SECONDS, persistent=True)
print(f"STILL HERE digital twin ready: listening on UDP {UDP_HOST}:{UDP_PORT}")

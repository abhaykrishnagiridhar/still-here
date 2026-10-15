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
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
LAPTOP = ROOT / "laptop"
SIMULATION = Path(__file__).resolve().parent
for path in (str(ROOT), str(LAPTOP), str(SIMULATION)):
    if path not in sys.path:
        sys.path.insert(0, path)

from models import Block
from sim_rover import ARM_BASE_HEIGHT, ARM_LINK_1, ARM_LINK_2, SimRover

MM = 0.001
UDP_HOST = "127.0.0.1"
UDP_PORT = int(os.environ.get("STILL_HERE_UDP_PORT", "8766"))
TIMER_SECONDS = 1 / 60

# Linear RGBA values, shared by solid viewport shading and rendered materials.
SCENE_COLORS = {
    "Rover white": (0.92, 0.94, 0.96, 1.0),
    "Arm green": (0.045, 0.42, 0.13, 1.0),
    "Wheel yellow": (1.0, 0.68, 0.015, 1.0),
    "Claw red": (0.8, 0.025, 0.035, 1.0),
    "Box black": (0.012, 0.015, 0.02, 1.0),
    "Ground grey": (0.19, 0.22, 0.26, 1.0),
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
        if obj.type != 'MESH':
            continue
        if obj.name.startswith('Block_'):
            name = 'Box black'
        elif obj.name.startswith('Wheel'):
            name = 'Wheel yellow'
        elif obj.name in ('LeftFinger', 'RightFinger'):
            name = 'Claw red'
        elif obj.name in ('ArmBase', 'UpperArm', 'Forearm'):
            name = 'Arm green'
        elif obj.name == 'RoverBody':
            name = 'Rover white'
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
        # One block, positioned inside the arm's reachable work envelope.
        demo_blocks = (Block(1, 1, 145, 0, 1, "light"),)
        self.rover = SimRover(demo_blocks)
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
        self.start_lift_showcase()
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

        bpy.ops.object.light_add(type="AREA", location=(0.28, -0.30, 0.55))
        bpy.context.object.data.energy = 90
        bpy.context.object.data.shape = "DISK"
        bpy.context.object.data.size = 0.45
        bpy.ops.object.camera_add(location=(0.48, -0.50, 0.32))
        camera = bpy.context.object
        camera.rotation_euler = (Vector((0.10, 0.0, 0.10)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.lens = 48
        bpy.context.scene.camera = camera

        # Bullet cannot constrain to an Empty, so use a tiny mesh target.
        self.gripper_anchor = make_cube("GripperPhysicsAnchor", (0.002, 0.002, 0.002), (0.0, 0.0, -1.0))
        self.gripper_anchor.hide_render = True
        add_rigid_body(self.gripper_anchor, "PASSIVE", kinematic=True)
        bpy.context.scene.rigidbody_world.substeps_per_frame = 10
        bpy.context.scene.rigidbody_world.solver_iterations = 20

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
                raw, _address = self.socket.recvfrom(4096)
            except BlockingIOError:
                return
            try:
                packet = json.loads(raw.decode("utf-8"))
                if packet.get("kind") == "command":
                    self.rover.handle(packet["message"])
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
                pass

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
        desired_carried = next((block["id"] for block in state["blocks"] if block["carried"]), None)
        self.sync_gripper_physics(arm, desired_carried)

    def tick(self) -> float:
        now = time.monotonic()
        dt = min(now - self.last_clock, 0.1)
        self.last_clock = now
        self.receive()
        self.rover.step(dt)
        self.update_objects()
        # Timers update transforms but do not advance Bullet by themselves.
        # Advancing one Blender frame makes dynamic boxes collide and fall.
        bpy.context.scene.frame_set(bpy.context.scene.frame_current + 1)
        return TIMER_SECONDS


TWIN = BlenderTwin()
bpy.app.timers.register(TWIN.tick, first_interval=TIMER_SECONDS, persistent=True)
print(f"STILL HERE digital twin ready: listening on UDP {UDP_HOST}:{UDP_PORT}")

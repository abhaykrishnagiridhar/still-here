// Run with: node --test ui_logic.test.ts   (or: npm test)
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BUSY_PHASES,
  END_PHASES,
  clamp,
  driveFor,
  headlineFor,
  keyDirection,
  toDisplay,
  toFrame,
  toneFor,
} from "./ui_logic.ts";

test("clamp keeps a value inside its range", () => {
  assert.equal(clamp(5, 0, 3), 3);
  assert.equal(clamp(-5, 0, 3), 0);
  assert.equal(clamp(2, 0, 3), 2);
});

test("forward and back drive both wheels the same way", () => {
  assert.deepEqual(driveFor("forward", 0.5), { left: 0.5, right: 0.5 });
  assert.deepEqual(driveFor("back", 0.5), { left: -0.5, right: -0.5 });
});

test("turning spins on the spot, and a faster right wheel turns the rover left", () => {
  assert.deepEqual(driveFor("left", 1), { left: -1, right: 1 });
  assert.deepEqual(driveFor("right", 1), { left: 1, right: -1 });
});

test("a speed beyond full or below zero is held inside 0 to 1", () => {
  assert.deepEqual(driveFor("forward", 7), { left: 1, right: 1 });
  assert.deepEqual(driveFor("forward", -2), { left: 0, right: 0 });
});

test("the keyboard keys map to directions, in either case", () => {
  assert.equal(keyDirection("w"), "forward");
  assert.equal(keyDirection("W"), "forward");
  assert.equal(keyDirection("ArrowDown"), "back");
  assert.equal(keyDirection("a"), "left");
  assert.equal(keyDirection("ArrowRight"), "right");
  assert.equal(keyDirection(" "), null);
  assert.equal(keyDirection("x"), null);
});

test("every phase has its own headline and an unknown one falls back to scanning", () => {
  assert.equal(headlineFor("plan_ready", null), "Check the plan, then approve it.");
  assert.equal(headlineFor("running", null), "The rover is clearing the way.");
  assert.equal(headlineFor("verifying", null), "Checking the result.");
  assert.equal(headlineFor("mystery", null), "Looking at the scene.");
});

test("a finished run is only called clear when the camera confirmed it", () => {
  assert.equal(headlineFor("done", true), "The way is clear.");
  assert.equal(headlineFor("done", false), "The rover finished, but it is not confirmed.");
  assert.equal(headlineFor("done", null), "The rover finished, but it is not confirmed.");
});

test("tone is ok only when verified and warn for trouble", () => {
  assert.equal(toneFor("done", true, true, null), "ok");
  assert.equal(toneFor("done", true, false, null), "warn");
  assert.equal(toneFor("blocked", true, null, null), "warn");
  assert.equal(toneFor("running", false, null, null), "warn");
  assert.equal(toneFor("running", true, null, "camera lost"), "warn");
  assert.equal(toneFor("running", true, null, null), "");
});

test("a tap on the picture becomes a position in the camera's own pixels", () => {
  const box = { left: 100, top: 50, width: 320, height: 240 };
  assert.deepEqual(toFrame(260, 170, box, { w: 640, h: 480 }), { x: 320, y: 240 });
  assert.deepEqual(toFrame(100, 50, box, { w: 640, h: 480 }), { x: 0, y: 0 });
});

test("a marker position is scaled to the size the picture is shown at", () => {
  assert.deepEqual(toDisplay([320, 240], 640, 640), { left: 320, top: 240 });
  assert.deepEqual(toDisplay([320, 240], 320, 640), { left: 160, top: 120 });
});

test("busy and ended phases do not overlap", () => {
  assert.ok(BUSY_PHASES.every((phase) => !END_PHASES.includes(phase)));
  assert.ok(BUSY_PHASES.includes("verifying"));
});

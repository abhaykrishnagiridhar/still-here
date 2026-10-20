// Run with: node --test ui_logic.test.ts   (or: npm test)
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BUSY_PHASES,
  END_PHASES,
  DEFAULT_CAMERA_ADDRESS,
  DEFAULT_ROVER_ADDRESS,
  streamUrl,
  cleanAddress,
  clamp,
  episodeLine,
  driveCode,
  driveFor,
  driveSpeedValue,
  parseArmState,
  roverUrl,
  headlineFor,
  keyDirection,
  roverNotice,
  withNotice,
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

test("a connected rover needs no notice", () => {
  assert.equal(roverNotice(true, "ws://still-here.local:81", ""), null);
});

test("a rover that cannot be reached is named, and the reason is added when there is one", () => {
  const plain = roverNotice(false, "ws://still-here.local:81", "");
  assert.ok(plain?.includes("ws://still-here.local:81"));
  assert.ok(plain?.includes("Nothing can be sent"));
  assert.ok(roverNotice(false, "ws://x:81", "refused")?.endsWith("(refused)"));
});

test("a stopped run is explained before what is happening now", () => {
  assert.equal(withNotice(null, "2 blocks to remove."), "2 blocks to remove.");
  assert.equal(withNotice("The rover was stopped.", "2 blocks to remove."), "The rover was stopped. 2 blocks to remove.");
});

test("each drive button sends the letter the rover firmware expects", () => {
  assert.equal(driveCode("forward"), "F");
  assert.equal(driveCode("back"), "B");
  assert.equal(driveCode("left"), "L");
  assert.equal(driveCode("right"), "R");
  assert.equal(driveCode("forward-left"), "Q");
  assert.equal(driveCode("forward-right"), "E");
  assert.equal(driveCode("back-left"), "Z");
  assert.equal(driveCode("back-right"), "C");
});

test("the speed slider maps onto the rover's 100 to 255 range and never leaves it", () => {
  assert.equal(driveSpeedValue(10), 100);
  assert.equal(driveSpeedValue(100), 255);
  assert.equal(driveSpeedValue(55), 178);
  assert.equal(driveSpeedValue(0), 100);
  assert.equal(driveSpeedValue(500), 255);
});

test("an address is cleaned to host or host:port, and anything odd is refused", () => {
  assert.equal(cleanAddress(DEFAULT_ROVER_ADDRESS), "still-arm.local");
  assert.equal(cleanAddress(DEFAULT_CAMERA_ADDRESS), "still-here.local");
  assert.equal(cleanAddress("192.168.4.1"), "192.168.4.1");
  assert.equal(streamUrl("still-here.local"), "http://still-here.local/stream");
  assert.equal(cleanAddress("  http://192.168.4.1/  "), "192.168.4.1");
  assert.equal(cleanAddress("rover.local:80"), "rover.local:80");
  assert.equal(cleanAddress(""), null);
  assert.equal(cleanAddress("192.168.4.1/drive?d=F"), "192.168.4.1");
  assert.equal(cleanAddress("a b"), null);
  assert.equal(cleanAddress("evil.com@192.168.4.1"), null);
  assert.equal(cleanAddress("-bad"), null);
});

test("rover URLs carry their settings in the query and escape them", () => {
  assert.equal(roverUrl("192.168.4.1", "/stop"), "http://192.168.4.1/stop");
  assert.equal(roverUrl("192.168.4.1", "/drive", { d: "F", v: 170 }), "http://192.168.4.1/drive?d=F&v=170");
  assert.equal(roverUrl("x", "/servo", { a: "1&2" }), "http://x/servo?a=1%262");
});

test("the rover's state is read only when it has five joints of numbers", () => {
  const good = { a: [90, 90, 90, 90, 90], min: [0, 30, 20, 20, 30], max: [180, 150, 160, 160, 110] };
  assert.deepEqual(parseArmState(good), good);
  assert.equal(parseArmState({ ...good, a: [90, 90, 90, 90] }), null);
  assert.equal(parseArmState({ ...good, min: [0, 30, 20, 20, "x"] }), null);
  assert.equal(parseArmState({ a: good.a }), null);
  assert.equal(parseArmState(null), null);
  assert.equal(parseArmState("ok"), null);
});

test("a run that brushed a block says which one and how wide the next corridor is", () => {
  const line = episodeLine({ number: 1, moved: 4, outcome: "bumped", brushed: "block_5", corridor_mm: 240, next_corridor_mm: 260 });
  assert.equal(line.left, "Run 1: moved 4 blocks");
  assert.equal(line.right, "brushed block_5, next corridor 260 mm");
  assert.equal(line.tone, "warn");
});

test("a clean run says so and shows the corridor it used", () => {
  const line = episodeLine({ number: 2, moved: 5, outcome: "clean", brushed: null, corridor_mm: 260, next_corridor_mm: 260 });
  assert.equal(line.left, "Run 2: moved 5 blocks");
  assert.equal(line.right, "clean, corridor 260 mm");
  assert.equal(line.tone, "ok");
});

test("one block is not plural", () => {
  assert.equal(episodeLine({ number: 1, moved: 1, outcome: "clean", brushed: null, corridor_mm: 240, next_corridor_mm: 240 }).left, "Run 1: moved 1 block");
});

test("a run the camera could not confirm is not called clean", () => {
  const line = episodeLine({ number: 3, moved: 4, outcome: "unverified", brushed: null, corridor_mm: 240, next_corridor_mm: 240 });
  assert.equal(line.right, "the camera could not confirm the way is clear");
  assert.equal(line.tone, "warn");
});

test("a bump with no block named still reads sensibly", () => {
  const line = episodeLine({ number: 1, moved: 4, outcome: "bumped", brushed: null, corridor_mm: 240, next_corridor_mm: 250 });
  assert.equal(line.right, "brushed a block, next corridor 250 mm");
});


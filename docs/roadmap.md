# Where STILL HERE could go: fire and rescue

This is the direction we want to grow the project in after the hackathon. It is an aim, not a finished plan, and nothing in it has been agreed with anyone.

## Why this field

The hackathon task is a small, safe stand-in for a real problem: reaching a trapped person without bringing more of the structure down on them or on the people sent in. Fire and rescue crews face this after building collapses, in burning or smoke-filled spaces, and wherever debris has to be moved by hand.

What STILL HERE already does is the part that matters most there: it looks at the scene, works out which pieces are safe to move and which are holding something up, shows that plan to a person, and only moves what the person approves. We want to turn that idea into a tool that lets a crew do more of the risky first look and clearing from a distance, so that fewer people have to go in.

## Where we are today

- A small wheeled rover with a hobby-servo arm, designed for 40 mm blocks. It has not yet been tested on real blocks.
- Camera and marker based perception, a planner that leaves heavy and load-bearing blocks alone, a route search to the survivor, an operator page with approval, and a fact-first report.
- A basic heat check (a flame sensor, and a rule that blocks near a heat source are left in place).
- A software model of the rover and a phone-driven Blender simulation (`docs/phone-simulation.md`).

It has not been tested on real debris, in real heat, or with any fire or rescue organisation. It is a student prototype and must not be used in a real rescue.

## Stages we would like to work through

1. **Hackathon rover (now).** Prove the idea on blocks: pick the top one off a stack without disturbing the one below, clear a path, report honestly.
2. **A rover that can move real weight.** A stronger arm and gripper, a sturdier chassis and a bigger power system (see below).
3. **Sensing for harsh scenes.** Better heat, smoke and dust handling than a single flame sensor and a visible-light camera.
4. **Trials with people who do this work.** Ask crews what they need, test on training rubble, and change the design to fit, not the other way round.

## What would have to change

| Area | Today | What a rescue version needs |
|---|---|---|
| Arm and servos | MG995 and MG90S hobby servos, light blocks only | High-torque servos that can lift and hold real debris without stalling or stripping gears |
| Power | 2S battery pack, 6 V servo supply (`docs/power.md`) | A higher-voltage pack, larger current budget, protection, and a design for heat |
| Sensing | Visible-light camera, one flame sensor, DHT11, IR | Heat imaging, gas and smoke tolerance, dust-proofing |
| Body | Hobby chassis and wheels | A sealed, rugged body that can climb and survive knocks |
| Control link | Phone hotspot Wi-Fi | A link that works through rubble, and a safe stop when it is lost |
| Safety | Operator approval, stop button, plan shown first | Independent safeguards and a proper safety review before any use near people |

The rule that stays the same: a person approves the plan, the rover only does what was approved, and the report states facts first.

## Who we would like to talk to

- **Servo and motor makers.** We would like to talk to companies such as REEFS RC about high-power servos. For example, retailer listings describe the REEFS RC 1400 Smart as a 4S-rated (up to 16.8 V) brushless servo with steel gears and a metal heat-sink case, listed at about 1400 oz-in of torque at 16.8 V and about 90 g. These figures come from retailer listings and have not been checked against the maker's datasheet. That is far beyond the MG995 class we use now. We would like to learn what suits a rescue arm, how it behaves under repeated heavy loads and heat, and whether a partnership or sponsorship is possible. We would check the real datasheet before designing around any figure.
- **Fire and rescue organisations and training schools**, to tell us what is actually hard and let us test on realistic rubble.
- **University labs and robotics clubs**, for materials, heat-tolerant sensing and testing space.

Adopting a servo of that class is not a drop-in swap. It needs a 4S pack, a supply and wiring rated for the stall current, a stronger gripper and joints, and a new power test plan.

## What we will not claim

- That any company has agreed to work with us or supplies us today.
- That the rover has been used or tested in a fire or rescue.
- Any figure we have not measured or read from a datasheet.

## Next small steps

- Write down what the hackathon rover could not do, after the final run.
- Draft a one-page note for servo makers and rescue organisations: what we built, what we need, and what we would share back.
- Re-do the power design for a 4S pack and a high-torque servo on paper (`docs/power.md`) before buying anything.

#include <cstdlib>
#include <iostream>

#include "planner.hpp"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::cerr << "FAIL line " << __LINE__ << ": " #cond << std::endl;  \
            ++failures;                                                        \
        }                                                                      \
    } while (0)

static DetectedObject block(const std::string& id, int x, int y) {
    DetectedObject o;
    o.id = id;
    o.color = "red";
    o.x = x;
    o.y = y;
    return o;
}

static void planner_orders_top_of_image_first() {
    RescuePlanner planner;
    const PlanResult r = planner.generatePlan({block("low", 100, 300), block("high", 100, 50)});
    CHECK(r.order.size() == 2);
    CHECK(r.order[0].id == "high");
    CHECK(r.order[1].id == "low");
}

static void planner_breaks_ties_by_x() {
    RescuePlanner planner;
    const PlanResult r = planner.generatePlan({block("right", 300, 100), block("left", 50, 100)});
    CHECK(r.order[0].id == "left");
}

static void planner_leaves_load_bearing_with_reason() {
    RescuePlanner planner;
    DetectedObject heavy = block("heavy", 10, 10);
    heavy.load_bearing = true;
    const PlanResult r = planner.generatePlan({heavy, block("ok", 20, 20)});
    CHECK(r.order.size() == 1);
    CHECK(r.order[0].id == "ok");
    CHECK(r.left.size() == 1);
    CHECK(r.left[0].object.id == "heavy");
    CHECK(r.left[0].reason == "load-bearing");
}

static void planner_leaves_heat_zone_blocks() {
    RescuePlanner planner;
    DetectedObject hot = block("hot", 10, 10);
    hot.heat_zone = true;
    const PlanResult r = planner.generatePlan({hot});
    CHECK(r.order.empty());
    CHECK(r.left.size() == 1);
    CHECK(r.left[0].reason == "near a heat source");
}

static void planner_handles_empty_input() {
    RescuePlanner planner;
    const PlanResult r = planner.generatePlan({});
    CHECK(r.order.empty());
    CHECK(r.left.empty());
}

static void heat_zone_marks_only_nearby_blocks() {
    const std::vector<DetectedObject> blocks = {block("near", 105, 100), block("far", 400, 400)};
    const auto marked = applyHeatZones(blocks, {{100, 100}}, 50);
    CHECK(marked[0].heat_zone);
    CHECK(!marked[1].heat_zone);
}

static void heat_zone_does_not_change_the_input() {
    const std::vector<DetectedObject> blocks = {block("near", 100, 100)};
    const auto marked = applyHeatZones(blocks, {{100, 100}}, 50);
    CHECK(marked[0].heat_zone);
    CHECK(!blocks[0].heat_zone);
}

static void heat_zone_with_no_sources_changes_nothing() {
    const auto marked = applyHeatZones({block("a", 1, 1)}, {}, 50);
    CHECK(!marked[0].heat_zone);
}

static void heat_zone_then_planner_leaves_the_hot_block() {
    RescuePlanner planner;
    const auto marked =
        applyHeatZones({block("hot", 100, 100), block("cool", 500, 100)}, {{105, 100}}, 60);
    const PlanResult r = planner.generatePlan(marked);
    CHECK(r.order.size() == 1);
    CHECK(r.order[0].id == "cool");
    CHECK(r.left.size() == 1);
    CHECK(r.left[0].object.id == "hot");
}

static void tracker_confirms_only_after_min_hits() {
    Tracker t(60, 3, 10);
    CHECK(t.update({{100, 100}}).empty());
    CHECK(t.update({{101, 100}}).empty());
    const auto confirmed = t.update({{102, 101}});
    CHECK(confirmed.size() == 1);
}

static void tracker_keeps_ids_when_detection_order_changes() {
    Tracker t(60, 1, 10);
    const auto first = t.update({{100, 100}, {400, 400}});
    CHECK(first.size() == 2);
    int id_a = 0, id_b = 0;
    for (const auto& tr : first) (tr.pos.x == 100 ? id_a : id_b) = tr.id;

    const auto second = t.update({{402, 399}, {101, 101}});  // reversed order
    CHECK(second.size() == 2);
    for (const auto& tr : second) {
        if (tr.pos.x < 200) {
            CHECK(tr.id == id_a);
        } else {
            CHECK(tr.id == id_b);
        }
    }
}

static void tracker_gives_a_new_id_to_a_far_detection() {
    Tracker t(60, 1, 10);
    const auto first = t.update({{100, 100}});
    const auto second = t.update({{500, 500}});
    CHECK(first.size() == 1);
    CHECK(second.size() == 1);
    CHECK(first[0].id != second[0].id);
}

static void tracker_forgets_a_block_after_too_many_missed_frames() {
    Tracker t(60, 1, 2);
    const int old_id = t.update({{100, 100}})[0].id;
    t.update({});
    t.update({});
    t.update({});  // missed more than 2 frames, so the track is dropped
    const auto back = t.update({{100, 100}});
    CHECK(back.size() == 1);
    CHECK(back[0].id != old_id);
}

static void tracker_does_not_confirm_a_flickering_block() {
    Tracker t(60, 3, 10);
    CHECK(t.update({{100, 100}}).empty());  // seen once
    CHECK(t.update({}).empty());            // missed
    CHECK(t.update({{100, 100}}).empty());  // seen twice in total, still below 3
}

int main() {
    planner_orders_top_of_image_first();
    planner_breaks_ties_by_x();
    planner_leaves_load_bearing_with_reason();
    planner_leaves_heat_zone_blocks();
    planner_handles_empty_input();
    heat_zone_marks_only_nearby_blocks();
    heat_zone_does_not_change_the_input();
    heat_zone_with_no_sources_changes_nothing();
    heat_zone_then_planner_leaves_the_hot_block();
    tracker_confirms_only_after_min_hits();
    tracker_keeps_ids_when_detection_order_changes();
    tracker_gives_a_new_id_to_a_far_detection();
    tracker_forgets_a_block_after_too_many_missed_frames();
    tracker_does_not_confirm_a_flickering_block();

    if (failures == 0) {
        std::cout << "all tests passed" << std::endl;
        return EXIT_SUCCESS;
    }
    std::cout << failures << " check(s) failed" << std::endl;
    return EXIT_FAILURE;
}

#pragma once

// Planning and tracking logic with no OpenCV in it, so it can be tested on its own.

#include <algorithm>
#include <string>
#include <vector>

struct Point2 {
    int x = 0;
    int y = 0;
};

struct DetectedObject {
    std::string id;
    std::string color;
    int x = 0;
    int y = 0;
    bool load_bearing = false;
    bool heat_zone = false;
};

struct LeftInPlace {
    DetectedObject object;
    std::string reason;
};

struct PlanResult {
    std::vector<DetectedObject> order;  // pick order: top of the image first
    std::vector<LeftInPlace> left;      // blocks the planner will not touch, and why
};

// Returns a copy of the blocks with heat_zone set on every block that sits within
// radius_px of any heat source. The input is not modified.
inline std::vector<DetectedObject> applyHeatZones(std::vector<DetectedObject> blocks,
                                                  const std::vector<Point2>& heat_sources,
                                                  int radius_px) {
    const long long radius_sq = static_cast<long long>(radius_px) * radius_px;
    for (auto& block : blocks) {
        for (const auto& heat : heat_sources) {
            const long long dx = block.x - heat.x;
            const long long dy = block.y - heat.y;
            if (dx * dx + dy * dy <= radius_sq) {
                block.heat_zone = true;
                break;
            }
        }
    }
    return blocks;
}

class RescuePlanner {
public:
    PlanResult generatePlan(const std::vector<DetectedObject>& objects) const {
        PlanResult result;

        for (const auto& obj : objects) {
            if (obj.load_bearing) {
                result.left.push_back({obj, "load-bearing"});
            } else if (obj.heat_zone) {
                result.left.push_back({obj, "near a heat source"});
            } else {
                result.order.push_back(obj);
            }
        }

        // Top of the image first (smaller y), with x as the tie-breaker.
        std::sort(result.order.begin(), result.order.end(),
                  [](const DetectedObject& a, const DetectedObject& b) {
                      if (a.y == b.y) return a.x < b.x;
                      return a.y < b.y;
                  });

        return result;
    }
};

// Gives each block a stable id across frames, and only reports a block once it has
// been seen in several frames in a row, so one flickering detection is ignored.
class Tracker {
public:
    struct Track {
        int id = 0;
        Point2 pos;
        int hits = 0;
        int missed = 0;
    };

    explicit Tracker(int max_distance_px = 60, int min_hits = 3, int max_missed = 10)
        : max_distance_px_(max_distance_px), min_hits_(min_hits), max_missed_(max_missed) {}

    // Feed the block centres seen in this frame. Returns the confirmed tracks that
    // were matched in this frame.
    std::vector<Track> update(const std::vector<Point2>& detections) {
        const long long max_sq = static_cast<long long>(max_distance_px_) * max_distance_px_;

        struct Pair {
            long long dist_sq;
            size_t track;
            size_t detection;
        };
        std::vector<Pair> pairs;
        for (size_t t = 0; t < tracks_.size(); ++t) {
            for (size_t d = 0; d < detections.size(); ++d) {
                const long long dx = tracks_[t].pos.x - detections[d].x;
                const long long dy = tracks_[t].pos.y - detections[d].y;
                const long long dist_sq = dx * dx + dy * dy;
                if (dist_sq <= max_sq) pairs.push_back({dist_sq, t, d});
            }
        }
        // Closest pairs win, so the result does not depend on the order of detections.
        std::sort(pairs.begin(), pairs.end(),
                  [](const Pair& a, const Pair& b) { return a.dist_sq < b.dist_sq; });

        std::vector<bool> track_used(tracks_.size(), false);
        std::vector<bool> detection_used(detections.size(), false);
        for (const auto& p : pairs) {
            if (track_used[p.track] || detection_used[p.detection]) continue;
            track_used[p.track] = true;
            detection_used[p.detection] = true;
            tracks_[p.track].pos = detections[p.detection];
            tracks_[p.track].hits += 1;
            tracks_[p.track].missed = 0;
        }

        for (size_t t = 0; t < tracks_.size(); ++t) {
            if (!track_used[t]) tracks_[t].missed += 1;
        }
        tracks_.erase(std::remove_if(tracks_.begin(), tracks_.end(),
                                     [this](const Track& t) { return t.missed > max_missed_; }),
                      tracks_.end());

        for (size_t d = 0; d < detections.size(); ++d) {
            if (detection_used[d]) continue;
            Track fresh;
            fresh.id = next_id_++;
            fresh.pos = detections[d];
            fresh.hits = 1;
            tracks_.push_back(fresh);
        }

        std::vector<Track> confirmed;
        for (const auto& t : tracks_) {
            if (t.hits >= min_hits_ && t.missed == 0) confirmed.push_back(t);
        }
        return confirmed;
    }

private:
    int max_distance_px_;
    int min_hits_;
    int max_missed_;
    int next_id_ = 1;
    std::vector<Track> tracks_;
};

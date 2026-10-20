#pragma once

// Pixels to millimetres, learned from the blocks themselves, and the rule for reopening a
// network camera that drops out. No OpenCV in here, so it can be tested on its own.
// These mirror scale.py and stream.py, which are the main version.

#include <algorithm>
#include <deque>
#include <stdexcept>
#include <vector>

constexpr double kBlockMm = 40.0;  // the blocks are 40 mm cubes

// A block can look somewhat smaller or bigger than average, because nearer ones look bigger.
constexpr double kMinBlockSizeRatio = 0.5;
constexpr double kMaxBlockSizeRatio = 1.8;

struct PxPoint {
    double x = 0.0;
    double y = 0.0;
};

struct MmPoint {
    double forward = 0.0;  // millimetres ahead of the rover
    double left = 0.0;     // millimetres to the rover's left
};

inline double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    const size_t n = values.size();
    return n % 2 == 1 ? values[n / 2] : (values[n / 2 - 1] + values[n / 2]) / 2.0;
}

// Keeps the typical on-screen side of a block over the last few frames and turns it into
// pixels per millimetre. 0 means "not known yet".
class ScaleEstimator {
public:
    explicit ScaleEstimator(double block_mm = kBlockMm, size_t window = 45, size_t min_samples = 5)
        : block_mm_(block_mm), window_(window), min_samples_(min_samples) {
        if (block_mm <= 0.0) throw std::invalid_argument("block_mm must be greater than zero");
        if (window < 1) throw std::invalid_argument("window must be at least 1");
        if (min_samples < 1) throw std::invalid_argument("min_samples must be at least 1");
    }

    // Feed the side length, in pixels, of every block seen in this frame.
    double update(const std::vector<double>& side_lengths_px) {
        if (!side_lengths_px.empty()) {
            samples_.push_back(median(side_lengths_px));
            if (samples_.size() > window_) samples_.pop_front();
        }
        return pxPerMm();
    }

    bool known() const { return samples_.size() >= min_samples_; }

    double pxPerMm() const {
        if (!known()) return 0.0;
        return median(std::vector<double>(samples_.begin(), samples_.end())) / block_mm_;
    }

private:
    double block_mm_;
    size_t window_;
    size_t min_samples_;
    std::deque<double> samples_;
};

// True if a blob this many pixels wide could be a block. Anything is allowed until the scale
// is known (px_per_mm is 0).
inline bool blockSizeOk(double side_px, double px_per_mm, double block_mm = kBlockMm,
                        double low = kMinBlockSizeRatio, double high = kMaxBlockSizeRatio) {
    if (px_per_mm <= 0.0) return true;
    const double expected = px_per_mm * block_mm;
    return low * expected <= side_px && side_px <= high * expected;
}

// Where a picture point is, in millimetres from the rover (the origin, at the bottom centre of
// the picture): forward is up the picture, left is left in the picture.
inline MmPoint toMm(PxPoint point, PxPoint origin, double px_per_mm) {
    if (px_per_mm <= 0.0) throw std::invalid_argument("px_per_mm must be greater than zero");
    return {(origin.y - point.y) / px_per_mm, (origin.x - point.x) / px_per_mm};
}

// Decides what to do about failed reads from a camera: keep waiting, reopen the stream, or
// give up. A good picture gives the retries back.
class ReconnectPolicy {
public:
    enum class Action { Keep, Reopen, GiveUp };

    ReconnectPolicy(int max_failed_reads, int max_reconnects)
        : max_failed_(max_failed_reads), max_reconnects_(max_reconnects) {}

    Action onFailedRead() {
        ++failed_;
        if (failed_ <= max_failed_) return Action::Keep;
        failed_ = 0;
        if (reconnects_ >= max_reconnects_) return Action::GiveUp;
        ++reconnects_;
        return Action::Reopen;
    }

    void onGoodFrame() {
        failed_ = 0;
        reconnects_ = 0;
    }

private:
    int max_failed_;
    int max_reconnects_;
    int failed_ = 0;
    int reconnects_ = 0;
};

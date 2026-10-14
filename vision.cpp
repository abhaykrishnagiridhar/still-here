// Rover vision and planning demo (C++).
//
// Usage:  vision.exe            webcam 0
//         vision.exe 1          webcam 1
//         vision.exe http://192.168.0.50/stream    the ESP32-CAM stream
//         vision.exe 0 snapshots    also saves the annotated frame to the existing folder
//                                   "snapshots" every time the plan changes
//
// Press ESC in the video window to quit.
//
// The blocks are 40 mm cubes. How big they look sets the scale, so positions are printed in
// millimetres from the rover (forward and left) and anything the wrong size for a block, such
// as a table edge, is ignored. A network camera that drops out is reopened by itself.
//
// This is the simple version. laptop/vision.py is the main one: it also finds the pulsing
// survivor light (so an amber survivor LED is NOT mistaken for fire there, but IS here) and
// plans the route to the survivor with route.py.

#include <opencv2/opencv.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <system_error>
#include <thread>
#include <vector>

#include "perception.hpp"
#include "planner.hpp"

namespace {

// Tunable values, all in one place.
constexpr double kMinBlockArea = 400.0;    // pixels; smaller red blobs are noise
constexpr double kMaxBlockArea = 30000.0;  // pixels; bigger red regions, such as a table
constexpr double kMaxBlockAspect = 2.0;    // a block is never this much longer than wide
constexpr double kMinFireArea = 800.0;     // pixels; smaller bright blobs are not a fire
constexpr double kHeatRadiusMm = 100.0;    // blocks closer than this to a fire are left alone
constexpr int kMaxFailedReads = 30;        // blank frames in a row before the stream is reopened
constexpr int kMaxReconnects = 5;          // times a dropped camera is reopened before giving up
constexpr char kWindowName[] = "Rover Vision Window";

struct Blob {
    Point2 centre;
    double side;  // pixels: the side of a square with the same area as the blob
};

cv::VideoCapture openSource(const std::string& source) {
    const bool is_index = !source.empty() &&
                          std::all_of(source.begin(), source.end(), [](unsigned char c) {
                              return std::isdigit(c) != 0;
                          });
    cv::VideoCapture capture;
    if (is_index) {
#ifdef _WIN32
        capture.open(std::stoi(source), cv::CAP_DSHOW);  // much faster start-up on Windows
#else
        capture.open(std::stoi(source));
#endif
    } else {
        capture.open(source);  // a stream URL such as the ESP32-CAM's /stream, or a video file
    }
    capture.set(cv::CAP_PROP_BUFFERSIZE, 1);  // keep only the newest picture, so a stream does not lag
    return capture;
}

// Removes speckles and fills small holes, so one block gives one blob.
cv::Mat cleanMask(const cv::Mat& mask) {
    cv::Mat cleaned;
    const cv::Mat kernel = cv::getStructuringElement(cv::MORPH_ELLIPSE, cv::Size(5, 5));
    cv::morphologyEx(mask, cleaned, cv::MORPH_OPEN, kernel);
    cv::morphologyEx(cleaned, cleaned, cv::MORPH_CLOSE, kernel);
    return cleaned;
}

cv::Mat redMask(const cv::Mat& hsv) {
    // Red sits at both ends of the hue range (0 to 180), so it needs two ranges.
    cv::Mat low, high, combined;
    cv::inRange(hsv, cv::Scalar(0, 120, 70), cv::Scalar(10, 255, 255), low);
    cv::inRange(hsv, cv::Scalar(170, 120, 70), cv::Scalar(180, 255, 255), high);
    cv::bitwise_or(low, high, combined);
    return cleanMask(combined);
}

cv::Mat fireMask(const cv::Mat& hsv) {
    // Bright orange to yellow only. The high brightness floor keeps wood, skin and cardboard
    // from counting as fire. Tune the three numbers for your lighting.
    cv::Mat mask;
    cv::inRange(hsv, cv::Scalar(15, 120, 230), cv::Scalar(35, 255, 255), mask);
    return cleanMask(mask);
}

// Every blob whose area is in range and whose shape is not too long and thin.
std::vector<Blob> findBlobs(const cv::Mat& mask, double min_area, double max_area,
                            double max_aspect) {
    std::vector<std::vector<cv::Point>> contours;
    cv::findContours(mask, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);

    std::vector<Blob> blobs;
    for (const auto& contour : contours) {
        const double area = cv::contourArea(contour);
        if (area < min_area || area > max_area) continue;
        const cv::Rect box = cv::boundingRect(contour);
        if (static_cast<double>(std::max(box.width, box.height)) /
                std::max(1, std::min(box.width, box.height)) > max_aspect) {
            continue;
        }
        const cv::Moments m = cv::moments(contour);
        if (m.m00 <= 0.0) continue;
        blobs.push_back({{static_cast<int>(m.m10 / m.m00), static_cast<int>(m.m01 / m.m00)},
                         std::sqrt(area)});
    }
    std::sort(blobs.begin(), blobs.end(), [](const Blob& a, const Blob& b) {
        return a.centre.x != b.centre.x ? a.centre.x < b.centre.x : a.centre.y < b.centre.y;
    });
    return blobs;
}

std::vector<Point2> centresOf(const std::vector<Blob>& blobs) {
    std::vector<Point2> centres;
    for (const auto& b : blobs) centres.push_back(b.centre);
    return centres;
}

std::string describePlan(const PlanResult& plan, PxPoint origin, double px_per_mm) {
    std::ostringstream out;
    if (plan.order.empty() && plan.left.empty()) out << "No blocks seen.\n";
    else if (plan.order.empty()) out << "No safe blocks to pick.\n";
    for (size_t i = 0; i < plan.order.size(); ++i) {
        const DetectedObject& b = plan.order[i];
        const MmPoint mm = toMm({static_cast<double>(b.x), static_cast<double>(b.y)}, origin, px_per_mm);
        out << "Pick " << (i + 1) << ": " << b.id << " at (" << std::lround(mm.forward) << ", "
            << std::lround(mm.left) << ") mm\n";
    }
    for (const auto& item : plan.left) {
        out << "Leave " << item.object.id << ": " << item.reason << "\n";
    }
    return out.str();
}

// Draws text with a dark outline so it stays readable on top of a block, and keeps it inside
// the frame so a block near the edge does not push its label out of view.
void drawLabel(cv::Mat& frame, const std::string& text, cv::Point anchor, const cv::Scalar& color) {
    const double scale = 0.5;
    int baseline = 0;
    const cv::Size size = cv::getTextSize(text, cv::FONT_HERSHEY_SIMPLEX, scale, 2, &baseline);
    const int x = std::max(5, std::min(anchor.x, frame.cols - size.width - 5));
    const int y = std::max(size.height + 5, anchor.y);
    cv::putText(frame, text, cv::Point(x, y), cv::FONT_HERSHEY_SIMPLEX, scale,
                cv::Scalar(0, 0, 0), 4);
    cv::putText(frame, text, cv::Point(x, y), cv::FONT_HERSHEY_SIMPLEX, scale, color, 2);
}

void drawOverlay(cv::Mat& frame, const PlanResult& plan, const std::vector<Point2>& heat_sources,
                 int heat_radius_px) {
    const cv::Scalar green(0, 255, 0);
    const cv::Scalar white(255, 255, 255);
    const cv::Scalar orange(0, 140, 255);

    for (const auto& heat : heat_sources) {
        cv::circle(frame, cv::Point(heat.x, heat.y), heat_radius_px, orange, 2);
    }
    for (size_t i = 0; i < plan.order.size(); ++i) {
        const DetectedObject& b = plan.order[i];
        cv::circle(frame, cv::Point(b.x, b.y), 6, green, -1);
        drawLabel(frame, std::to_string(i + 1) + " " + b.id, cv::Point(b.x - 15, b.y - 15), green);
    }
    for (const auto& item : plan.left) {
        const DetectedObject& b = item.object;
        cv::circle(frame, cv::Point(b.x, b.y), 6, white, -1);
        // Below the block, so it never lands on the label of a block that will be picked.
        drawLabel(frame, b.id + " (left: " + item.reason + ")", cv::Point(b.x - 15, b.y + 50), white);
    }
}

}  // namespace

int main(int argc, char** argv) {
    const std::string source = argc > 1 ? argv[1] : "0";
    const std::string snapshot_dir = argc > 2 ? argv[2] : "";  // empty means do not save
    std::error_code ignored;
    const bool is_file = std::filesystem::is_regular_file(source, ignored);

    cv::VideoCapture cap = openSource(source);
    ReconnectPolicy policy(kMaxFailedReads, is_file ? 0 : kMaxReconnects);  // a file is not reopened

    RescuePlanner planner;
    Tracker tracker;  // needs a block in 3 frames in a row before it is believed
    ScaleEstimator scale;
    std::string last_printed;
    int snapshot_count = 0;

    std::cout << "--- Rover vision and planning started (ESC to quit) ---" << std::endl;

    for (;;) {
        cv::Mat frame;
        if (!cap.isOpened() || !cap.read(frame) || frame.empty()) {
            const auto action = policy.onFailedRead();
            if (action == ReconnectPolicy::Action::GiveUp) {
                if (is_file) break;  // the end of a video file is not an error
                std::cerr << "Lost the video source and could not reconnect: " << source << std::endl;
                return EXIT_FAILURE;
            }
            if (action == ReconnectPolicy::Action::Reopen) {
                cap.release();
                std::this_thread::sleep_for(std::chrono::seconds(1));
                cap = openSource(source);
            }
            if (cv::waitKey(30) == 27) break;
            continue;
        }
        policy.onGoodFrame();

        const PxPoint origin{frame.cols / 2.0, static_cast<double>(frame.rows)};  // the rover

        cv::Mat blurred, hsv;
        cv::GaussianBlur(frame, blurred, cv::Size(5, 5), 0);
        cv::cvtColor(blurred, hsv, cv::COLOR_BGR2HSV);

        // The blocks are 40 mm cubes: how big they look sets the scale.
        const std::vector<Blob> blobs = findBlobs(redMask(hsv), kMinBlockArea, kMaxBlockArea, kMaxBlockAspect);
        std::vector<double> sides;
        for (const auto& b : blobs) sides.push_back(b.side);
        const double px_per_mm = scale.update(sides);

        if (px_per_mm <= 0.0) {
            cv::putText(frame, "Measuring the 40 mm blocks to set the scale...", cv::Point(10, 25),
                        cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(255, 255, 0), 2);
            cv::imshow(kWindowName, frame);
            if (cv::waitKey(1) == 27) break;
            continue;
        }

        // Blocks: red blobs of the right size, tracked over frames so each keeps the same id.
        std::vector<Blob> block_sized;
        for (const auto& b : blobs) {
            if (blockSizeOk(b.side, px_per_mm)) block_sized.push_back(b);
        }
        std::vector<DetectedObject> blocks;
        for (const auto& track : tracker.update(centresOf(block_sized))) {
            DetectedObject obj;
            obj.id = "block_" + std::to_string(track.id);
            obj.color = "red";
            obj.x = track.pos.x;
            obj.y = track.pos.y;
            obj.load_bearing = false;  // set this from a marker or a second colour when you have one
            blocks.push_back(obj);
        }

        // Heat: bright orange or yellow blobs. Blocks near one are left alone.
        const std::vector<Point2> heat_sources =
            centresOf(findBlobs(fireMask(hsv), kMinFireArea, 1e12, 1e12));
        const int heat_radius_px = static_cast<int>(std::lround(kHeatRadiusMm * px_per_mm));
        blocks = applyHeatZones(blocks, heat_sources, heat_radius_px);

        const PlanResult plan = planner.generatePlan(blocks);

        // Print only when the plan changes, so the terminal stays readable.
        const std::string text = describePlan(plan, origin, px_per_mm);
        const bool plan_changed = (text != last_printed);
        if (plan_changed) {
            std::cout << "=== PLAN CHANGED ===\n" << text << std::flush;
            last_printed = text;
        }

        drawOverlay(frame, plan, heat_sources, heat_radius_px);

        if (plan_changed && !snapshot_dir.empty()) {
            const std::string path =
                snapshot_dir + "/plan_" + std::to_string(++snapshot_count) + ".png";
            if (!cv::imwrite(path, frame)) {
                std::cerr << "Could not save " << path << " (does the folder exist?)" << std::endl;
            }
        }

        cv::imshow(kWindowName, frame);
        if (cv::waitKey(1) == 27) break;
    }

    cap.release();
    cv::destroyAllWindows();
    return EXIT_SUCCESS;
}

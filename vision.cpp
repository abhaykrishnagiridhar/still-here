// Rover vision and planning demo.
//
// Usage:  vision.exe            webcam 0
//         vision.exe 1          webcam 1
//         vision.exe http://192.168.0.50/stream    the ESP32-CAM stream
//
// Press ESC in the video window to quit.

#include <opencv2/opencv.hpp>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "planner.hpp"

namespace {

// Tunable values, all in one place.
constexpr double kMinBlockArea = 400.0;  // pixels; smaller red blobs are treated as noise
constexpr double kMinFireArea = 800.0;   // pixels; smaller bright blobs are not a fire
constexpr int kHeatRadiusPx = 120;       // blocks closer than this to a fire are left alone
constexpr int kMaxFailedReads = 30;      // blank frames in a row before giving up
constexpr char kWindowName[] = "Rover Vision Window";

cv::VideoCapture openSource(const std::string& source) {
    const bool is_index = !source.empty() &&
                          std::all_of(source.begin(), source.end(), [](unsigned char c) {
                              return std::isdigit(c) != 0;
                          });
    if (is_index) {
        const int index = std::stoi(source);
#ifdef _WIN32
        return cv::VideoCapture(index, cv::CAP_DSHOW);  // much faster start-up on Windows
#else
        return cv::VideoCapture(index);
#endif
    }
    return cv::VideoCapture(source);  // a stream URL such as the ESP32-CAM's /stream
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
    // Bright orange to yellow only. The high brightness floor keeps wood, skin and
    // cardboard from counting as fire. Tune the three numbers for your lighting.
    cv::Mat mask;
    cv::inRange(hsv, cv::Scalar(15, 120, 230), cv::Scalar(35, 255, 255), mask);
    return cleanMask(mask);
}

// Centres of every blob in the mask that is at least min_area pixels big.
std::vector<Point2> findBlobCentres(const cv::Mat& mask, double min_area) {
    std::vector<std::vector<cv::Point>> contours;
    cv::findContours(mask, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);

    std::vector<Point2> centres;
    for (const auto& contour : contours) {
        if (cv::contourArea(contour) < min_area) continue;
        const cv::Moments m = cv::moments(contour);
        if (m.m00 <= 0.0) continue;
        centres.push_back({static_cast<int>(m.m10 / m.m00), static_cast<int>(m.m01 / m.m00)});
    }
    return centres;
}

std::string describePlan(const PlanResult& plan) {
    std::ostringstream out;
    if (plan.order.empty()) out << "No safe blocks to pick.\n";
    for (size_t i = 0; i < plan.order.size(); ++i) {
        const DetectedObject& b = plan.order[i];
        out << "Pick " << (i + 1) << ": " << b.id << " at (" << b.x << ", " << b.y << ")\n";
    }
    for (const auto& item : plan.left) {
        out << "Leave " << item.object.id << ": " << item.reason << "\n";
    }
    return out.str();
}

void drawOverlay(cv::Mat& frame, const PlanResult& plan, const std::vector<Point2>& heat_sources) {
    const cv::Scalar green(0, 255, 0);
    const cv::Scalar red(0, 0, 255);
    const cv::Scalar orange(0, 140, 255);

    for (const auto& heat : heat_sources) {
        cv::circle(frame, cv::Point(heat.x, heat.y), kHeatRadiusPx, orange, 2);
    }
    for (size_t i = 0; i < plan.order.size(); ++i) {
        const DetectedObject& b = plan.order[i];
        cv::circle(frame, cv::Point(b.x, b.y), 6, green, -1);
        cv::putText(frame, std::to_string(i + 1) + " " + b.id, cv::Point(b.x - 15, b.y - 15),
                    cv::FONT_HERSHEY_SIMPLEX, 0.5, green, 2);
    }
    for (const auto& item : plan.left) {
        const DetectedObject& b = item.object;
        cv::circle(frame, cv::Point(b.x, b.y), 6, red, -1);
        cv::putText(frame, b.id + " (left: " + item.reason + ")", cv::Point(b.x - 15, b.y - 15),
                    cv::FONT_HERSHEY_SIMPLEX, 0.5, red, 2);
    }
}

}  // namespace

int main(int argc, char** argv) {
    const std::string source = argc > 1 ? argv[1] : "0";

    cv::VideoCapture cap = openSource(source);
    if (!cap.isOpened()) {
        std::cerr << "Could not open the video source: " << source << std::endl;
        return EXIT_FAILURE;
    }

    RescuePlanner planner;
    Tracker tracker;  // needs a block in 3 frames in a row before it is believed
    std::string last_printed;
    int failed_reads = 0;

    std::cout << "--- Rover vision and planning started (ESC to quit) ---" << std::endl;

    for (;;) {
        cv::Mat frame;
        if (!cap.read(frame) || frame.empty()) {
            if (++failed_reads > kMaxFailedReads) {
                std::cerr << "The video source stopped sending frames." << std::endl;
                break;
            }
            if (cv::waitKey(30) == 27) break;
            continue;
        }
        failed_reads = 0;

        cv::Mat blurred, hsv;
        cv::GaussianBlur(frame, blurred, cv::Size(5, 5), 0);
        cv::cvtColor(blurred, hsv, cv::COLOR_BGR2HSV);

        // Blocks: red blobs, tracked over frames so each keeps the same id.
        const std::vector<Point2> centres = findBlobCentres(redMask(hsv), kMinBlockArea);
        std::vector<DetectedObject> blocks;
        for (const auto& track : tracker.update(centres)) {
            DetectedObject obj;
            obj.id = "block_" + std::to_string(track.id);
            obj.color = "red";
            obj.x = track.pos.x;
            obj.y = track.pos.y;
            obj.load_bearing = false;  // set this from a marker or a second colour when you have one
            blocks.push_back(obj);
        }

        // Heat: bright orange or yellow blobs. Blocks near one are left alone.
        const std::vector<Point2> heat_sources = findBlobCentres(fireMask(hsv), kMinFireArea);
        blocks = applyHeatZones(blocks, heat_sources, kHeatRadiusPx);

        const PlanResult plan = planner.generatePlan(blocks);

        // Print only when the plan changes, so the terminal stays readable.
        const std::string text = describePlan(plan);
        if (text != last_printed) {
            std::cout << "=== PLAN CHANGED ===\n" << text << std::flush;
            last_printed = text;
        }

        drawOverlay(frame, plan, heat_sources);
        cv::imshow(kWindowName, frame);
        if (cv::waitKey(1) == 27) break;
    }

    cap.release();
    cv::destroyAllWindows();
    return EXIT_SUCCESS;
}

#include <opencv2/opencv.hpp>
#include <opencv2/imgproc.hpp>
#include <iostream>
#include <vector>
#include <string>
#include <algorithm>

// ==========================================
// 1. DATA STRUCTURE & PLANNER CLASS
// ==========================================
struct DetectedObject {
    std::string id;
    std::string color;
    int x;
    int y;
    bool load_bearing;
    bool heat_zone;
};

class RescuePlanner {
public:
    std::vector<DetectedObject> generatePlan(std::vector<DetectedObject>& objects) {
        std::vector<DetectedObject> validObjects;

        // Stage 3 safety filters: skip load-bearing or heat-zone blocks
        for (const auto& obj : objects) {
            if (obj.load_bearing || obj.heat_zone) {
                continue; // Skip hazardous blocks
            }
            validObjects.push_back(obj);
        }

        // Sort top-first: ascending order of Y-coordinate, with X tie-breaker
        std::sort(validObjects.begin(), validObjects.end(), [](const DetectedObject& a, const DetectedObject& b) {
            if (a.y == b.y) {
                return a.x < b.x;
            }
            return a.y < b.y;
        });

        return validObjects;
    }
};

// ==========================================
// 2. MAIN VISION & EXECUTION LOOP
// ==========================================
int main() {
    // Open camera (0 for default webcam, or put your ESP32 stream URL string here)
    cv::VideoCapture cap(0); 
    
    if (!cap.isOpened()) {
        std::cerr << "Error: Could not open camera stream!" << std::endl;
        return -1;
    }

    cv::Mat frame;
    RescuePlanner planner;

    std::cout << "--- Rover Vision & Planning Started ---" << std::endl;
    std::cout << "Press 'ESC' in the video window to exit." << std::endl;

    while (true) {
        cap >> frame; // Capture frame from camera
        if (frame.empty()) {
            std::cerr << "Error: Blank frame received!" << std::endl;
            break;
        }

        cv::Mat hsv;
        cv::cvtColor(frame, hsv, cv::COLOR_BGR2HSV);

        // ----------------------------------------------------
        // BLOCK DETECTION (Example: Red Blocks)
        // ----------------------------------------------------
        cv::Scalar lower_red1(0, 120, 70);
        cv::Scalar upper_red1(10, 255, 255);
        cv::Mat mask1, mask_red;
        cv::inRange(hsv, lower_red1, upper_red1, mask1);
        
        // Handle red wrapping around the 0/180 HSV hue boundary
        cv::Scalar lower_red2(170, 120, 70);
        cv::Scalar upper_red2(180, 255, 255);
        cv::Mat mask2;
        cv::inRange(hsv, lower_red2, upper_red2, mask2);
        
        mask_red = mask1 | mask2; // Combine both ranges

        std::vector<std::vector<cv::Point>> contours;
        cv::findContours(mask_red, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);

        std::vector<DetectedObject> detectedObjects;

        for (size_t i = 0; i < contours.size(); i++) {
            // Filter out small noise specs based on pixel area
            if (cv::contourArea(contours[i]) > 400) {
                cv::Moments m = cv::moments(contours[i]);
                if (m.m00 != 0) {
                    int cx = static_cast<int>(m.m10 / m.m00);
                    int cy = static_cast<int>(m.m01 / m.m00);

                    DetectedObject obj;
                    obj.id = "block_" + std::to_string(i + 1);
                    obj.color = "red";
                    obj.x = cx;
                    obj.y = cy;
                    obj.load_bearing = false; // Change to true if this specific block is load-bearing
                    obj.heat_zone = false;    

                    detectedObjects.push_back(obj);

                    // Draw visual cues on the live output window
                    cv::circle(frame, cv::Point(cx, cy), 6, cv::Scalar(0, 255, 0), -1);
                    cv::putText(frame, obj.id, cv::Point(cx - 15, cy - 15), 
                                cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(0, 255, 0), 2);
                }
            }
        }

        // ----------------------------------------------------
        // FIRE / HEAT SOURCE DETECTION (Pulsing Light / Flame)
        // ----------------------------------------------------
        cv::Scalar lower_fire(20, 150, 200); // Tune ranges based on fire/light color
        cv::Scalar upper_fire(35, 255, 255);
        cv::Mat fire_mask;
        cv::inRange(hsv, lower_fire, upper_fire, fire_mask);

        int fire_pixels = cv::countNonZero(fire_mask);
        if (fire_pixels > 800) { // Threshold for fire/heat detection trigger
            std::cout << "[ALERT] Fire / Heat Source Detected in frame!" << std::endl;
            
            // Optionally, you can inject a virtual hazard object into your planner if needed
            DetectedObject fireObj;
            fireObj.id = "fire_hazard";
            fireObj.color = "orange/yellow";
            fireObj.x = frame.cols / 2; // Center rough approximation
            fireObj.y = frame.rows / 2;
            fireObj.load_bearing = false;
            fireObj.heat_zone = true; // This will automatically get filtered out by the planner!
            detectedObjects.push_back(fireObj);
        }

        // ----------------------------------------------------
        // PASS TO RESCUE PLANNER
        // ----------------------------------------------------
        std::vector<DetectedObject> safePlan = planner.generatePlan(detectedObjects);

        // Print current execution priorities to the terminal cleanly
        system("cls"); // Use "clear" if you are on Linux/macOS, "cls" for Windows CMD/PowerShell
        std::cout << "=== RESCUE ROVER LIVE CLEARING PLAN ===" << std::endl;
        if (safePlan.empty()) {
            std::cout << "No safe target objects found." << std::endl;
        } else {
            for (size_t i = 0; i < safePlan.size(); ++i) {
                std::cout << "Priority " << (i + 1) << ": ID = " << safePlan[i].id 
                          << ", X = " << safePlan[i].x << ", Y = " << safePlan[i].y << std::endl;
            }
        }

        // Show live feed view
        cv::imshow("Rover Vision Window", frame);

        // Break loop if 'ESC' key (ASCII 27) is pressed
        if (cv::waitKey(1) == 27) {
            break;
        }
    }

    cap.release();
    cv::destroyAllWindows();
    return 0;
}
#pragma once

#include <Arduino.h>

// Serves the camera over Wi-Fi on port 80, as docs/protocol.md says:
//   /stream    live video (MJPEG), what laptop/vision.py opens
//   /capture   one still picture, handy for a quick look or for calibration
//   /          a small page that shows the stream in a browser
// Call after Wi-Fi is connected and cameraBegin() has succeeded.
void mjpegServerBegin();

// How many viewers are connected right now.
int mjpegViewerCount();

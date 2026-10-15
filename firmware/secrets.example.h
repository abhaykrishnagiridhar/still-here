#pragma once

// Copy to secrets.h (git-ignored) and fill in. The ESP32 only joins 2.4 GHz Wi-Fi,
// so set the phone hotspot to 2.4 GHz.
//
// The laptop must be on the SAME network as the rover. The rover prints its address when it starts
// (for example 192.168.43.20). The laptop's address must begin with the same first three numbers.
// Two different networks can share one name, so compare the numbers, not the name. If they differ,
// the laptop cannot see the rover at all: no ping, no still-here.local, no video.
#define WIFI_SSID "your-hotspot-name"
#define WIFI_PASSWORD "your-hotspot-password"

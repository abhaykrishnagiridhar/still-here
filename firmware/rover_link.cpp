#include "rover_link.h"

#include <ESPmDNS.h>
#include <WebSocketsServer.h>

#include "rover_json.h"
#include "rover_origin.h"

namespace {

constexpr uint16_t COMMAND_PORT = 81;
constexpr uint16_t VIDEO_PORT = 80;
constexpr uint32_t HEARTBEAT_PING_MS = 15000;  // find out about a half-open connection (a vanished phone or laptop)
constexpr uint32_t HEARTBEAT_PONG_MS = 3000;
constexpr uint8_t HEARTBEAT_MISSES = 2;

WebSocketsServer g_server(COMMAND_PORT);
RoverCore* g_core = nullptr;
int g_operator = -1;  // the connection number of the one allowed operator, or -1

class OperatorSink : public RoverSink {
public:
    void send(const char* json) override {
        if (g_operator >= 0) g_server.sendTXT(static_cast<uint8_t>(g_operator), json);
    }
};
OperatorSink g_sink;

// Called by the library for every HTTP header of a connection request. A false answer refuses it.
bool validateHeader(String name, String value) {
    if (name.equalsIgnoreCase("Origin")) {
        bool allowed = originAllowed(value.c_str());
        if (!allowed) Serial.printf("link: refused a connection from the page %s\n", value.c_str());
        return allowed;
    }
    return true;
}

void onEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {
        case WStype_CONNECTED:
            if (g_operator >= 0 && g_operator != num) {
                Serial.printf("link: refused a second operator (connection %u)\n", num);
                g_server.disconnect(num);
            } else {
                g_operator = num;
                Serial.printf("link: operator connected from %s\n", g_server.remoteIP(num).toString().c_str());
            }
            break;
        case WStype_DISCONNECTED:
            if (static_cast<int>(num) == g_operator) {
                g_operator = -1;
                if (g_core != nullptr) g_core->connectionClosed(millis());
                Serial.println("link: operator left");
            }
            break;
        case WStype_TEXT:
            if (static_cast<int>(num) == g_operator && g_core != nullptr) {
                Command command;
                if (parseCommand(reinterpret_cast<const char*>(payload), length, &command) == PARSE_OK) {
                    g_core->handle(command, millis());
                }  // anything unreadable is ignored: the rover keeps doing what it was doing
            }
            break;
        default:
            break;
    }
}

}  // namespace

void roverLinkBegin(RoverCore& core) {
    g_core = &core;
    g_server.begin();
    g_server.onEvent(onEvent);
    g_server.onValidateHttpHeader(validateHeader, nullptr, 0);  // 0 mandatory headers: a missing Origin is fine
    g_server.enableHeartbeat(HEARTBEAT_PING_MS, HEARTBEAT_PONG_MS, HEARTBEAT_MISSES);
    if (MDNS.begin("still-here")) {
        MDNS.addService("ws", "tcp", COMMAND_PORT);
        MDNS.addService("http", "tcp", VIDEO_PORT);
        Serial.println("link: announced as still-here.local (commands on port 81, video on port 80)");
    } else {
        Serial.println("link: could not start mDNS. Use the rover's IP address instead.");
    }
}

void roverLinkLoop() { g_server.loop(); }

bool roverLinkHasOperator() { return g_operator >= 0; }

RoverSink& roverLinkSink() { return g_sink; }

#include "mjpeg_server.h"

#include <WiFi.h>

#include "camera.h"

namespace {

constexpr uint16_t HTTP_PORT = 80;
constexpr int MAX_VIEWERS = 3;
constexpr uint32_t REQUEST_TIMEOUT_MS = 2000;
constexpr uint32_t FRAME_WAIT_MS = 2000;
constexpr uint32_t VIEWER_TASK_STACK = 6144;
constexpr uint32_t ACCEPT_TASK_STACK = 4096;
constexpr uint32_t ACCEPT_POLL_MS = 10;
constexpr int NETWORK_CORE = 0;

const char STREAM_HEADER[] =
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: multipart/x-mixed-replace;boundary=frame\r\n"
    "Cache-Control: no-cache\r\n"
    "Connection: close\r\n\r\n";

const char INDEX_PAGE[] =
    "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
    "<!doctype html><title>STILL HERE rover camera</title>"
    "<body style=\"margin:0;background:#111\"><img src=\"/stream\" style=\"width:100%\">";

volatile int g_viewers = 0;

// Reads one line (up to the newline) from the client. Returns false if it takes too long.
bool readLine(WiFiClient& client, String* line) {
  line->remove(0);
  uint32_t start = millis();
  while (millis() - start < REQUEST_TIMEOUT_MS && client.connected()) {
    if (!client.available()) {
      delay(1);
      continue;
    }
    char c = client.read();
    if (c == '\n') return true;
    if (c != '\r' && line->length() < 200) *line += c;
  }
  return false;
}

// Reads the request's first line and throws away the rest of the headers.
bool readRequestPath(WiFiClient& client, String* path) {
  String first;
  if (!readLine(client, &first)) return false;
  int start = first.indexOf(' ');
  int end = first.indexOf(' ', start + 1);
  if (start < 0 || end < 0) return false;
  *path = first.substring(start + 1, end);

  String header;
  while (readLine(client, &header)) {
    if (header.length() == 0) return true;  // blank line: the headers are over
  }
  return false;
}

void sendStill(WiFiClient& client) {
  uint8_t* buffer = nullptr;
  size_t capacity = 0, length = 0;
  uint32_t seq = 0;
  if (cameraWaitForFrame(0, &buffer, &capacity, &length, &seq, FRAME_WAIT_MS)) {
    client.printf(
        "HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n"
        "Cache-Control: no-cache\r\nConnection: close\r\n\r\n",
        (unsigned)length);
    client.write(buffer, length);
  } else {
    client.print("HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\nno picture yet");
  }
  free(buffer);
}

void sendStream(WiFiClient& client) {
  client.print(STREAM_HEADER);
  uint8_t* buffer = nullptr;
  size_t capacity = 0, length = 0;
  uint32_t seq = 0;
  while (client.connected()) {
    if (!cameraWaitForFrame(seq, &buffer, &capacity, &length, &seq, FRAME_WAIT_MS)) continue;
    client.printf("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n",
                  (unsigned)length);
    bool sent = client.write(buffer, length) == length;
    client.print("\r\n");
    if (!sent) break;
  }
  free(buffer);
}

void handleViewer(WiFiClient& client) {
  String path;
  if (!readRequestPath(client, &path)) return;
  if (path == "/stream") {
    sendStream(client);
  } else if (path == "/capture") {
    sendStill(client);
  } else if (path == "/") {
    client.print(INDEX_PAGE);
  } else {
    client.print("HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n");
  }
}

void viewerTask(void* arg) {
  WiFiClient* client = static_cast<WiFiClient*>(arg);
  handleViewer(*client);
  client->stop();
  delete client;
  g_viewers--;
  vTaskDelete(nullptr);
}

void acceptTask(void*) {
  WiFiServer server(HTTP_PORT);
  server.begin();
  server.setNoDelay(true);
  for (;;) {
    WiFiClient incoming = server.accept();
    if (!incoming) {
      vTaskDelay(pdMS_TO_TICKS(ACCEPT_POLL_MS));
      continue;
    }
    if (g_viewers >= MAX_VIEWERS) {
      incoming.print("HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\ntoo many viewers");
      incoming.stop();
      continue;
    }
    g_viewers++;
    WiFiClient* client = new WiFiClient(incoming);
    xTaskCreatePinnedToCore(viewerTask, "viewer", VIEWER_TASK_STACK, client, 1, nullptr,
                            NETWORK_CORE);
  }
}

}  // namespace

void mjpegServerBegin() {
  xTaskCreatePinnedToCore(acceptTask, "accept", ACCEPT_TASK_STACK, nullptr, 1, nullptr,
                          NETWORK_CORE);
}

int mjpegViewerCount() {
  return g_viewers;
}

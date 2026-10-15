#pragma once

// Who may open the rover's command socket: only pages from this machine or the local network.
// Same rule as laptop/origin_guard.py, so a web page on the public internet cannot make a
// visitor's browser drive the rover. Clients that send no Origin header (the laptop's Python
// code, curl) are not browsers and are allowed.
//
// Deliberately a little STRICTER than the Python version, never looser: an Origin with a user name
// in it is refused (browsers never send one), and only the usual private ranges are allowed
// (10/8, 172.16/12, 192.168/16, 169.254/16, 127/8, ::1, fe80::/10, fc00::/7).
// Plain C++11, no Arduino headers.

#include <ctype.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

namespace rover_origin_detail {

inline bool endsWith(const char* text, const char* suffix) {
    size_t t = strlen(text), s = strlen(suffix);
    return t >= s && strcmp(text + t - s, suffix) == 0;
}

// Reads "a.b.c.d" with no leading zeros. Returns false if it is anything else.
inline bool parseIPv4(const char* host, int octet[4]) {
    const char* p = host;
    for (int i = 0; i < 4; ++i) {
        if (!isdigit(static_cast<unsigned char>(*p))) return false;
        if (*p == '0' && isdigit(static_cast<unsigned char>(p[1]))) return false;
        int value = 0, digits = 0;
        while (isdigit(static_cast<unsigned char>(*p))) {
            value = value * 10 + (*p - '0');
            if (++digits > 3 || value > 255) return false;
            ++p;
        }
        octet[i] = value;
        if (i < 3) {
            if (*p != '.') return false;
            ++p;
        }
    }
    return *p == '\0';
}

inline bool ipv4Local(const int o[4]) {
    return o[0] == 127 || o[0] == 10 || (o[0] == 192 && o[1] == 168) || (o[0] == 169 && o[1] == 254) ||
           (o[0] == 172 && o[1] >= 16 && o[1] <= 31);
}

inline bool ipv6Local(const char* host) {
    for (const char* p = host; *p; ++p) {
        if (!isxdigit(static_cast<unsigned char>(*p)) && *p != ':') return false;
    }
    if (strcmp(host, "::1") == 0) return true;
    char first[5] = {0, 0, 0, 0, 0};
    size_t n = 0;
    while (host[n] && host[n] != ':' && n < 4) {
        first[n] = static_cast<char>(tolower(static_cast<unsigned char>(host[n])));
        ++n;
    }
    if (n < 2 || (host[n] && host[n] != ':')) return false;
    if (strncmp(first, "fe8", 3) == 0 || strncmp(first, "fe9", 3) == 0 || strncmp(first, "fea", 3) == 0 ||
        strncmp(first, "feb", 3) == 0) {
        return n == 4;  // fe80::/10
    }
    return n == 4 && (strncmp(first, "fc", 2) == 0 || strncmp(first, "fd", 2) == 0);  // fc00::/7
}

}  // namespace rover_origin_detail

inline bool originAllowed(const char* origin) {
    using namespace rover_origin_detail;
    if (origin == nullptr || origin[0] == '\0') return true;
    const char* scheme = strstr(origin, "://");
    if (scheme == nullptr || scheme == origin) return false;  // "null" and the like
    const char* start = scheme + 3;
    char host[64];
    size_t n = 0;
    if (*start == '[') {  // IPv6 in brackets
        ++start;
        while (start[n] && start[n] != ']' && n + 1 < sizeof host) {
            host[n] = start[n];
            ++n;
        }
        if (start[n] != ']') return false;
    } else {
        while (start[n] && start[n] != ':' && start[n] != '/' && n + 1 < sizeof host) {
            host[n] = start[n];
            ++n;
        }
        if (start[n] && start[n] != ':' && start[n] != '/') return false;  // host too long
    }
    host[n] = '\0';
    if (n == 0 || strchr(host, '@') != nullptr) return false;
    for (size_t i = 0; i < n; ++i) host[i] = static_cast<char>(tolower(static_cast<unsigned char>(host[i])));
    if (strcmp(host, "localhost") == 0 || endsWith(host, ".localhost")) return true;
    int octet[4];
    if (parseIPv4(host, octet)) return ipv4Local(octet);
    if (strchr(host, ':') != nullptr) return ipv6Local(host);
    return false;
}

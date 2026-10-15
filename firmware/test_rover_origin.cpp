// Tests for rover_origin.h on the PC. The "same as Python" rows were checked against
// laptop/origin_guard.py when this was written:
//   g++ -std=c++11 -Wall -Wextra -Wpedantic test_rover_origin.cpp -o test_rover_origin && ./test_rover_origin
#include <cstdio>
#include <cstdlib>
#include <string>

#include "rover_origin.h"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #cond);       \
            ++failures;                                                        \
        }                                                                      \
    } while (0)

static void pages_from_this_machine_or_the_local_network_are_allowed() {
    const char* allowed[] = {"http://localhost:3000", "http://127.0.0.1:8000", "http://192.168.0.20:8765",
                             "http://10.0.0.5", "http://[::1]:8000", "http://172.16.0.1", "http://172.31.255.255",
                             "http://169.254.1.1", "http://app.localhost", "https://LOCALHOST", "http://[fe80::1]",
                             "http://[fd12:3456::1]:80", "http://192.168.0.20", "http://192.168.0.20/path"};
    for (const char* origin : allowed) {
        if (!originAllowed(origin)) std::fprintf(stderr, "should be allowed: %s\n", origin);
        CHECK(originAllowed(origin));
    }
}

static void a_client_with_no_origin_header_is_allowed() {
    CHECK(originAllowed(nullptr));
    CHECK(originAllowed(""));
}

static void pages_from_the_internet_are_refused() {
    const char* refused[] = {"https://evil.example", "http://8.8.8.8", "http://localhost.evil.example", "null",
                             "http://", "http://172.32.0.1", "http://172.15.0.1", "http://192.169.0.1",
                             "http://11.0.0.1", "http://1.2.3", "http://01.2.3.4", "http://192.168.0.1.evil.com",
                             "http://[2001:db8::1]", "http://evil.example:80@192.168.0.1", "http://user@192.168.0.1",
                             "localhost", "://localhost", "http://[::1", "http://192.168.0.256",
                             "http://256.1.1.1", "http://1.1.1.1.1", "http://fe80::1", "http://example.local"};
    for (const char* origin : refused) {
        if (originAllowed(origin)) std::fprintf(stderr, "should be refused: %s\n", origin);
        CHECK(!originAllowed(origin));
    }
}

static void a_very_long_origin_is_refused_without_overflowing() {
    std::string longHost = "http://" + std::string(500, 'a') + ".example";
    CHECK(!originAllowed(longHost.c_str()));
    std::string longLocal = "http://" + std::string(500, '1');
    CHECK(!originAllowed(longLocal.c_str()));
}

int main() {
    pages_from_this_machine_or_the_local_network_are_allowed();
    a_client_with_no_origin_header_is_allowed();
    pages_from_the_internet_are_refused();
    a_very_long_origin_is_refused_without_overflowing();

    if (failures == 0) {
        std::printf("all tests passed\n");
        return EXIT_SUCCESS;
    }
    std::printf("%d check(s) failed\n", failures);
    return EXIT_FAILURE;
}

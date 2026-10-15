#pragma once

// Reads one protocol message (docs/protocol.md) from JSON text. Strict, bounded and with no heap:
// it never allocates, never recurses deeper than MAX_DEPTH, and never writes past its buffers,
// so a hostile or broken sender cannot crash the rover. Plain C++11, no Arduino headers.
//
// What it accepts: one JSON object. Keys it does not know are skipped (any shape). Duplicate keys:
// the last one wins. NaN and Infinity are not JSON and are refused.
//
// parseCommand() tells you how far it got:
//   PARSE_OK         the text is valid JSON. Check command.type: CMD_UNKNOWN means "ignore it".
//   PARSE_BAD_JSON   not valid JSON, or too deep: ignore the message.
//   PARSE_TOO_BIG    longer than MAX_MESSAGE_BYTES: ignore the message.
//   PARSE_BAD_FIELD  a drive or arm_pose number was not a usable number: ignore the message.
// A plan with a problem is still PARSE_OK: command.stepsValid and command.planProblem say what
// was wrong, so the rover can answer bad_plan.

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "rover_types.h"

constexpr size_t MAX_MESSAGE_BYTES = 6144;
constexpr int MAX_PLAN_STEPS = 32;
constexpr int MAX_DEPTH = 8;

enum CommandType {
    CMD_UNKNOWN = 0,
    CMD_PING,
    CMD_MODE,
    CMD_DRIVE,
    CMD_ARM_POSE,
    CMD_PLAN,
    CMD_PLAN_START,
    CMD_ABORT
};

enum ParseStatus { PARSE_OK = 0, PARSE_BAD_JSON, PARSE_TOO_BIG, PARSE_BAD_FIELD };

enum PlanProblem { PLAN_OK = 0, PLAN_UNREADABLE, PLAN_UNKNOWN_ACTION, PLAN_TOO_MANY_STEPS };

struct PlanStep {
    long id;
    bool pick;  // true = pick, false = drop
    float x, y, z;
    PlanStep() : id(0), pick(false), x(0), y(0), z(0) {}
};

struct Command {
    CommandType type;

    bool hasT;
    double t;

    bool modeValid;
    bool modeAuto;

    float left, right;

    bool hasJoint[JOINT_COUNT];
    float joint[JOINT_COUNT];
    bool hasSpeed;
    float speed;

    bool planIdValid;  // plan_id was present and a positive whole number
    long planId;

    bool stepsPresent;
    bool stepsValid;
    PlanProblem planProblem;
    int stepCount;
    PlanStep steps[MAX_PLAN_STEPS];

    bool badField;  // some number was not usable

    Command()
        : type(CMD_UNKNOWN), hasT(false), t(0), modeValid(false), modeAuto(false), left(0), right(0),
          hasSpeed(false), speed(1.0f), planIdValid(false), planId(0), stepsPresent(false),
          stepsValid(false), planProblem(PLAN_OK), stepCount(0), badField(false) {
        for (int i = 0; i < JOINT_COUNT; ++i) {
            hasJoint[i] = false;
            joint[i] = 0.0f;
        }
    }
};

namespace rover_json_detail {

enum NumberResult { NUM_OK, NUM_BAD, NUM_OVERFLOW };

class Cursor {
public:
    Cursor(const char* text, size_t length) : p_(text), end_(text + length), failed_(false) {
        if (length > 0 && memchr(text, 0, length) != nullptr) failed_ = true;  // no embedded NUL
    }

    bool failed() const { return failed_; }
    bool fail() {
        failed_ = true;
        return false;
    }

    void skipSpace() {
        while (p_ < end_ && (*p_ == ' ' || *p_ == '\t' || *p_ == '\n' || *p_ == '\r')) ++p_;
    }
    char peek() {
        skipSpace();
        return p_ < end_ ? *p_ : '\0';
    }
    bool consume(char c) {
        skipSpace();
        if (!failed_ && p_ < end_ && *p_ == c) {
            ++p_;
            return true;
        }
        return false;
    }
    bool atEnd() {
        skipSpace();
        return !failed_ && p_ == end_;
    }

    // Reads a string. Stores at most cap-1 characters in out (out may be null to just skip it) and
    // sets *truncated when the string was longer. Non-ASCII \u escapes are stored as '?'.
    bool readString(char* out, size_t cap, bool* truncated) {
        if (failed_ || !consume('"')) return false;
        size_t n = 0;
        if (truncated) *truncated = false;
        for (;;) {
            if (p_ >= end_) return fail();
            unsigned char c = static_cast<unsigned char>(*p_++);
            if (c == '"') break;
            if (c < 0x20) return fail();
            char stored = static_cast<char>(c);
            if (c == '\\') {
                if (p_ >= end_) return fail();
                char e = *p_++;
                switch (e) {
                    case '"': stored = '"'; break;
                    case '\\': stored = '\\'; break;
                    case '/': stored = '/'; break;
                    case 'b': stored = '\b'; break;
                    case 'f': stored = '\f'; break;
                    case 'n': stored = '\n'; break;
                    case 'r': stored = '\r'; break;
                    case 't': stored = '\t'; break;
                    case 'u': {
                        unsigned code = 0;
                        for (int i = 0; i < 4; ++i) {
                            if (p_ >= end_) return fail();
                            char h = *p_++;
                            unsigned v;
                            if (h >= '0' && h <= '9') v = h - '0';
                            else if (h >= 'a' && h <= 'f') v = 10 + h - 'a';
                            else if (h >= 'A' && h <= 'F') v = 10 + h - 'A';
                            else return fail();
                            code = code * 16 + v;
                        }
                        stored = code < 0x80 && code != 0 ? static_cast<char>(code) : '?';
                        break;
                    }
                    default: return fail();
                }
            }
            if (out && n + 1 < cap) out[n++] = stored;
            else if (truncated) *truncated = true;
        }
        if (out && cap > 0) out[n] = '\0';
        return true;
    }

    // Reads a JSON number (strict grammar: no leading zeros, no "1.", no NaN).
    NumberResult readNumber(double* value) {
        skipSpace();
        if (failed_) return NUM_BAD;
        char buffer[48];
        size_t n = 0;
        bool full = false;
        auto take = [&]() {
            if (n + 1 >= sizeof buffer) full = true;
            else buffer[n++] = *p_;
            ++p_;
        };
        auto digit = [&]() { return p_ < end_ && *p_ >= '0' && *p_ <= '9'; };
        if (p_ < end_ && *p_ == '-') take();
        if (!digit()) return fail(), NUM_BAD;
        if (*p_ == '0') {
            take();
            if (digit()) return fail(), NUM_BAD;  // leading zero
        } else {
            while (digit()) take();
        }
        if (p_ < end_ && *p_ == '.') {
            take();
            if (!digit()) return fail(), NUM_BAD;
            while (digit()) take();
        }
        if (p_ < end_ && (*p_ == 'e' || *p_ == 'E')) {
            take();
            if (p_ < end_ && (*p_ == '+' || *p_ == '-')) take();
            if (!digit()) return fail(), NUM_BAD;
            while (digit()) take();
        }
        if (full) return fail(), NUM_BAD;  // absurdly long number
        buffer[n] = '\0';
        double parsed = strtod(buffer, nullptr);
        if (!isfinite(parsed)) return NUM_OVERFLOW;
        *value = parsed;
        return NUM_OK;
    }

    bool literal(const char* word) {
        skipSpace();
        size_t length = strlen(word);
        if (failed_ || static_cast<size_t>(end_ - p_) < length || memcmp(p_, word, length) != 0) return fail();
        p_ += length;
        return true;
    }

    bool skipValue(int depth) {
        if (depth > MAX_DEPTH) return fail();
        char c = peek();
        if (c == '"') return readString(nullptr, 0, nullptr);
        if (c == '{') {
            consume('{');
            if (consume('}')) return true;
            for (;;) {
                if (peek() != '"' || !readString(nullptr, 0, nullptr) || !consume(':') || !skipValue(depth + 1)) return fail();
                if (consume(',')) continue;
                if (consume('}')) return true;
                return fail();
            }
        }
        if (c == '[') {
            consume('[');
            if (consume(']')) return true;
            for (;;) {
                if (!skipValue(depth + 1)) return false;
                if (consume(',')) continue;
                if (consume(']')) return true;
                return fail();
            }
        }
        if (c == 't') return literal("true");
        if (c == 'f') return literal("false");
        if (c == 'n') return literal("null");
        double ignored;
        return readNumber(&ignored) != NUM_BAD && !failed_;
    }

private:
    const char* p_;
    const char* end_;
    bool failed_;
};

// Reads a number value for a known key. A value that is not a number, or too big, marks the
// command as having a bad field but keeps parsing, so the rest of the text is still checked.
inline bool readNumberField(Cursor& in, Command* command, double* value, bool* present) {
    char c = in.peek();
    if (c == '-' || (c >= '0' && c <= '9')) {
        NumberResult r = in.readNumber(value);
        if (r == NUM_BAD) return false;
        if (r == NUM_OVERFLOW) {
            command->badField = true;
            if (present) *present = false;
        } else if (present) {
            *present = true;
        }
        return true;
    }
    command->badField = true;
    if (present) *present = false;
    return in.skipValue(1);
}

inline bool readStep(Cursor& in, Command* command) {
    bool hasId = false, hasAction = false, hasX = false, hasY = false, hasZ = false;
    double id = 0, x = 0, y = 0, z = 0;
    char action[12];
    action[0] = '\0';
    bool actionTruncated = false;
    bool stepBad = false;
    if (!in.consume('{')) return in.fail();
    if (!in.consume('}')) {
        for (;;) {
            char key[12];
            bool keyTruncated = false;
            if (in.peek() != '"' || !in.readString(key, sizeof key, &keyTruncated) || !in.consume(':')) return in.fail();
            if (!keyTruncated && strcmp(key, "id") == 0) {
                if (!readNumberField(in, command, &id, &hasId)) return false;
            } else if (!keyTruncated && strcmp(key, "x") == 0) {
                if (!readNumberField(in, command, &x, &hasX)) return false;
            } else if (!keyTruncated && strcmp(key, "y") == 0) {
                if (!readNumberField(in, command, &y, &hasY)) return false;
            } else if (!keyTruncated && strcmp(key, "z") == 0) {
                if (!readNumberField(in, command, &z, &hasZ)) return false;
            } else if (!keyTruncated && strcmp(key, "action") == 0) {
                if (in.peek() == '"') {
                    if (!in.readString(action, sizeof action, &actionTruncated)) return false;
                    hasAction = true;
                } else {
                    stepBad = true;
                    if (!in.skipValue(2)) return false;
                }
            } else if (!in.skipValue(2)) {
                return false;
            }
            if (in.consume(',')) continue;
            if (in.consume('}')) break;
            return in.fail();
        }
    }
    // A step is judged after it is read. Every problem is remembered, none is acted on.
    bool pick = !actionTruncated && strcmp(action, "pick") == 0;
    bool drop = !actionTruncated && strcmp(action, "drop") == 0;
    bool idOk = hasId && id == floor(id) && id >= 1 && id <= 2147483647.0;
    if (stepBad || !hasId || !hasX || !hasY || !hasZ || !hasAction || !idOk) {
        if (command->planProblem == PLAN_OK) command->planProblem = PLAN_UNREADABLE;
    } else if (!pick && !drop) {
        if (command->planProblem == PLAN_OK) command->planProblem = PLAN_UNKNOWN_ACTION;
    } else if (command->stepCount >= MAX_PLAN_STEPS) {
        command->planProblem = PLAN_TOO_MANY_STEPS;
    } else {
        for (int i = 0; i < command->stepCount; ++i) {
            if (command->steps[i].id == static_cast<long>(id) && command->planProblem == PLAN_OK) {
                command->planProblem = PLAN_UNREADABLE;  // two steps with the same id
            }
        }
        PlanStep& step = command->steps[command->stepCount++];
        step.id = static_cast<long>(id);
        step.pick = pick;
        step.x = static_cast<float>(x);
        step.y = static_cast<float>(y);
        step.z = static_cast<float>(z);
    }
    return true;
}

inline bool readSteps(Cursor& in, Command* command) {
    command->stepsPresent = true;
    if (!in.consume('[')) return in.fail();
    if (in.consume(']')) return true;
    for (;;) {
        if (!readStep(in, command)) return false;
        if (in.consume(',')) continue;
        if (in.consume(']')) return true;
        return in.fail();
    }
}

}  // namespace rover_json_detail

inline ParseStatus parseCommand(const char* text, size_t length, Command* command) {
    using namespace rover_json_detail;
    *command = Command();
    if (length > MAX_MESSAGE_BYTES) return PARSE_TOO_BIG;
    Cursor in(text, length);
    if (!in.consume('{')) return PARSE_BAD_JSON;

    char typeName[24];
    typeName[0] = '\0';
    bool typeTruncated = false;
    char modeName[12];
    modeName[0] = '\0';
    bool modeTruncated = false, hasMode = false;
    double planId = 0;
    bool hasPlanId = false;

    if (!in.consume('}')) {
        for (;;) {
            char key[16];
            bool keyTruncated = false;
            if (in.peek() != '"' || !in.readString(key, sizeof key, &keyTruncated) || !in.consume(':')) {
                return PARSE_BAD_JSON;
            }
            bool ok;
            double number = 0;
            bool present = false;
            if (keyTruncated) {
                ok = in.skipValue(1);
            } else if (strcmp(key, "type") == 0) {
                if (in.peek() == '"') {
                    ok = in.readString(typeName, sizeof typeName, &typeTruncated);
                } else {
                    command->badField = true;
                    ok = in.skipValue(1);
                }
            } else if (strcmp(key, "mode") == 0) {
                if (in.peek() == '"') {
                    ok = in.readString(modeName, sizeof modeName, &modeTruncated);
                    hasMode = ok;
                } else {
                    ok = in.skipValue(1);
                }
            } else if (strcmp(key, "steps") == 0) {
                ok = in.peek() == '[' ? readSteps(in, command) : in.skipValue(1);
            } else if (strcmp(key, "t") == 0) {
                ok = readNumberField(in, command, &number, &present);
                if (ok && present) {
                    command->hasT = true;
                    command->t = number;
                }
            } else if (strcmp(key, "left") == 0 || strcmp(key, "right") == 0) {
                ok = readNumberField(in, command, &number, &present);
                if (ok && present) (key[0] == 'l' ? command->left : command->right) = static_cast<float>(number);
            } else if (strcmp(key, "speed") == 0) {
                ok = readNumberField(in, command, &number, &present);
                if (ok && present) {
                    command->hasSpeed = true;
                    command->speed = static_cast<float>(number);
                }
            } else if (strcmp(key, "plan_id") == 0) {
                ok = readNumberField(in, command, &planId, &hasPlanId);
            } else {
                int joint = strcmp(key, "base") == 0       ? JOINT_BASE
                            : strcmp(key, "shoulder") == 0 ? JOINT_SHOULDER
                            : strcmp(key, "elbow") == 0    ? JOINT_ELBOW
                            : strcmp(key, "gripper") == 0  ? JOINT_GRIPPER
                                                           : -1;
                if (joint >= 0) {
                    ok = readNumberField(in, command, &number, &present);
                    if (ok && present) {
                        command->hasJoint[joint] = true;
                        command->joint[joint] = static_cast<float>(number);
                    }
                } else {
                    ok = in.skipValue(1);
                }
            }
            if (!ok || in.failed()) return PARSE_BAD_JSON;
            if (in.consume(',')) continue;
            if (in.consume('}')) break;
            return PARSE_BAD_JSON;
        }
    }
    if (!in.atEnd()) return PARSE_BAD_JSON;

    if (hasMode && !modeTruncated) {
        if (strcmp(modeName, "manual") == 0) {
            command->modeValid = true;
            command->modeAuto = false;
        } else if (strcmp(modeName, "auto") == 0) {
            command->modeValid = true;
            command->modeAuto = true;
        }
    }
    command->planIdValid = hasPlanId && planId == floor(planId) && planId >= 1 && planId <= 2147483647.0;
    if (command->planIdValid) command->planId = static_cast<long>(planId);
    command->stepsValid = command->stepsPresent && command->planProblem == PLAN_OK;
    if (!command->stepsPresent && command->planProblem == PLAN_OK) command->planProblem = PLAN_UNREADABLE;

    if (!typeTruncated) {
        if (strcmp(typeName, "ping") == 0) command->type = CMD_PING;
        else if (strcmp(typeName, "mode") == 0) command->type = CMD_MODE;
        else if (strcmp(typeName, "drive") == 0) command->type = CMD_DRIVE;
        else if (strcmp(typeName, "arm_pose") == 0) command->type = CMD_ARM_POSE;
        else if (strcmp(typeName, "plan") == 0) command->type = CMD_PLAN;
        else if (strcmp(typeName, "plan_start") == 0) command->type = CMD_PLAN_START;
        else if (strcmp(typeName, "abort") == 0) command->type = CMD_ABORT;
    }
    if (command->badField && (command->type == CMD_DRIVE || command->type == CMD_ARM_POSE)) return PARSE_BAD_FIELD;
    return PARSE_OK;
}

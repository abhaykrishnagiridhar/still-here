#pragma once

#include <Arduino.h>

#include "rover_core.h"

// The operator link: a WebSocket server on port 81 and the mDNS name `still-here`, as in
// docs/protocol.md. It reads each text message with rover_json.h, hands it to the core, and sends
// whatever the core says back to the one connected operator.
//
//  - Only one operator at a time: a second connection is refused.
//  - A connection whose Origin header names a site outside this machine or the local network is
//    refused (rover_origin.h). Clients that send no Origin, such as the laptop's Python code, are
//    allowed.
//  - When the operator's connection closes, the core is told at once (connectionClosed).
//
// NOT TESTED ON THE BOARD YET. The decisions it makes (what to ignore, who is allowed) live in
// rover_json.h, rover_origin.h and rover_core.h, which are tested on a PC.
void roverLinkBegin(RoverCore& core);

// Where the core sends what it says: to the connected operator, or nowhere if there is none.
// Create the RoverCore with this, then call roverLinkBegin(core).
RoverSink& roverLinkSink();

// Call every pass of loop().
void roverLinkLoop();

bool roverLinkHasOperator();

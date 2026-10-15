"""Who may press the buttons: only pages served from this machine or the local network.

Browsers always send an Origin header with a cross-site request. A page on the public
internet therefore cannot make a visitor's browser drive the rover or approve a plan.
Clients that send no Origin, such as scripts and curl, are not browsers and are allowed.
"""

import ipaddress
from typing import Optional
from urllib.parse import urlparse


def origin_allowed(origin: Optional[str]) -> bool:
    if not origin:
        return True
    host = urlparse(origin).hostname
    if host is None:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local

"""
RADIUS PAP authentication — pure Python, no third-party dependencies.

FortiAuthenticator setup required:
  1. Add a RADIUS client entry for this app's IP with a shared secret.
  2. Create user groups and configure them to return Filter-Id or Class
     attributes in the Access-Accept reply with the group name as the value.
  3. Set RADIUS_GROUP_ADMIN / RADIUS_GROUP_VIEWER in .env to match those names.

Role resolution from reply attributes:
  - Filter-Id (attribute 11) or Class (attribute 25) are checked for the
    configured group names (case-insensitive substring match).
  - Admin group takes precedence over viewer group.
  - If FortiAuthenticator sends no group attributes the user gets 'viewer'.
  - If group attributes are present but none match, access is denied.
"""

import hashlib
import hmac
import logging
import os
import socket
import struct
from typing import Optional

log = logging.getLogger(__name__)

_ACCESS_REQUEST  = 1
_ACCESS_ACCEPT   = 2
_ATTR_USER_NAME      = 1
_ATTR_USER_PASSWORD  = 2
_ATTR_FILTER_ID      = 11
_ATTR_NAS_IDENTIFIER = 32
_ATTR_CLASS          = 25


def _encrypt_pap_password(password: str, secret: bytes, authenticator: bytes) -> bytes:
    """RFC 2865 §5.2 PAP password obfuscation."""
    raw = password.encode("utf-8")[:128]
    padded = raw + b"\x00" * ((-len(raw)) % 16 or 16)
    result, last = b"", authenticator
    for i in range(0, len(padded), 16):
        digest = hashlib.md5(secret + last).digest()
        block  = bytes(a ^ b for a, b in zip(padded[i:i + 16], digest))
        result += block
        last    = block
    return result


def _attr(code: int, value: bytes) -> bytes:
    return bytes([code, len(value) + 2]) + value


def _parse_attrs(data: bytes) -> dict:
    attrs: dict = {}
    pos = 0
    while pos + 2 <= len(data):
        t, length = data[pos], data[pos + 1]
        if length < 2 or pos + length > len(data):
            break
        attrs.setdefault(t, []).append(data[pos + 2:pos + length])
        pos += length
    return attrs


def authenticate(
    username: str,
    password: str,
    host: str,
    port: int,
    secret: str,
    timeout: int,
    group_admin: str,
    group_viewer: str,
) -> Optional[str]:
    """
    Send a RADIUS Access-Request (PAP) and return the user's role or None.

    Returns 'admin', 'viewer', or None (rejected / error / no group match).
    """
    secret_b   = secret.encode("utf-8")
    identifier = os.urandom(1)[0]
    req_auth   = os.urandom(16)

    body = (
        _attr(_ATTR_USER_NAME,      username.encode("utf-8"))
        + _attr(_ATTR_USER_PASSWORD, _encrypt_pap_password(password, secret_b, req_auth))
        + _attr(_ATTR_NAS_IDENTIFIER, b"4thealth")
    )
    length = 20 + len(body)
    packet = struct.pack("!BBH16s", _ACCESS_REQUEST, identifier, length, req_auth) + body

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(packet, (host, port))
            reply, _ = sock.recvfrom(4096)
    except OSError as exc:
        log.error("RADIUS socket error for %r: %s", username, exc)
        return None

    if len(reply) < 20:
        log.warning("RADIUS short reply for %r (%d bytes)", username, len(reply))
        return None

    code, reply_id, reply_len = struct.unpack("!BBH", reply[:4])
    reply_auth = reply[4:20]
    attrs_data = reply[20:reply_len]

    # Verify reply authenticator (RFC 2865 §3)
    expected = hashlib.md5(
        bytes([code, reply_id]) + struct.pack("!H", reply_len)
        + req_auth + attrs_data + secret_b
    ).digest()
    if not hmac.compare_digest(expected, reply_auth):
        log.warning("RADIUS authenticator mismatch for %r — check shared secret", username)
        return None

    if code != _ACCESS_ACCEPT:
        log.info("RADIUS access denied for %r (code=%d)", username, code)
        return None

    # Extract group names from Filter-Id and Class attributes
    attrs  = _parse_attrs(attrs_data)
    groups = [
        v.decode("utf-8", errors="ignore").strip("\x00 ")
        for t in (_ATTR_FILTER_ID, _ATTR_CLASS)
        for v in attrs.get(t, [])
        if v
    ]

    if group_admin and any(group_admin.lower() in g.lower() for g in groups):
        return "admin"
    if group_viewer and any(group_viewer.lower() in g.lower() for g in groups):
        return "viewer"
    if groups:
        log.warning(
            "RADIUS user %r authenticated but no role group matched. "
            "Groups received: %s. Expected admin=%r viewer=%r",
            username, groups, group_admin, group_viewer,
        )
        return None

    # No group attributes in reply — default to viewer
    return "viewer"

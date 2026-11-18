"""Minimal SOCKS5 client (RFC 1928) used to place the Tor arm through a proxy.

Only the no-authentication, CONNECT command, IPv4/domain/IPv6 address types are
implemented, which is what a local Tor ``SocksPort`` exposes to a client. The
SOCKS reply code is preserved in the error message because Tor uses it to report
path failures, and a failed circuit must be recorded as a failure rather than
retried until a lucky sample appears.
"""
from __future__ import annotations

import asyncio
import ipaddress

__all__ = ["Socks5Error", "open_socks5"]

_REPLY_NAMES = {
    0x00: "succeeded",
    0x01: "general SOCKS server failure",
    0x02: "connection not allowed by ruleset",
    0x03: "network unreachable",
    0x04: "host unreachable",
    0x05: "connection refused",
    0x06: "TTL expired",
    0x07: "command not supported",
    0x08: "address type not supported",
    0x90: "tor: circuit established, stream still in progress",
    0x91: "tor: stream already open",
}


class Socks5Error(RuntimeError):
    """Raised when the SOCKS5 greeting or CONNECT reply fails."""

    def __init__(self, message: str, *, reply_code: int | None = None) -> None:
        self.reply_code = reply_code
        super().__init__(message)


def _encode_target(host: str, port: int) -> tuple[bytes, int]:
    """Return (address bytes, ATYP) for a host literal or a domain name."""
    if not isinstance(host, str) or not host:
        raise ValueError("target host must be a non-empty string")
    if not 1 <= int(port) <= 65535:
        raise ValueError("target port must be within 1..65535")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        encoded = host.encode("idna")
        if not 1 <= len(encoded) <= 255:
            raise ValueError("target domain must encode to 1..255 bytes") from None
        return len(encoded).to_bytes(1, "big") + encoded, 0x03
    if address.version == 4:
        return address.packed, 0x01
    return address.packed, 0x04


async def open_socks5(
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    *,
    timeout: float = 60.0,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a proxied TCP connection through a SOCKS5 proxy and CONNECT command."""
    address_bytes, address_type = _encode_target(target_host, target_port)
    started = asyncio.get_running_loop().time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(proxy_host, proxy_port), timeout=timeout
        )
    except (OSError, TimeoutError) as exc:
        raise Socks5Error(f"socks5 proxy {proxy_host}:{proxy_port} unreachable: {type(exc).__name__}") from exc
    try:
        remaining = timeout - (asyncio.get_running_loop().time() - started)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        greeting = await asyncio.wait_for(reader.readexactly(2), timeout=max(0.1, remaining))
        if greeting[0] != 0x05:
            raise Socks5Error(f"not a SOCKS5 proxy (version byte {greeting[0]})")
        if greeting[1] != 0x00:
            raise Socks5Error(f"proxy refused the no-authentication method (0x{greeting[1]:02x})")

        request = b"\x05\x01\x00" + bytes([address_type]) + address_bytes + int(target_port).to_bytes(2, "big")
        remaining = timeout - (asyncio.get_running_loop().time() - started)
        writer.write(request)
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(4), timeout=max(0.1, remaining))
        if head[0] != 0x05:
            raise Socks5Error(f"invalid SOCKS5 reply version 0x{head[0]:02x}")
        reply_code = head[1]
        if reply_code != 0x00:
            name = _REPLY_NAMES.get(reply_code, "unknown SOCKS5 reply")
            raise Socks5Error(f"SOCKS5 CONNECT failed: {name} (0x{reply_code:02x})", reply_code=reply_code)
        atyp = head[3]
        if atyp == 0x01:
            bound_length = 4
        elif atyp == 0x04:
            bound_length = 16
        elif atyp == 0x03:
            length_byte = await asyncio.wait_for(reader.readexactly(1), timeout=max(0.1, remaining))
            bound_length = length_byte[0]
        else:
            raise Socks5Error(f"invalid SOCKS5 bound address type 0x{atyp:02x}")
        await asyncio.wait_for(reader.readexactly(bound_length + 2), timeout=max(0.1, remaining))
        return reader, writer
    except BaseException:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
        raise

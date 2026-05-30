"""Hardware test: paint the four LED segments red / green / blue / yellow.

Sends pixel data to WLED using the DNRGB realtime UDP protocol on port 21324:

    byte 0:    4  (protocol = DNRGB)
    byte 1:    timeout in seconds (WLED reverts after this idle window)
    byte 2-3:  start LED index, big-endian uint16
    byte 4+:   RGB triples for sequential LEDs

DNRGB lets us send long strips as multiple chunks (each with its own start
index), staying under the safe UDP-over-Ethernet payload size (~1472 bytes).
Ctrl+C to stop.
"""

import socket
import time

WLED_IP = "192.168.0.194"     # or "wled-0bec08.local"
WLED_PORT = 21324             # WLED realtime UDP port
TIMEOUT_SECS = 2              # WLED reverts to its normal effect after this idle gap
COLOR_ORDER = "RGB"

LEDS_PER_SEGMENT = 273
SEGMENT_COLORS = [
    (255, 0,   0),    # segment 1 — red
    (0,   255, 0),    # segment 2 — green
    (0,   0,   255),  # segment 3 — blue
    (255, 255, 0),    # segment 4 — yellow
]

# DNRGB header is 4 bytes; cap chunk payload at ~1440 to stay under MTU.
# 480 LEDs * 3 bytes = 1440 bytes payload, plus 4-byte header = 1444 bytes.
LEDS_PER_CHUNK = 480


def reorder(px, color_order):
    order = {"RGB": (0, 1, 2), "GRB": (1, 0, 2), "BRG": (2, 0, 1),
             "BGR": (2, 1, 0), "GBR": (1, 2, 0), "RBG": (0, 2, 1)}[color_order]
    return (px[order[0]], px[order[1]], px[order[2]])


def build_pixels():
    pixels = []
    for color in SEGMENT_COLORS:
        pixels.extend([color] * LEDS_PER_SEGMENT)
    return pixels


def send_dnrgb(sock, pixels):
    """Send the full strip as one or more DNRGB chunks."""
    for start in range(0, len(pixels), LEDS_PER_CHUNK):
        chunk = pixels[start:start + LEDS_PER_CHUNK]
        header = bytes([4, TIMEOUT_SECS, (start >> 8) & 0xFF, start & 0xFF])
        body = bytearray(len(chunk) * 3)
        for i, px in enumerate(chunk):
            r, g, b = reorder(px, COLOR_ORDER)
            body[i*3 + 0] = r
            body[i*3 + 1] = g
            body[i*3 + 2] = b
        sock.sendto(header + bytes(body), (WLED_IP, WLED_PORT))


def main():
    pixels = build_pixels()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    chunks = (len(pixels) + LEDS_PER_CHUNK - 1) // LEDS_PER_CHUNK
    print(f"Target:      {WLED_IP}:{WLED_PORT} (DNRGB)")
    print(f"Total LEDs:  {len(pixels)} ({len(SEGMENT_COLORS)} x {LEDS_PER_SEGMENT})")
    print(f"Chunks:      {chunks} packet(s) per frame, up to {LEDS_PER_CHUNK} LEDs each")
    print(f"Segments:    red, green, blue, yellow")
    print("Sending continuously. Ctrl+C to stop.")

    try:
        while True:
            send_dnrgb(sock, pixels)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping.")


if __name__ == "__main__":
    main()

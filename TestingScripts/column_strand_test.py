"""Hardware test: paint each of the 8 column strands a different rainbow color.

The column has 8 parallel strands of 600 LEDs running top-to-bottom; one
revolution around the column is 51 LEDs (helix pitch — not used by this test
but worth keeping in mind for future ring-aware effects).

Strands are laid out red, orange, yellow, green, cyan, blue, purple, magenta
so each one is easy to identify visually.

Sends DNRGB UDP to WLED on port 21324, chunked at 480 LEDs/packet (same wire
protocol as the main script and segment_color_test.py). Loops so WLED stays in
realtime mode. Ctrl+C to stop.
"""

import socket
import time

WLED_IP = "192.168.0.195"     # adjust if the column is on a different WLED controller
WLED_PORT = 21324
TIMEOUT_SECS = 2
COLOR_ORDER = "RGB"

LEDS_PER_STRAND = 600
STRAND_COLORS = [
    (255, 0,   0),    # 1 — red
    (255, 128, 0),    # 2 — orange
    (255, 255, 0),    # 3 — yellow
    (0,   255, 0),    # 4 — green
    (0,   255, 255),  # 5 — cyan
    (0,   0,   255),  # 6 — blue
    (128, 0,   255),  # 7 — purple
    (255, 0,   255),  # 8 — magenta
]

LEDS_PER_CHUNK = 480


def reorder(px, color_order):
    order = {"RGB": (0, 1, 2), "GRB": (1, 0, 2), "BRG": (2, 0, 1),
             "BGR": (2, 1, 0), "GBR": (1, 2, 0), "RBG": (0, 2, 1)}[color_order]
    return (px[order[0]], px[order[1]], px[order[2]])


def build_pixels():
    pixels = []
    for color in STRAND_COLORS:
        pixels.extend([color] * LEDS_PER_STRAND)
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
    print(f"Total LEDs:  {len(pixels)} ({len(STRAND_COLORS)} x {LEDS_PER_STRAND})")
    print(f"Chunks:      {chunks} packet(s) per frame, up to {LEDS_PER_CHUNK} LEDs each")
    print(f"Strands:     red, orange, yellow, green, cyan, blue, purple, magenta")
    print("Sending continuously. Ctrl+C to stop.")

    try:
        while True:
            send_dnrgb(sock, pixels)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping.")


if __name__ == "__main__":
    main()

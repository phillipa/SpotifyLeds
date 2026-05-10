import sacn
import time

# DOUBLE CHECK THIS IP in your WLED 'Info' tab!
WLED_IP = "192.168.1.124"  # Replace with your ESP32 IP

sender = sacn.sACNsender()
sender.start()
time.sleep(1)  # Give the sender time to initialize

# Activate universe 1
sender.activate_output(1)
time.sleep(0.5)  # Give it time to activate

sender[1].multicast = False
sender[1].destination_host = WLED_IP

print(f"Sending RED to {WLED_IP}. Check WLED 'Peek' tab or look at the LEDs!")
print(f"Make sure E1.31 is enabled in WLED Config → Sync Interfaces")
print(f"Multicast: {sender[1].multicast}, Host: {sender[1].destination_host}\n")

try:
    count = 0
    while True:
        # We send 30 values (10 LEDs * 3 colors)
        # Some WLED versions expect the first byte to be a 'null' or padding 
        # if the start address is 1. Let's try a standard array first:
        test_data = (255, 0, 0) * 30        
        sender[1].dmx_data = test_data
        count += 1
        if count % 20 == 0:
            print(f"Packets sent: {count}")
        time.sleep(0.05)
except KeyboardInterrupt:
    print(f"\nStopped. Total packets sent: {count}")
    sender.stop()




import sacn
import pyaudio
import numpy as np
import time

# --- CONFIGURATION ---
WLED_IP = "192.168.1.124"  # Replace with your ESP32 IP
NUM_LEDS = 30            # Your prototype count
BLACKHOLE_INDEX = 0      # Change this to the index from Step 1

# --- SETUP E1.31 SENDER ---
sender = sacn.sACNsender()
sender.start()
sender.activate_output(1)
sender[1].multicast = False
sender[1].destination_host = WLED_IP
sender[1].universe = 1
sender[1].destination_ip = WLED_IP
sender[1].port = 5568
out = sender[1]
print('output type:', type(out))
print('attrs:', [a for a in dir(out) if 'dest' in a or 'host' in a or 'ip' in a or 'multi' in a or 'universe' in a])
print('destination_host:', getattr(out,'destination_host',None))
print('destination_ip:', getattr(out,'destination_ip',None))
print('multicast:', getattr(out,'multicast',None))
print('universe:', getattr(out,'universe',None))
print('port:', getattr(out,'port',None))
print('has dmx_data:', hasattr(out,'dmx_data'))


# Test: Flash LEDs red to verify connection
print("Testing LED connection - LEDs should flash red for 5 seconds...")
sender[1].dmx_data = (255, 0, 0) * NUM_LEDS
time.sleep(5)
sender[1].dmx_data = (0, 0, 0) * NUM_LEDS
print("Test complete. If LEDs didn't flash, check WLED sACN settings.")

# --- SETUP AUDIO CAPTURE ---
p = pyaudio.PyAudio()

# List available devices to find BlackHole index
print("Available audio devices:")
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    print(f"{i}: {info['name']}")

print(f"\nUsing BlackHole device at index {BLACKHOLE_INDEX}.\n")
stream = p.open(format=pyaudio.paFloat32, 
                channels=2, 
                rate=44100,
                input=True, 
                input_device_index=BLACKHOLE_INDEX,
                frames_per_buffer=1024)

print("Streaming Spotify... Press Ctrl+C to stop.")


try:
   # for i in range(0,5):
      while True:
          # Read the audio data from BlackHole
        data = np.frombuffer(stream.read(1024, exception_on_overflow=False), dtype=np.float32)
        
        if len(data) == 0:
            brightness = 0
        else:
            # Calculate the volume (RMS)
            rms = np.sqrt(np.mean(data**2))
            
            if np.isnan(rms) or np.isinf(rms):
                brightness = 0
            else:
                # Scale the volume to a 0-255 brightness value
                # Sensitivity: Adjust '1' lower for more reactivity, higher for less
                brightness = int(np.clip(rms * 255, 0, 255))
        
        # Create a basic 'Music Pulse' - Red for Bass/Volume
        # Structure is (R, G, B) * Number of LEDs
        led_data = (brightness, 0, int(brightness/2)) * NUM_LEDS
        
        # Debug: print brightness occasionally
        if not hasattr(locals(), 'last_brightness') or abs(brightness - last_brightness) > 5:
            print(f"Brightness: {brightness}")
            last_brightness = brightness
        
        # Ship it to the ESP32
        sender[1].dmx_data = led_data
        
        # Small delay to keep the Wi-Fi from flooding
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nStopping...")
    stream.stop_stream()
    stream.close()
    p.terminate()
    sender.stop()
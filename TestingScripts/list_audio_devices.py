import pyaudio

# Initialize PyAudio
p = pyaudio.PyAudio()

# List all available audio devices
print("Available audio devices:")
print("-" * 80)

for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    print(f"Device {i}:")
    print(f"  Name: {info['name']}")
    print(f"  Channels: {info['maxInputChannels']} input, {info['maxOutputChannels']} output")
    print(f"  Sample rate: {info['defaultSampleRate']}")
    print()

p.terminate()

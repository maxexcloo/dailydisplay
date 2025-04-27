# boot.py - Runs on boot-up
import network
import time
import config
import machine
import esp # Optional: For disabling ESP-NOW on boot if needed

# Disable ESP-NOW on boot if it interferes with Wi-Fi
# esp.osdebug(None) # Uncomment if you experience Wi-Fi issues

print("Booting device...")

# Configure Wi-Fi station interface
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# Check if already connected
if not wlan.isconnected():
    print(f"Connecting to Wi-Fi network: {config.WIFI_SSID}")
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

    # Wait for connection with a timeout
    max_wait = 15  # seconds
    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
        print(".")
        time.sleep(1)

    # Check connection status
    if wlan.status() != 3:
        print("Wi-Fi connection failed!")
        # Optional: Enter deep sleep on failure or handle differently
        # machine.deepsleep(60000) # Sleep for 1 minute and retry
    else:
        print("Wi-Fi connected successfully!")
        status = wlan.ifconfig()
        print(f"IP Address: {status[0]}")
else:
    print("Wi-Fi already connected.")
    status = wlan.ifconfig()
    print(f"IP Address: {status[0]}")

# Note: Wi-Fi connection established here will persist until disconnect/reset
# main.py will use this existing connection

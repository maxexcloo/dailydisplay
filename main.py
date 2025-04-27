# main.py - Main application logic
import time
import machine
import network
import urequests
import gc # Garbage Collector

# Import device-specific libraries (ensure these are in /lib)
try:
    from lib import m5epd
    from lib import upng
except ImportError:
    print("Error: Required libraries (m5epd.py, upng.py) not found in /lib folder.")
    # Optional: Halt execution or indicate error permanently
    while True: time.sleep(1)

import config

# --- Global Variables ---
wlan = network.WLAN(network.STA_IF)

# --- EPD Initialization ---
# Initialize the EPD driver
# Note: Pin configurations might vary slightly depending on the exact M5Paper S3
# hardware revision or the specific m5epd library version. Check library docs.
try:
    epd = m5epd.EPD()
    print("EPD driver initialized.")
    epd.set_rotation(config.DISPLAY_ROTATION)
    # Clear the display initially (optional, depends on library)
    # epd.clear_frame() # Or epd.fill(0xFF) depending on library API
    # print("EPD cleared.")
except Exception as e:
    print(f"Error initializing EPD: {e}")
    # Optional: Halt or indicate error
    while True: time.sleep(1)


# --- Functions ---

def connect_wifi():
    """Ensures Wi-Fi is connected."""
    if not wlan.isconnected():
        print("Wi-Fi disconnected. Reconnecting...")
        wlan.active(True) # Ensure interface is active
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        max_wait = 15
        while max_wait > 0:
            if wlan.status() < 0 or wlan.status() >= 3:
                break
            max_wait -= 1
            print(".")
            time.sleep(1)
        if wlan.status() != 3:
            print("Wi-Fi reconnection failed!")
            return False
        print("Wi-Fi reconnected.")
    return True

def fetch_image_data(url):
    """Fetches image data from the specified URL."""
    print(f"Fetching image from: {url}")
    try:
        response = urequests.get(url, timeout=20) # Increased timeout for image download
        if response.status_code == 200:
            print(f"Image fetched successfully ({len(response.content)} bytes).")
            return response.content
        else:
            print(f"Error fetching image: HTTP Status {response.status_code}")
            return None
    except Exception as e:
        print(f"Error during image request: {e}")
        return None

def display_png(png_data):
    """Decodes PNG data and displays it on the EPD."""
    if not png_data:
        print("No PNG data to display.")
        return False

    print("Decoding PNG...")
    try:
        # Use the upng library to decode
        png = upng.UPNG(png_data)
        png.decode() # Decode the image data
        width, height = png.get_width(), png.get_height()
        print(f"PNG decoded: {width}x{height}, Format: {png.get_format()}")

        # Check if dimensions match the expected display size
        # Note: m5epd library might handle scaling or require exact match.
        # Assuming the library expects a buffer matching its dimensions (960x540 for M5Paper S3)
        if width != 960 or height != 540:
             print(f"Warning: PNG dimensions ({width}x{height}) differ from expected (960x540).")
             # Depending on m5epd, this might fail or draw partially.
             # Add resizing logic here if needed and possible with available memory/libs.

        # Get the pixel data (assuming grayscale format suitable for EPD)
        # The format might be upng.GREYSCALE, upng.PALETTE, etc.
        # We need to convert this to a format m5epd understands, likely a FrameBuffer.
        # This conversion is the trickiest part and depends heavily on the m5epd API.

        # --- Example using FrameBuffer (adjust based on m5epd API) ---
        # Create a FrameBuffer matching the EPD dimensions and format (e.g., MONO_HLSB)
        # fb_format = framebuf.MONO_HLSB # Example format, check m5epd docs
        # fb = framebuf.FrameBuffer(bytearray(width * height // 8), width, height, fb_format)

        # Get the raw pixel buffer from upng
        pixel_buffer = png.get_buffer()

        # --- Direct drawing if m5epd supports raw buffer ---
        # Some EPD libraries might allow drawing directly from a compatible buffer
        # Check if png.get_format() output is directly usable.
        # Example: If m5epd expects a bytearray of grayscale pixels (0-255)
        if png.get_format() == upng.GREYSCALE:
             print("Attempting to draw grayscale buffer directly...")
             # The m5epd library needs a method like draw_buffer or draw_frame
             # epd.draw_frame(pixel_buffer) # Hypothetical API call
             # Or maybe it needs coordinates:
             # epd.draw_buffer(0, 0, width, height, pixel_buffer) # Hypothetical
             # *** This part requires specific knowledge of the m5epd API ***
             # For now, let's assume a method exists. Replace with actual call.
             epd.draw_frame(pixel_buffer) # Placeholder - REPLACE WITH ACTUAL API
             print("Buffer sent to EPD driver.")
        else:
             print(f"Error: PNG format ({png.get_format()}) not directly supported for drawing. Manual conversion needed.")
             # Implement conversion from png format to EPD buffer format here if necessary.
             return False

        # Trigger the display update
        print("Updating EPD display...")
        epd.display_frame() # Or epd.update() / epd.refresh() - check API
        print("EPD display update requested.")
        return True

    except Exception as e:
        print(f"Error decoding or displaying PNG: {e}")
        traceback.print_exc()
        return False
    finally:
        # Clean up memory explicitly
        png = None
        pixel_buffer = None
        gc.collect()

# --- Main Loop ---
while True:
    gc.collect() # Collect garbage before starting loop iteration
    print("\n--- Starting Update Cycle ---")

    if not connect_wifi():
        print("Failed to connect to Wi-Fi. Entering deep sleep and retrying later.")
        machine.deepsleep(config.UPDATE_INTERVAL_SECONDS * 1000)

    # Fetch the image
    image_data = fetch_image_data(config.IMAGE_URL)

    # Display the image if fetched successfully
    if image_data:
        display_success = display_png(image_data)
        if not display_success:
            print("Failed to display the new image.")
            # Optional: Display a cached image or an error message on screen
    else:
        print("Failed to fetch image data.")
        # Optional: Display a cached image or an error message on screen

    # Clean up image data memory
    image_data = None
    gc.collect()

    # Disconnect Wi-Fi (optional, saves power during sleep)
    # print("Disconnecting Wi-Fi...")
    # wlan.disconnect()
    # wlan.active(False)
    # print("Wi-Fi disconnected.")

    # Enter deep sleep
    sleep_ms = config.UPDATE_INTERVAL_SECONDS * 1000
    print(f"Entering deep sleep for {config.UPDATE_INTERVAL_SECONDS} seconds...")
    machine.deepsleep(sleep_ms)

    # --- Code execution stops here until wake-up ---

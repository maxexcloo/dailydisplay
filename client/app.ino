/**
 * M5PaperS3 E-Ink Dashboard Client (using FASTEPD Library)
 *
 * Fetches a grayscale PNG from a web service, decodes using PNGdec,
 * and displays using FASTEPD in 4bpp mode. Performs partial updates
 * every minute and a full refresh every 15 minutes. Logs errors to Serial.
 *
 * Requires: WiFi, HTTPClient, FastEPD, PNGdec libraries.
 * Assumes PSRAM is enabled for the board.
 */

// Standard Library Includes
#include <string.h>

// Third-Party Library Includes
#include <FastEPD.h>
#include <HTTPClient.h>
#include <PNGdec.h>
#include <WiFi.h>
#include <esp_heap_caps.h>

// ==============================================================================
// User Configuration
// ==============================================================================
const char *ssid = "Schnitzel WiFi";
const char *password = "wifiwifi";
const char *serverUrl = "http://192.168.0.167:5050/display/test";
const unsigned long REFRESH_INTERVAL_MS = 60 * 1000;           // 1 minute
const unsigned long FULL_REFRESH_INTERVAL_MS = 15 * 60 * 1000; // 15 minutes

// ==============================================================================
// Display & Decoder Configuration
// ==============================================================================
const int SCREEN_WIDTH = 960;
const int SCREEN_HEIGHT = 540;
const int TEXT_MARGIN_X = 10;
const int TEXT_MARGIN_Y = 10;
const int HTTP_TIMEOUT_MS = 30 * 1000;         // 30 seconds
const int WIFI_CONNECT_RETRIES = 3;            // Number of connection attempts before giving up
const int WIFI_CONNECT_TIMEOUT_MS = 30 * 1000; // 30 seconds

// ==============================================================================
// Global Objects & Buffers
// ==============================================================================
FASTEPD epaper;
PNG png;
uint8_t *png_buffer = nullptr; // Buffer for downloaded PNG, allocated in PSRAM if possible
unsigned long lastFullRefreshMillis = 0;
unsigned long lastRefreshMillis = 0;
uint16_t png_callback_rgb565_buffer[SCREEN_WIDTH]; // Global buffer for PNG callback line

// ==============================================================================
// Helper Functions (Sorted Alphabetically)
// ==============================================================================

/**
 * @brief Connects to WiFi, showing status on display. Returns true on success.
 */
bool connectWifi()
{
  // Don't try to reconnect if already connected
  if (WiFi.status() == WL_CONNECTED)
  {
    return true;
  }

  displayTextMessage("Connecting to WiFi:\n" + String(ssid));
  Serial.printf("Connecting to WiFi: %s ", ssid);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int retries = 0;
  unsigned long startMillis = millis();
  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
    if (millis() - startMillis > WIFI_CONNECT_TIMEOUT_MS)
    {
      Serial.println("\nFailed to connect to WiFi (Timeout).");
      displayTextMessage("WiFi Connect Failed\n(Timeout)");

      // If we've tried multiple times, give up
      if (++retries >= WIFI_CONNECT_RETRIES)
      {
        return false;
      }

      // Otherwise try again
      Serial.println("Retrying connection...");
      WiFi.disconnect();
      delay(1000);
      WiFi.begin(ssid, password);
      startMillis = millis();
    }
  }
  Serial.println("\nWiFi connected successfully.");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  displayTextMessage("WiFi Connected!\nIP: " + WiFi.localIP().toString());
  return true;
}

/**
 * @brief Displays a message at the top-left, clearing the screen first.
 * @param message The string message to display. Handles newlines.
 */
void displayTextMessage(const String &message)
{
  epaper.fillScreen(0xf);   // White background
  epaper.setTextColor(0x0); // Black text
  epaper.setFont(FONT_12x16);

  int yPos = TEXT_MARGIN_Y;
  int lineStart = 0;

  for (int i = 0; i <= message.length(); i++)
  {
    if (i == message.length() || message.charAt(i) == '\n')
    {
      epaper.setCursor(TEXT_MARGIN_X, yPos);
      epaper.print(message.substring(lineStart, i));
      yPos += 20; // Adjust line spacing
      lineStart = i + 1;
    }
  }

  epaper.fullUpdate(true); // Refresh display after drawing text
}

/**
 * @brief Check if WiFi is connected and attempt to reconnect if needed
 * @return true if connected, false if connection failed
 */
bool ensureWiFiConnected()
{
  if (WiFi.status() != WL_CONNECTED)
  {
    Serial.println("WiFi connection lost. Attempting to reconnect...");
    return connectWifi();
  }
  return true;
}

/**
 * @brief Safely frees the PNG buffer if allocated
 */
void freePngBuffer()
{
  if (png_buffer)
  {
    free(png_buffer);
    png_buffer = nullptr;
  }
}

/**
 * @brief PNG Decoder Callback: Converts RGB565 line to 4bpp grayscale
 * and writes directly into the epaper buffer.
 */
void pngDrawCallback(PNGDRAW *pDraw)
{
  uint8_t *pBuffer = epaper.currentBuffer();
  if (!pBuffer)
    return;

  // Validate dimensions
  if (pDraw->iWidth > SCREEN_WIDTH || pDraw->y >= SCREEN_HEIGHT)
  {
    Serial.printf("PNG dimensions out of bounds: width=%d, y=%d\n", pDraw->iWidth, pDraw->y);
    return;
  }

  const int BITMAP_PITCH = SCREEN_WIDTH / 2; // Bytes per row for 4bpp buffer

  png.getLineAsRGB565(pDraw, png_callback_rgb565_buffer, PNG_RGB565_LITTLE_ENDIAN, 0xffffffff);

  uint16_t *s = png_callback_rgb565_buffer;
  int y = pDraw->y;
  int w = pDraw->iWidth;
  int x_start_byte = 0; // Assume line starts at x=0
  int num_bytes = w / 2;

  if (y < 0 || y >= SCREEN_HEIGHT)
    return;
  if (num_bytes > BITMAP_PITCH)
    num_bytes = BITMAP_PITCH;

  uint8_t *d = &pBuffer[(y * BITMAP_PITCH) + x_start_byte];

  for (int i = 0; i < num_bytes; i++)
  {
    uint16_t p1 = *s++;
    int g0 = ((p1 & 0x7e0) >> 5) + (p1 >> 11) + (p1 & 0x1f);
    g0 >>= 3;
    if (g0 > 15)
      g0 = 15;

    uint16_t p2 = *s++;
    int g1 = ((p2 & 0x7e0) >> 5) + (p2 >> 11) + (p2 & 0x1f);
    g1 >>= 3;
    if (g1 > 15)
      g1 = 15;

    *d++ = (uint8_t)((g0 << 4) | g1); // Pack pixels
  }
}

/**
 * @brief Fetches, decodes, and displays the dashboard image. Returns true on success.
 */
bool updateDisplay()
{
  bool success = false;
  unsigned long currentTime = millis(); // Capture current time once

  // Make sure we're connected before proceeding
  if (!ensureWiFiConnected())
  {
    return false;
  }

  HTTPClient http;
  http.begin(serverUrl);
  http.setTimeout(HTTP_TIMEOUT_MS);
  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK)
  {
    int len = http.getSize();
    if (len <= 0)
    {
      Serial.println("Error: Content length is 0 or unknown.");
      displayTextMessage("Error: Empty content");
      http.end();
      return false;
    }

    // Always free the buffer before allocating new memory
    freePngBuffer();

    png_buffer = (uint8_t *)heap_caps_malloc(len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);

    if (!png_buffer)
    {
      png_buffer = (uint8_t *)malloc(len);
    }

    if (!png_buffer)
    {
      Serial.printf("Error: Failed to allocate %d bytes for PNG buffer.\n", len);
      displayTextMessage("Error: Memory allocation failed");
      http.end();
      return false;
    }

    WiFiClient *stream = http.getStreamPtr();
    int bytes_read = stream->readBytes(png_buffer, len);
    http.end();

    if (bytes_read != len)
    {
      Serial.printf("Error: PNG download incomplete. Read %d / %d bytes.\n", bytes_read, len);
      displayTextMessage("Error: PNG download incomplete");
      freePngBuffer();
      return false;
    }

    int rc = png.openRAM(png_buffer, len, pngDrawCallback);

    if (rc == PNG_SUCCESS)
    {
      rc = png.decode(nullptr, 0);
      png.close();

      if (rc == PNG_SUCCESS)
      {
        Serial.println("PNG decoded successfully.");

        // Handle the millis() overflow case (occurs after ~49 days)
        bool isFullRefresh = false;

        // Check if lastFullRefreshMillis is greater than currentTime (overflow occurred)
        if (lastFullRefreshMillis > currentTime)
        {
          isFullRefresh = true;
        }
        // Normal case - check if enough time has passed for full refresh
        else if ((currentTime - lastFullRefreshMillis >= FULL_REFRESH_INTERVAL_MS) ||
                 (lastFullRefreshMillis == 0))
        {
          isFullRefresh = true;
        }

        if (isFullRefresh)
        {
          Serial.println("Initiating FULL screen update...");
          epaper.fullUpdate(false);
          lastFullRefreshMillis = currentTime; // Reset full refresh timer *after* update
        }
        else
        {
          Serial.println("Initiating PARTIAL screen update...");
          epaper.fullUpdate(true);
        }

        success = true;
      }
      else
      {
        Serial.printf("Error: PNG decode failed. Code: %d\n", rc);
        displayTextMessage("Error: PNG decode failed\nCode: " + String(rc));
      }
    }
    else
    {
      Serial.printf("Error: PNG open failed. Code: %d\n", rc);
      displayTextMessage("Error: PNG open failed\nCode: " + String(rc));
    }

    freePngBuffer(); // Always free the buffer after use
  }
  else
  {
    Serial.printf("HTTP request failed. Error: %s (Code: %d)\n", http.errorToString(httpCode).c_str(), httpCode);
    displayTextMessage("HTTP request failed\nCode: " + String(httpCode));
    http.end(); // Ensure http client is ended on error too
  }

  return success;
}

// ==============================================================================
// Arduino Setup & Loop
// ==============================================================================

void setup()
{
  Serial.begin(115200);
  Serial.println("\nM5PaperS3 Dashboard Client Starting (FASTEPD)...");

  epaper.initPanel(BB_PANEL_M5PAPERS3);
  epaper.setMode(BB_MODE_4BPP);
  epaper.fillScreen(0xf);
  epaper.fullUpdate(false);

  if (!connectWifi())
  {
    Serial.println("Initial WiFi connection failed. Will retry in main loop.");
    displayTextMessage("WiFi connection failed.\nWill retry in main loop.");
  }
  else if (!updateDisplay())
  {
    Serial.println("Initial display update failed.");
    displayTextMessage("Initial data fetch failed.\nWill retry in main loop.");
  }

  // Initialize timers after first attempt
  lastRefreshMillis = millis();
  lastFullRefreshMillis = lastRefreshMillis; // Ensure first update counts as full refresh reference

  Serial.println("Setup complete. Entering main loop.");
}

void loop()
{
  unsigned long currentTime = millis();

  // Handle millis() overflow (occurs after ~49 days)
  if (lastRefreshMillis > currentTime)
  {
    // Overflow occurred, reset timers
    lastRefreshMillis = currentTime;
    lastFullRefreshMillis = currentTime;
    Serial.println("millis() overflow detected, resetting timers");
  }

  if (currentTime - lastRefreshMillis >= REFRESH_INTERVAL_MS)
  {
    lastRefreshMillis = currentTime;
    if (!updateDisplay())
    { // Attempt the update
      Serial.println("Update failed, will retry on next interval.");
    }
  }

  delay(100); // Yield time
}

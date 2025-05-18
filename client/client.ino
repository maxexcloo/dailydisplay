/**
 * M5Paper S3 E-Ink Dashboard Client
 *
 * Fetches a grayscale PNG from a web service, decodes, and displays it.
 * Performs a full refresh every hour (XX:00).
 * Logs errors to Serial.
 *
 * Requires: WiFi, HTTPClient, FastEPD, PNGdec, NTPClient libraries.
 * Assumes PSRAM is enabled.
 */

// Standard Library Includes
#include <string.h>

// Third-Party Library Includes
#include <esp_heap_caps.h>
#include <FastEPD.h>
#include <HTTPClient.h>
#include <NTPClient.h>
#include <PNGdec.h>
#include <WiFi.h>
#include <WiFiUdp.h>

// ==============================================================================
// Configuration
// ==============================================================================

// Display Configuration
const int SCREEN_WIDTH = 960;
const int SCREEN_HEIGHT = 540;
const int TEXT_MARGIN_X = 10;
const int TEXT_MARGIN_Y = 10;

// Network Configuration
const int HTTP_TIMEOUT_MS = 30 * 1000;
const int WIFI_CONNECT_RETRIES = 3;
const int WIFI_CONNECT_TIMEOUT_MS = 20 * 1000;
const char* WIFI_SSID = "";
const char* WIFI_PASSWORD = "";

// NTP Configuration
const char* NTP_SERVER = "pool.ntp.org";
const unsigned long NTP_SYNC_INTERVAL_MS = 60 * 60 * 1000;

// Server Configuration
const char* SERVER_URL = "";

// ==============================================================================
// Global Objects & Buffers
// ==============================================================================
FASTEPD epaper;
PNG png;
uint8_t* png_buffer = nullptr;                      // Buffer for the downloaded PNG
uint16_t png_callback_rgb565_buffer[SCREEN_WIDTH];  // Line buffer for PNG decoding

WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, NTP_SERVER, 0, NTP_SYNC_INTERVAL_MS);  // UTC

int lastSuccessfulRefreshHour = -1;      // Tracks the hour of the last successful image refresh
unsigned long lastNTPAttemptMillis = 0;  // For periodic NTP sync attempts in loop

// ==============================================================================
// Helper Functions
// ==============================================================================

/**
 * @brief Connects to WiFi with retries.
 * @return True if connected, false otherwise.
 */
bool connectWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }
  WiFi.mode(WIFI_STA);
  Serial.printf("Connecting to WiFi: %s\n", WIFI_SSID);

  for (int attempt = 0; attempt < WIFI_CONNECT_RETRIES; ++attempt) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    unsigned long connectStartMillis = millis();
    Serial.printf("Attempt %d... ", attempt + 1);
    while (WiFi.status() != WL_CONNECTED && (millis() - connectStartMillis < WIFI_CONNECT_TIMEOUT_MS)) {
      delay(500);
      Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nWiFi connected. IP: " + WiFi.localIP().toString());
      displayTextMessage("WiFi Connected\nIP: " + WiFi.localIP().toString());
      return true;
    } else {
      Serial.println("\nWiFi connect failed.");
      WiFi.disconnect(true);
      delay(1000);
      if (attempt < WIFI_CONNECT_RETRIES - 1) {
        displayTextMessage("WiFi Fail. Retry...");
      }
    }
  }
  Serial.println("WiFi connection failed after all retries.");
  displayTextMessage("WiFi Connect Failed");
  return false;
}

/**
 * @brief Displays a message on the E-Ink screen.
 */
void displayTextMessage(const String& message) {
  epaper.fillScreen(0xf);    // White background
  epaper.setTextColor(0x0);  // Black text
  epaper.setFont(FONT_12x16);
  int yPos = TEXT_MARGIN_Y;
  int lineStart = 0;
  int fontHeight = 16;

  for (int i = 0; i <= message.length(); i++) {
    if (i == message.length() || message.charAt(i) == '\n') {
      epaper.setCursor(TEXT_MARGIN_X, yPos);
      epaper.print(message.substring(lineStart, i));
      yPos += fontHeight + 4;
      lineStart = i + 1;
    }
  }
  epaper.fullUpdate(true);
}

/**
 * @brief Ensures WiFi is connected, trying to reconnect if necessary.
 * @return True if connected, false otherwise.
 */
bool ensureWiFiConnected() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected. Reconnecting...");
    return connectWifi();
  }
  return true;
}

/**
 * @brief Frees the PNG buffer from PSRAM/heap.
 */
void freePngBuffer() {
  if (png_buffer) {
    heap_caps_free(png_buffer);  // Use heap_caps_free for memory from heap_caps_malloc
    png_buffer = nullptr;
  }
}

/**
 * @brief PNG decoder callback. Converts RGB565 line to 4bpp grayscale
 * and writes directly into the epaper buffer.
 */
void pngDrawCallback(PNGDRAW* pDraw) {
  uint8_t* pBuffer = epaper.currentBuffer();
  // Basic validation
  if (!pBuffer || pDraw->y >= SCREEN_HEIGHT || pDraw->iWidth <= 0) return;

  // Ensure decoded line width does not exceed screen width for buffer access
  int process_width = (pDraw->iWidth > SCREEN_WIDTH) ? SCREEN_WIDTH : pDraw->iWidth;

  const int BITMAP_PITCH = SCREEN_WIDTH / 2;  // Bytes per row for 4bpp buffer
  png.getLineAsRGB565(pDraw, png_callback_rgb565_buffer, PNG_RGB565_LITTLE_ENDIAN, 0xffffffff);

  uint16_t* s = png_callback_rgb565_buffer;          // Source: RGB565 pixels
  uint8_t* d = &pBuffer[(pDraw->y * BITMAP_PITCH)];  // Destination: E-Paper buffer for current line

  for (int x = 0; x < process_width / 2; x++) {  // Process two pixels at a time
    uint16_t p1 = *s++;
    // Average R,G,B components, then scale to 4-bit (0-15)
    int g0 = (((p1 & 0xF800) >> 11) + ((p1 & 0x07E0) >> 5) + (p1 & 0x001F)) / 3;
    g0 >>= 1;
    if (g0 > 15) g0 = 15;

    uint16_t p2 = *s++;
    int g1 = (((p2 & 0xF800) >> 11) + ((p2 & 0x07E0) >> 5) + (p2 & 0x001F)) / 3;
    g1 >>= 1;
    if (g1 > 15) g1 = 15;

    *d++ = (uint8_t)((g0 << 4) | g1);  // Pack two 4-bit pixels into one byte
  }

  // Handle odd width: process the last pixel if width is odd
  if (process_width % 2 == 1) {
    uint16_t p1 = *s;
    int g0 = (((p1 & 0xF800) >> 11) + ((p1 & 0x07E0) >> 5) + (p1 & 0x001F)) / 3;
    g0 >>= 1;
    if (g0 > 15) g0 = 15;
    // Assuming buffer was cleared (e.g. to white 0xFF), preserve the second nibble
    *d = (uint8_t)((g0 << 4) | (*d & 0x0F));
  }
}

/**
 * @brief Fetches, decodes, and displays the PNG image from the server.
 * @return True on success, false on failure.
 */
bool updateDashboardImage() {
  if (!ensureWiFiConnected()) {
    return false;
  }

  Serial.println("Fetching image...");
  displayTextMessage("Fetching image...");

  HTTPClient http;
  http.begin(SERVER_URL);
  http.setTimeout(HTTP_TIMEOUT_MS);
  int httpCode = http.GET();
  bool success = false;

  if (httpCode == HTTP_CODE_OK) {
    int len = http.getSize();
    if (len <= 0) {
      Serial.println("Error: Empty content from server.");
      displayTextMessage("Error: Empty Content");
    } else {
      freePngBuffer();
      png_buffer = (uint8_t*)heap_caps_malloc(len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
      if (!png_buffer) png_buffer = (uint8_t*)malloc(len);

      if (!png_buffer) {
        Serial.printf("Error: Failed to allocate %d bytes for PNG.\n", len);
        displayTextMessage("Error: Mem Alloc");
      } else {
        WiFiClient* stream = http.getStreamPtr();
        int bytes_read = stream->readBytes(png_buffer, len);

        if (bytes_read != len) {
          Serial.printf("Error: PNG download incomplete (%d/%d bytes).\n", bytes_read, len);
          displayTextMessage("Error: PNG Download");
        } else {
          Serial.println("PNG downloaded. Decoding...");
          displayTextMessage("Decoding image...");
          int rc = png.openRAM(png_buffer, len, pngDrawCallback);
          if (rc == PNG_SUCCESS) {
            rc = png.decode(nullptr, 0);
            png.close();
            if (rc == PNG_SUCCESS) {
              Serial.println("PNG decoded. Updating screen...");
              displayTextMessage("Updating screen...");
              epaper.fullUpdate(false);
              Serial.println("Screen update complete.");
              success = true;
            } else {
              Serial.printf("Error: PNG decode failed (Code: %d).\n", rc);
              displayTextMessage("Error: PNG Decode");
            }
          } else {
            Serial.printf("Error: PNG open failed (Code: %d).\n", rc);
            displayTextMessage("Error: PNG Open");
          }
        }
        freePngBuffer();
      }
    }
  } else {
    Serial.printf("HTTP GET failed (Code: %d): %s\n", httpCode, http.errorToString(httpCode).c_str());
    displayTextMessage("HTTP Error: " + String(httpCode));
  }

  http.end();
  return success;
}

// ==============================================================================
// Setup & Loop
// ==============================================================================
void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 2000)
    ;
  Serial.println("\nM5Paper S3 Dashboard Client");

  epaper.initPanel(BB_PANEL_M5PAPERS3);
  epaper.setMode(BB_MODE_4BPP);
  epaper.fillScreen(0xf);
  epaper.fullUpdate(false);

  if (connectWifi()) {
    Serial.println("Initializing NTP...");
    displayTextMessage("WiFi OK. NTP Init...");
    timeClient.begin();
    if (timeClient.forceUpdate()) {
      Serial.println("NTP time: " + timeClient.getFormattedTime());
      displayTextMessage("NTP OK. Waiting...");
    } else {
      Serial.println("NTP initial sync failed.");
      displayTextMessage("NTP Sync Failed");
    }
  }
  lastNTPAttemptMillis = millis();
  Serial.println("Setup complete.");
}

void loop() {
  unsigned long currentTime = millis();

  if (lastNTPAttemptMillis > currentTime) {
    lastNTPAttemptMillis = currentTime;
  }

  if (WiFi.status() == WL_CONNECTED && (currentTime - lastNTPAttemptMillis >= (NTP_SYNC_INTERVAL_MS / 2) || lastNTPAttemptMillis == 0)) {
    if (timeClient.update()) {
      Serial.println("NTP time synced: " + timeClient.getFormattedTime());
    } else {
      Serial.println("NTP sync attempt failed.");
    }
    lastNTPAttemptMillis = currentTime;
  }

  if (WiFi.status() == WL_CONNECTED && timeClient.getEpochTime() > (3600UL * 24 * 365 * 50)) {
    int currentHour = timeClient.getHours();

    if (currentHour != lastSuccessfulRefreshHour) {
      Serial.printf("Scheduled refresh: %02d:00\n", currentHour);
      if (updateDashboardImage()) {
        lastSuccessfulRefreshHour = currentHour;
      } else {
        Serial.println("Scheduled image update failed. Will retry next hour.");
      }
    }
  } else if (WiFi.status() != WL_CONNECTED) {
    ensureWiFiConnected();
  }

  delay(5000);
}

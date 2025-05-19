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

// General Configuration
const unsigned long MAIN_LOOP_DELAY_MS = 30 * 1000;
const char* SERVER_URL = "";

// Network Configuration
const char* WIFI_SSID = "";
const char* WIFI_PASSWORD = "";
const unsigned long WIFI_CONNECTING_MESSAGE_INTERVAL_MS = 30 * 1000;
const unsigned long WIFI_RETRY_PAUSE_MS = 30 * 1000;

// NTP Configuration
const char* NTP_SERVER = "pool.ntp.org";
const unsigned long MIN_VALID_EPOCH_TIME = (3600UL * 24 * 365 * 50);
const unsigned long NTP_RETRY_PAUSE_MS = 30 * 1000;
const unsigned long NTP_SYNC_INTERVAL_MS = 60 * 60 * 1000;

// ==============================================================================
// Global Objects & Buffers
// ==============================================================================
FASTEPD epaper;
HTTPClient http;
PNG png;
WiFiUDP udp;
NTPClient timeClient(udp, NTP_SERVER, 0, NTP_SYNC_INTERVAL_MS);
int lastSuccessfulRefreshHour = -1;
uint8_t* png_buffer = nullptr;
uint16_t png_callback_rgb565_buffer[SCREEN_WIDTH];

// ==============================================================================
// Helper Functions
// ==============================================================================

bool connectWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  unsigned long lastDisplayMessageTime = 0;
  WiFi.mode(WIFI_STA);
  Serial.printf("Connecting to WiFi: %s (indefinite retries)...\n", WIFI_SSID);

  for (;;) {
    if (millis() - lastDisplayMessageTime >= WIFI_CONNECTING_MESSAGE_INTERVAL_MS || lastDisplayMessageTime == 0) {
      displayTextMessage("WiFi Connecting...");
      lastDisplayMessageTime = millis();
    }

    unsigned long connectStartMillis = millis();
    const unsigned long singleAttemptCycleTimeout = 30 * 1000;
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("Attempting WiFi.begin() sequence...");

    while (millis() - connectStartMillis < singleAttemptCycleTimeout) {
      if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi connected. IP: " + WiFi.localIP().toString());
        return true;
      }

      delay(500);
      Serial.print(".");
    }

    WiFi.disconnect(true);
    Serial.println("\nConnection attempt sequence timed out.");
    Serial.println("Waiting before next connection attempt...");
    delay(WIFI_RETRY_PAUSE_MS);
  }

  return false;
}

void displayTextMessage(const String& message) {
  int fontHeight = 16;
  int lineStart = 0;
  int yPos = TEXT_MARGIN_Y;
  epaper.fillScreen(0xf);
  epaper.setFont(FONT_12x16);
  epaper.setTextColor(0x0);

  for (int i = 0; i <= message.length(); i++) {
    if (i == message.length() || message.charAt(i) == '\n') {
      epaper.setCursor(TEXT_MARGIN_X, yPos);
      epaper.print(message.substring(lineStart, i));
      lineStart = i + 1;
      yPos += fontHeight + 4;
    }
  }

  epaper.fullUpdate(true);
}

void freePngBuffer() {
  if (png_buffer) {
    heap_caps_free(png_buffer);
    png_buffer = nullptr;
  }
}

void pngDrawCallback(PNGDRAW* pDraw) {
  uint8_t* pBuffer = epaper.currentBuffer();
  if (!pBuffer || pDraw->y >= SCREEN_HEIGHT || pDraw->iWidth <= 0) {
    return;
  }

  png.getLineAsRGB565(pDraw, png_callback_rgb565_buffer, PNG_RGB565_LITTLE_ENDIAN, 0xffffffff);

  const int bitmap_pitch = SCREEN_WIDTH / 2;
  int process_width = pDraw->iWidth;
  uint16_t* s = png_callback_rgb565_buffer;
  uint8_t* d = &pBuffer[(pDraw->y * bitmap_pitch)];

  for (int x = 0; x < process_width / 2; x++) {
    uint16_t p1_rgb565 = *s++;
    int g0_val = ((p1_rgb565 & 0x07E0) >> 5) + ((p1_rgb565 & 0xF800) >> 11) + (p1_rgb565 & 0x001F);
    g0_val >>= 3;
    if (g0_val > 15) g0_val = 15;

    uint16_t p2_rgb565 = *s++;
    int g1_val = ((p2_rgb565 & 0x07E0) >> 5) + ((p2_rgb565 & 0xF800) >> 11) + (p2_rgb565 & 0x001F);
    g1_val >>= 3;
    if (g1_val > 15) g1_val = 15;

    *d++ = (uint8_t)((g0_val << 4) | g1_val);
  }

  if (process_width % 2 == 1) {
    uint16_t p1_rgb565 = *s;
    int g0_val = ((p1_rgb565 & 0x07E0) >> 5) + ((p1_rgb565 & 0xF800) >> 11) + (p1_rgb565 & 0x001F);
    g0_val >>= 3;
    if (g0_val > 15) g0_val = 15;
    *d = (uint8_t)((g0_val << 4) | (*d & 0x0F));
  }
}

bool updateDashboardImage() {
  Serial.println("Fetching image...");
  http.begin(SERVER_URL);
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

      if (!png_buffer) {
        Serial.println("PSRAM allocation failed, trying internal RAM...");
        png_buffer = (uint8_t*)malloc(len);
      }

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
          Serial.println("PNG downloaded. Preparing to decode...");
          epaper.fillScreen(0xf);

          int rc = png.openRAM(png_buffer, len, pngDrawCallback);
          if (rc == PNG_SUCCESS) {
            if (png.getWidth() > SCREEN_WIDTH) {
              Serial.printf("Error: PNG width (%d) exceeds screen width (%d). Aborting decode.\n", png.getWidth(), SCREEN_WIDTH);
              png.close();
              displayTextMessage("Error: Image Too Wide\n(" + String(png.getWidth()) + "px > " + String(SCREEN_WIDTH) + "px)");
            } else {
              Serial.println("Decoding PNG into E-Paper buffer...");
              rc = png.decode(nullptr, 0);
              png.close();

              if (rc == PNG_SUCCESS) {
                Serial.println("PNG decoded successfully into E-Paper buffer.");
                Serial.println("Updating screen with image...");
                epaper.fullUpdate(true);
                Serial.println("Screen update complete.");
                success = true;
              } else {
                Serial.printf("Error: PNG decode failed (Code: %d).\n", rc);
                displayTextMessage("Error: PNG Decode");
              }
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

bool updateNTPTime(bool forceSync) {
  static unsigned long lastPeriodicNTPAttemptMillis = 0;
  unsigned long currentTime = millis();

  if (lastPeriodicNTPAttemptMillis > currentTime && lastPeriodicNTPAttemptMillis != 0) {
    lastPeriodicNTPAttemptMillis = currentTime;
  }

  if (forceSync) {
    Serial.println("NTP: Initializing and attempting first sync (will retry indefinitely)...");
    timeClient.begin();

    for (;;) {
      if (!connectWifi()) {
        Serial.println("NTP: WiFi connection lost during forced sync attempt. Retrying WiFi...");
        delay(WIFI_RETRY_PAUSE_MS);
        continue;
      }

      Serial.println("NTP: Attempting forceUpdate()...");
      if (timeClient.forceUpdate()) {
        Serial.println("NTP: Initial sync successful. Time: " + timeClient.getFormattedTime());
        return true;
      } else {
        Serial.println("NTP: Initial sync attempt failed.");
        displayTextMessage("NTP Sync Failed");
        Serial.println("NTP: Retrying...");
        delay(NTP_RETRY_PAUSE_MS);
      }
    }
  } else {
    if (!((currentTime - lastPeriodicNTPAttemptMillis >= (NTP_SYNC_INTERVAL_MS / 2)) || lastPeriodicNTPAttemptMillis == 0)) {
      return true;
    }

    if (!connectWifi()) {
      Serial.println("NTP: WiFi not connected for periodic update.");
      return false;
    }

    Serial.println("NTP: Attempting periodic update...");
    bool success = timeClient.update();
    lastPeriodicNTPAttemptMillis = currentTime;

    if (success) {
      Serial.println("NTP: Periodic sync successful. Time: " + timeClient.getFormattedTime());
      return true;
    } else {
      Serial.println("NTP: Periodic sync failed.");
      return false;
    }
  }

  return false;
}

// ==============================================================================
// Setup & Loop
// ==============================================================================
void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 2000) {}
  Serial.println("\nM5Paper S3 Dashboard Client");

  epaper.initPanel(BB_PANEL_M5PAPERS3);
  epaper.setMode(BB_MODE_4BPP);
  epaper.fillScreen(0xf);
  epaper.fullUpdate(false);

  connectWifi();
  updateNTPTime(true);

  Serial.println("Setup complete.");
}

void loop() {
  if (connectWifi()) {
    updateNTPTime(false);

    if (timeClient.getEpochTime() > MIN_VALID_EPOCH_TIME) {
      int currentHour = timeClient.getHours();

      if (currentHour != lastSuccessfulRefreshHour) {
        Serial.printf("Scheduled refresh: Current hour %02d:00, Last successful refresh hour: %02d:00\n", currentHour, lastSuccessfulRefreshHour);

        if (updateDashboardImage()) {
          lastSuccessfulRefreshHour = currentHour;
        } else {
          Serial.println("Scheduled image update failed. Will retry next hour.");
        }
      }
    } else {
      Serial.println("NTP time not yet valid for image refresh check.");
    }
  }

  delay(MAIN_LOOP_DELAY_MS);
}

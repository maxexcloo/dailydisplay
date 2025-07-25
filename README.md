# Daily Display

A personal dashboard system for E-Ink displays that shows calendar events and weather information. Built for M5Paper S3 devices with a Python Flask backend and Arduino client.

## Features

- **Calendar Integration**: Fetches events from CalDAV sources
- **Weather Display**: Current conditions and forecasts via Open-Meteo API
- **E-Ink Optimized**: Grayscale rendering optimized for E-Paper displays
- **Multi-User Support**: Multiple user configurations with personalized timezones and locations
- **Auto-Refresh**: Hourly updates with background data fetching
- **PNG Export**: Pre-rendered images for efficient display updates

## Architecture

### Server (`server/`)
- **Flask Application**: REST API server with template rendering
- **Background Tasks**: Scheduled data fetching and PNG generation
- **Data Sources**: CalDAV calendars and Open-Meteo weather API
- **Multi-threading**: Concurrent data fetching with thread-safe operations

### Client (`client/`)
- **Arduino/ESP32**: M5Paper S3 compatible firmware
- **WiFi Management**: Auto-reconnection and robust error handling
- **PNG Rendering**: Direct-to-display image decoding
- **NTP Sync**: Automatic time synchronization

## Quick Start

### Server Setup

1. **Environment Configuration**:
   ```bash
   export CONFIG='{
     "user_hash": {
       "timezone": "America/New_York",
       "weather_location": "New York, NY",
       "caldav_urls": "https://user:pass@calendar.example.com/cal.ics",
       "caldav_filter_names": "personal,work"
     }
   }'
   ```

2. **Run with Docker**:
   ```bash
   docker build -t dailydisplay .
   docker run -p 7777:7777 -e CONFIG="$CONFIG" dailydisplay
   ```

3. **Or run locally**:
   ```bash
   cd server
   python app.py
   ```

### Client Setup

1. **Configure WiFi and Server** in `client.ino`:
   ```cpp
   const char* WIFI_SSID = "YourWiFi";
   const char* WIFI_PASSWORD = "YourPassword";
   const char* SERVER_URL = "http://your-server:7777/your_hash.png";
   ```

2. **Flash to M5Paper S3** using Arduino IDE or PlatformIO

## API Endpoints

- `GET /` - Health check
- `GET /<user_hash>` - HTML dashboard view
- `GET /<user_hash>.png` - Pre-rendered PNG image

## Configuration

### Server Environment Variables

- `CONFIG`: JSON configuration for users (required)

### User Configuration Structure

```json
{
  "user_hash": {
    "timezone": "America/New_York",
    "weather_location": "New York, NY", 
    "caldav_urls": "url1,url2,url3",
    "caldav_filter_names": "calendar1,calendar2"
  }
}
```

### CalDAV URL Format

```
https://username:password@calendar.provider.com/path/to/calendar.ics
```

## Dependencies

### Server
- Flask (web framework)
- CalDAV (calendar access)
- Playwright (PNG rendering)
- iCalendar (event parsing)
- Gunicorn (WSGI server)

### Client
- FastEPD (E-Paper display)
- PNGdec (image decoding)
- HTTPClient (web requests)
- NTPClient (time sync)

## Production Deployment

### Docker (Recommended)
```bash
docker build -t dailydisplay .
docker run -d \
  --name dailydisplay \
  -p 7777:7777 \
  -e CONFIG="$CONFIG" \
  --restart unless-stopped \
  dailydisplay
```

### System Service
```bash
# Install dependencies
pip install -r requirements.txt

# Run with Gunicorn
gunicorn --bind 0.0.0.0:7777 app:app
```

## Troubleshooting

### Common Issues

1. **No Calendar Events**: Check CalDAV URL format and credentials
2. **Weather Not Loading**: Verify location name format 
3. **PNG Not Rendering**: Ensure Playwright dependencies are installed
4. **Client Connection Issues**: Check WiFi credentials and server URL

### Logs

Server logs show detailed information about:
- Configuration loading
- Data fetching attempts
- PNG generation status
- Error conditions

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is provided as-is for personal use. Please ensure compliance with third-party service terms when using CalDAV and weather APIs.

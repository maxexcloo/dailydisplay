# Claude Code Configuration

Daily Display project: E-ink dashboard with Python Flask server + Arduino ESP32 client.

## Commands

```bash
# Development
cd server && python app.py

# Docker
docker build -t dailydisplay .
docker run -p 7777:7777 -e CONFIG="$CONFIG" dailydisplay

# Test endpoints
curl http://localhost:7777/user_hash.png
```

## Code Organization

### Server (Python - app.py:665 lines)
- **File structure**: Dependencies → Imports → Constants → Globals → Helpers → Routes → Main
- **Functions**: Alphabetically sorted (private with `_` prefix, public without)
- **Naming**: `snake_case` functions, `ALL_CAPS` constants
- **Threading**: Global state protected with locks (`APP_DATA_LOCK`, `PNG_CACHE_LOCK`)

### Client (Arduino/C++ - client.ino:330 lines)  
- **File structure**: Includes → Constants → Globals → Functions → Setup/Loop
- **Functions**: Alphabetically sorted (`camelCase`)
- **Naming**: `ALL_CAPS` constants, `camelCase` everything else
- **Memory**: Explicit PNG buffer allocation with PSRAM fallback

## Configuration

Single `CONFIG` environment variable with JSON:
```json
{
  "user_hash": {
    "timezone": "America/New_York",
    "weather_location": "New York, NY",
    "caldav_urls": "https://user:pass@cal.com/cal.ics",
    "caldav_filter_names": "personal,work"
  }
}
```

## Architecture

**Data flow**: Background thread fetches calendar/weather → PNG pre-rendered → Client polls hourly
**Error handling**: Graceful degradation with extensive logging (109 print statements total)
**Threading**: Flask main thread + daemon background refresh thread

## Security Notes

- CalDAV credentials in URLs (private network intended)
- No authentication on endpoints
- For production: add auth, HTTPS, rate limiting

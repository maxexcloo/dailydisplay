# Claude Code Configuration

This file contains project-specific information for Claude Code to better understand and work with this codebase.

## Project Overview

Daily Display is a personal dashboard system with two main components:
- **Server**: Python Flask app that fetches calendar/weather data and generates PNG images
- **Client**: Arduino/ESP32 firmware for M5Paper S3 e-ink displays

## Common Commands

### Development
```bash
# Run server in development mode
cd server && python app.py

# Build and run with Docker
docker build -t dailydisplay .
docker run -p 7777:7777 -e CONFIG="$CONFIG" dailydisplay
```

### Testing
```bash
# Test server endpoints
curl http://localhost:7777/
curl http://localhost:7777/user_hash
curl http://localhost:7777/user_hash.png
```

## Code Patterns

### Organization & Naming Conventions

#### Server (Python - app.py:665 lines)
**File Structure (top to bottom):**
1. **Script dependencies** (lines 1-13): PEP 723 format with `# ///` blocks
2. **Imports** (lines 15-29): Standard library, then third-party, alphabetically within each group
3. **Configuration constants** (lines 40-111): ALL_CAPS with descriptive prefixes
4. **Global state initialization** (lines 116-121): App objects and threading locks
5. **User configuration loading** (lines 125-172): Environment parsing with error handling
6. **Helper functions** (lines 177-339): Private functions prefixed with `_`, alphabetically sorted
7. **Background tasks** (lines 344-366): Long-running daemon threads
8. **Flask routes** (lines 371-411): HTTP endpoints with decorators
9. **Core business logic** (lines 416-613): Public functions, alphabetically sorted
10. **Initialization** (lines 618-648): App startup and background task management
11. **Main execution** (lines 651-665): Development server startup

**Naming Patterns:**
- **Constants**: `ALL_CAPS_WITH_UNDERSCORES` (e.g., `API_OPEN_METEO_FORECAST_URL`)
- **Global variables**: `ALL_CAPS` (e.g., `APP_DATA`, `PNG_CACHE`)
- **Private functions**: `_snake_case` prefix (e.g., `_build_template_context`)
- **Public functions**: `snake_case` (e.g., `fetch_calendar_events`)
- **Flask routes**: `snake_case` matching URL patterns
- **Variables**: `snake_case` throughout

**Function Organization:**
- Helper functions alphabetically sorted: `_build_template_context`, `_fetch_lat_lon`, `_process_event_data`, `_regenerate_all_pngs`, `_render_png_for_hash`
- Public functions alphabetically sorted: `fetch_calendar_events`, `fetch_weather_data`, `get_weather_icon_class`, `refresh_all_data`

#### Client (Arduino/C++ - client.ino:330 lines)
**File Structure (top to bottom):**
1. **Includes** (lines 1-11): Standard library first, then third-party libraries
2. **Configuration constants** (lines 16-38): Grouped by functionality with comments
3. **Global objects** (lines 42-50): Hardware and network objects, then state variables
4. **Helper functions** (lines 55-286): Alphabetically sorted by function name
5. **Setup & Loop** (lines 291-330): Standard Arduino structure

**Naming Patterns:**
- **Constants**: `ALL_CAPS_WITH_UNDERSCORES` (e.g., `SCREEN_WIDTH`, `WIFI_CONNECTING_MESSAGE_INTERVAL_MS`)
- **Functions**: `camelCase` (e.g., `connectWifi`, `displayTextMessage`, `updateDashboardImage`)
- **Global variables**: `camelCase` (e.g., `lastSuccessfulRefreshHour`, `png_buffer`)
- **Local variables**: `camelCase` throughout

**Function Organization:**
- All helper functions alphabetically sorted: `connectWifi`, `displayTextMessage`, `freePngBuffer`, `pngDrawCallback`, `updateDashboardImage`, `updateNTPTime`

### Code Quality Patterns

#### Server (Python)
- **Global state management**: `APP_DATA` dict with threading locks
- **Configuration loading**: JSON from `CONFIG` environment variable
- **Error handling**: Try/catch with detailed logging and user-friendly error messages
- **Thread safety**: All shared data protected with locks (`APP_DATA_LOCK`, `PNG_CACHE_LOCK`)
- **Background tasks**: Daemon threads for scheduled data refresh
- **Resource cleanup**: Explicit cleanup of PNG buffers and Playwright resources
- **Logging**: Extensive `print()` statements (72 occurrences) for debugging and monitoring

#### Client (Arduino/C++)
- **Constants**: All configuration as `const` values at top of file
- **Memory management**: Explicit allocation/deallocation of PNG buffers with PSRAM fallback
- **Error recovery**: Infinite retry loops with delays for WiFi/NTP failures
- **Display management**: Clear error handling for e-ink display operations
- **Logging**: Detailed `Serial.print*()` statements (37 occurrences) for debugging

## Key Files

- `server/app.py`: Main Flask application (665 lines)
- `server/templates/index.html`: HTML template for dashboard
- `client/client.ino`: Arduino firmware for M5Paper S3
- `Dockerfile`: Multi-stage build with Playwright

## Dependencies

### Server
- Flask, CalDAV, Playwright for core functionality
- Gunicorn for production WSGI serving
- Uses PEP 723 script dependencies format

### Client  
- FastEPD, PNGdec, HTTPClient for ESP32/M5Paper functionality
- Standard Arduino libraries

## Configuration

### Environment Variables
- `CONFIG`: JSON string containing user configurations (required)

### User Config Structure
Each user hash maps to:
- `timezone`: IANA timezone string
- `weather_location`: Location name for geocoding
- `caldav_urls`: Comma-separated CalDAV URLs with embedded auth
- `caldav_filter_names`: Optional comma-separated calendar name filters

## Architecture Notes

### Threading Model
- Main Flask thread serves HTTP requests
- Background daemon thread refreshes data every hour
- PNG generation happens synchronously within background thread
- All shared state protected with locks

### Data Flow
1. Background thread fetches calendar events and weather data
2. Data stored in global `APP_DATA` dict with timestamp
3. PNG images pre-rendered and cached
4. Client polls PNG endpoint every hour
5. Client renders image directly to e-ink display

### Error Handling Philosophy
- Server: Graceful degradation with placeholder data
- Client: Infinite retry with status display on e-ink screen
- Both: Detailed logging for debugging

## Security Considerations

### Current State
- CalDAV credentials embedded in URLs
- No authentication on server endpoints
- Intended for private network deployment

### Production Recommendations
- Add basic authentication
- Use environment variables for secrets
- Consider HTTPS termination
- Rate limiting on endpoints

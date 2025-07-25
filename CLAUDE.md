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

### Server (Python)
- **Global state management**: `APP_DATA` dict with threading locks
- **Configuration loading**: JSON from `CONFIG` environment variable
- **Error handling**: Try/catch with detailed logging and user-friendly error messages
- **Thread safety**: All shared data protected with locks (`APP_DATA_LOCK`, `PNG_CACHE_LOCK`)
- **Background tasks**: Daemon threads for scheduled data refresh
- **Resource cleanup**: Explicit cleanup of PNG buffers and Playwright resources

### Client (Arduino/C++)
- **Constants**: All configuration as `const` values at top of file
- **Memory management**: Explicit allocation/deallocation of PNG buffers with PSRAM fallback
- **Error recovery**: Infinite retry loops with delays for WiFi/NTP failures
- **Display management**: Clear error handling for e-ink display operations

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

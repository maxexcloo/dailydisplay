# Daily Display

Personal dashboard for E-Ink displays showing calendar events and weather. Python Flask server + Arduino ESP32 client for M5Paper S3.

## Quick Start

### Server
```bash
# Set configuration
export CONFIG='{
  "user_hash": {
    "timezone": "America/New_York",
    "weather_location": "New York, NY",
    "caldav_urls": "https://user:pass@calendar.example.com/cal.ics"
  }
}'

# Run with Docker (recommended)
docker run -d -p 7777:7777 -e CONFIG="$CONFIG" --restart unless-stopped ghcr.io/max.schaefer/dailydisplay:latest

# Or with docker-compose
docker-compose up -d
```

### Client
1. Set WiFi/server credentials in `client/client.ino`
2. Flash to M5Paper S3 using Arduino IDE

## Configuration

Single environment variable contains JSON config:

```json
{
  "user_hash": {
    "timezone": "America/New_York",
    "weather_location": "New York, NY", 
    "caldav_urls": "https://user:pass@cal.example.com/cal.ics,https://user:pass@work.com/work.ics",
    "caldav_filter_names": "personal,work"
  }
}
```

## API

- `GET /` - Health check
- `GET /<user_hash>` - HTML dashboard
- `GET /<user_hash>.png` - PNG for e-ink display

## Features

- **Calendar**: CalDAV integration with timezone support
- **Weather**: Open-Meteo API with day/night icons
- **Multi-user**: Multiple dashboard configurations
- **Auto-refresh**: Hourly background updates
- **E-ink optimized**: Grayscale PNG rendering

## Architecture

**Server** (`server/app.py`): Flask app fetches calendar/weather data, generates PNGs with Playwright
**Client** (`client/client.ino`): ESP32 firmware polls PNG endpoint, renders to M5Paper S3 display

## Deployment Options

### Docker Compose (Recommended)
```yaml
services:
  dailydisplay:
    image: ghcr.io/max.schaefer/dailydisplay:latest
    ports: ["7777:7777"]
    restart: unless-stopped
    environment:
      CONFIG: |
        {"user_hash": {"timezone": "America/New_York", "weather_location": "New York"}}
```

### Docker Run
```bash
docker run -d -p 7777:7777 -e CONFIG='{"user_hash":{"timezone":"America/New_York","weather_location":"New York"}}' ghcr.io/max.schaefer/dailydisplay:latest
```

### Local Development
```bash
cd server && python app.py
```

## Dependencies

**Server**: Flask, CalDAV, Playwright, iCalendar, Gunicorn
**Client**: FastEPD, PNGdec, HTTPClient, NTPClient

Pre-built Docker images available for linux/amd64 and linux/arm64 via GitHub Actions.

## Troubleshooting

- **No events**: Check CalDAV URL format (`https://user:pass@host/path.ics`)
- **No weather**: Verify location name spelling
- **PNG errors**: Playwright dependencies missing
- **Client issues**: Check WiFi credentials and server URL

## License

Provided as-is for personal use. Comply with third-party API terms.

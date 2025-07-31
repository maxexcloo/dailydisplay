# ARCHITECTURE.md - Technical Design

## Overview

E-ink dashboard system with Python Flask server and Arduino ESP32 client for displaying calendar events and weather.

## Core Components

### Client Architecture
- **Connectivity**: WiFi with HTTP client
- **Display**: E-ink with FastEPD library
- **Hardware**: ESP32 with M5Paper S3 display
- **Memory**: PSRAM for PNG buffers
- **Power**: Deep sleep between updates

### Server Architecture
- **Background**: Hourly data refresh on minute 58
- **Caching**: In-memory PNG cache with TTL
- **Data Sources**: CalDAV calendars, Open-Meteo weather API
- **Framework**: Flask with Jinja2 templating
- **Rendering**: Playwright for PNG generation

## Data Flow

1. **Client Request**: ESP32 requests PNG → Cache check → Data refresh → HTML render → PNG generate → Response
2. **Background Process**: Timer trigger → Parallel data fetch → Cache clear → Pre-render → Error handling
3. **Display Update**: PNG receive → Decode → Render to E-ink → Deep sleep

## Key Features

### Multi-User Support
- **Configuration**: JSON config via environment variable
- **Isolation**: User hash-based routing
- **Personalization**: Timezone, location, calendar URLs per user

### Performance Optimization
- **Batch Processing**: Parallel calendar/weather fetching
- **Graceful Degradation**: Cached data during API failures
- **Thread Safety**: Locks for cache and application state

## Technology Stack

### Backend
- **Calendar**: CalDAV integration
- **Rendering**: Playwright with headless browser
- **Runtime**: Python 3.12+
- **Server**: Flask with Gunicorn

### Frontend
- **Display**: E-ink with FastEPD library
- **Hardware**: ESP32 microcontroller
- **Image**: PNG decoding with PNGdec
- **Network**: WiFi with HTTP client

---

*Technical architecture documentation for the DailyDisplay project.*

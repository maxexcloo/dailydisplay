# ARCHITECTURE.md - Technical Design

## Overview

E-ink dashboard system with Python Flask server and Arduino ESP32 client for displaying calendar events and weather.

## Core Components

### Server Architecture
- **Framework**: Flask with Jinja2 templating
- **Data Sources**: CalDAV calendars, Open-Meteo weather API
- **Rendering**: Playwright for PNG generation
- **Caching**: In-memory PNG cache with TTL
- **Background**: Hourly data refresh on minute 58

### Client Architecture
- **Hardware**: ESP32 with M5Paper S3 display
- **Connectivity**: WiFi with HTTP client
- **Display**: E-ink with FastEPD library
- **Power**: Deep sleep between updates
- **Memory**: PSRAM for PNG buffers

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
- **Thread Safety**: Locks for cache and application state
- **Graceful Degradation**: Cached data during API failures
- **Batch Processing**: Parallel calendar/weather fetching

## Technology Stack

### Backend
- **Runtime**: Python 3.12+
- **Server**: Flask with Gunicorn
- **Rendering**: Playwright with headless browser
- **Calendar**: CalDAV integration

### Frontend/Client
- **Hardware**: ESP32 microcontroller
- **Display**: E-ink with FastEPD library
- **Network**: WiFi with HTTP client
- **Image**: PNG decoding with PNGdec

---

*Technical architecture documentation for the DailyDisplay project.*

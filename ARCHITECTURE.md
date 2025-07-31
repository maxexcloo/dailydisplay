# Architecture

## Overview

Daily Display is a two-component system designed for E-ink dashboard displays:

- **Server**: Python Flask application that aggregates calendar and weather data
- **Client**: Arduino ESP32 firmware that displays rendered dashboard images

## System Design

### Server Architecture

The Flask server (`server/app.py`) implements a multi-threaded architecture:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   HTTP Client   │───▶│   Flask Server   │───▶│  Data Sources   │
│   (ESP32/Web)   │    │                  │    │ (CalDAV/Weather)│
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │  Background      │
                       │  Refresh Thread  │
                       └──────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   PNG Cache      │
                       │  (Thread-Safe)   │
                       └──────────────────┘
```

#### Core Components

**Configuration Management**
- Single `CONFIG` environment variable containing JSON
- Multi-user support with user hash-based isolation
- Timezone-aware calendar processing

**Data Collection**
- **CalDAV Integration**: Fetches calendar events with filtering support
- **Weather API**: Open-Meteo integration with geocoding
- **Background Processing**: Hourly refresh cycle (minute 58)

**Rendering Pipeline**
- **HTML Generation**: Jinja2 templates for dashboard layout
- **PNG Generation**: Playwright for server-side rendering
- **E-ink Optimization**: Grayscale conversion and compression

**Thread Safety**
- `APP_DATA_LOCK`: Protects global application state
- `PNG_CACHE_LOCK`: Protects rendered image cache
- Background thread coordination

### Client Architecture

The ESP32 client (`client/client.ino`) implements a polling-based display system:

```
┌──────────────┐    ┌─────────────────┐    ┌──────────────────┐
│    WiFi      │───▶│   HTTP Client   │───▶│   PNG Decoder    │
│ Connection   │    │                 │    │                  │
└──────────────┘    └─────────────────┘    └──────────────────┘
                                                      │
                                                      ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  Deep Sleep  │◀───│ Display Driver  │◀───│  Image Buffer    │
│   Manager    │    │  (FastEPD)      │    │    (PSRAM)       │
└──────────────┘    └─────────────────┘    └──────────────────┘
```

#### Key Features

**Memory Management**
- PSRAM allocation for PNG buffers
- Automatic garbage collection
- Low-power operation between updates

**Display Pipeline**
- PNG decoding with PNGdec library
- E-ink refresh optimization
- Error handling and retry logic

**Power Management**
- Deep sleep between updates
- Wake-on-timer functionality
- Battery level monitoring

## Data Flow

### Request Lifecycle

1. **Client Request**: ESP32 requests `/<user_hash>.png`
2. **Cache Check**: Server checks PNG cache validity
3. **Data Refresh**: If stale, fetch calendar/weather data
4. **HTML Rendering**: Generate dashboard HTML from template
5. **PNG Generation**: Convert HTML to optimized PNG
6. **Response**: Serve cached or fresh PNG to client
7. **Display Update**: Client decodes and renders to E-ink display

### Background Processing

1. **Timer Trigger**: Cron-like scheduler at minute 58 each hour
2. **Data Collection**: Parallel fetch of calendar and weather data
3. **Cache Invalidation**: Clear stale PNG cache entries
4. **Pre-rendering**: Generate fresh PNGs for active users
5. **Error Handling**: Log failures, continue with cached data

## Security Considerations

### Authentication
- CalDAV credentials in configuration (basic auth)
- No user authentication for display endpoints
- User isolation via hash-based routing

### Data Handling
- Sensitive data limited to calendar credentials
- No persistent storage of user data
- Memory-only caching with TTL

### Network Security
- HTTPS enforcement for external API calls
- Input validation for configuration data
- Rate limiting considerations for external APIs

## Scalability & Performance

### Server Optimization
- In-memory caching reduces API calls
- Background pre-rendering improves response times
- Thread-safe operations enable concurrent requests
- Playwright optimization for PNG generation

### Client Optimization
- Deep sleep reduces power consumption
- PSRAM utilization for large image buffers
- Error recovery and retry mechanisms
- Minimal network overhead per update

## Deployment Architecture

### Container Deployment
```
┌─────────────────────────────────────────┐
│              Docker Host                │
│  ┌─────────────────────────────────────┐ │
│  │        dailydisplay:latest          │ │
│  │                                     │ │
│  │  ┌─────────────┐  ┌─────────────┐   │ │
│  │  │ Flask App   │  │Background   │   │ │
│  │  │ (Port 7777) │  │Thread       │   │ │
│  │  └─────────────┘  └─────────────┘   │ │
│  └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
          │                    │
          ▼                    ▼
┌─────────────────┐   ┌─────────────────┐
│   ESP32 Client  │   │  External APIs  │
│   (WiFi)        │   │ CalDAV/Weather  │
└─────────────────┘   └─────────────────┘
```

### High Availability
- Stateless server design enables horizontal scaling
- Docker restart policies handle process failures
- Graceful degradation with cached data during API outages
- Health check endpoints for monitoring

## Future Extensions

### Planned Enhancements
- **Multiple Display Types**: Support for different E-ink screen sizes
- **Plugin Architecture**: Modular data source integration
- **Configuration UI**: Web interface for user management
- **Metrics Collection**: Usage analytics and performance monitoring

### Scalability Considerations
- Database backend for persistent configuration
- Load balancing for multiple server instances
- CDN integration for static asset delivery
- Message queue for background processing

---

*Technical architecture documentation for the dailydisplay project.*
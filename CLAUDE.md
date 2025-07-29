# CLAUDE.md - Development Guide

## Project Overview
**Purpose**: E-ink dashboard with Python Flask server + Arduino ESP32 client displaying calendar events and weather  
**Status**: Active

## Commands
```bash
# Development
cd server && python app.py    # Start development server
curl http://localhost:7777/user_hash.png    # Test endpoints

# Build
docker build -t dailydisplay .  # Build Docker image
docker run -p 7777:7777 -e CONFIG="$CONFIG" dailydisplay  # Run container
```

## Tech Stack
- **Language**: Python 3.12+ (server), Arduino C++ (client)
- **Framework**: Flask (server), FastEPD (client display)
- **Testing**: Manual testing via curl endpoints

## Code Standards

### Organization
- **Config/Data**: Alphabetical and recursive (imports, dependencies, object keys)
- **Documentation**: Sort sections, lists, and references alphabetically when logical
- **Files**: Alphabetical in documentation and directories
- **Functions**: Group by purpose, alphabetical within groups
- **Variables**: Alphabetical within scope

### Quality
- **Comments**: Minimal - only for complex business logic
- **Documentation**: Update README.md and docs with every feature change
- **Formatting**: Run formatter before commits
- **KISS principle**: Keep it simple - prefer readable code over clever code
- **Naming**: `snake_case` functions, `ALL_CAPS` constants (Python), `camelCase` functions, `ALL_CAPS` constants (Arduino)
- **Trailing newlines**: Required in all files

## Project Structure
- **client/**: Arduino ESP32 firmware for M5Paper S3 display
- **server/**: Python Flask application serving dashboard data
- **server/templates/**: HTML templates for web interface
- **app.py**: Main Flask server entry point
- **client.ino**: Arduino client firmware entry point

## Project Specs
- **Single CONFIG environment variable**: JSON configuration for all users and settings
- **Background refresh thread**: Daemon thread updates data every hour at minute 58
- **PNG pre-rendering**: Server generates grayscale PNGs optimized for e-ink displays
- **CalDAV integration**: Fetches calendar events with timezone support and filtering
- **Weather data**: Open-Meteo API integration with geocoding and forecast
- **Thread-safe data access**: Global state protected with locks (APP_DATA_LOCK, PNG_CACHE_LOCK)
- **Memory management**: Arduino client uses PSRAM for PNG buffer allocation
- **Error handling**: Graceful degradation with extensive logging throughout

## README Guidelines
- **Structure**: Title → Description → Quick Start → Features → Installation → Usage → Contributing
- **Badges**: Include relevant status badges (build, version, license)
- **Code examples**: Always include working examples in code blocks
- **Installation**: Provide copy-paste commands that work
- **Quick Start**: Get users running in under 5 minutes

## Git Workflow
```bash
# After every change
# No specific formatter/linter configured yet
git add . && git commit -m "type: description"

# Always commit after verified working changes
# Keep commits small and focused
```

---

*Simple context for AI assistants working on this open source project.*

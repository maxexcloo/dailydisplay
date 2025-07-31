# CLAUDE.md - Development Guide

## Project Overview
**Purpose**: E-ink dashboard with Python Flask server + Arduino ESP32 client displaying calendar events and weather
**Status**: Active
**Language**: Python 3.12+ (server), Arduino C++ (client)

## Code Standards

### Organization
- **Config/Data**: Alphabetical and recursive (imports, dependencies, object keys)
- **Documentation**: Sort alphabetically and recursively when it makes logical sense
- **Files**: Alphabetical in documentation and directories
- **Functions**: Group by purpose, alphabetical within groups
- **Variables**: Alphabetical within scope

### Quality
- **Comments**: Minimal - only for complex business logic
- **Documentation**: Update ARCHITECTURE.md and README.md with every feature change
- **Error handling**: Graceful degradation with extensive logging throughout
- **Formatting**: Run `uv run --with ruff black` for Python, Arduino IDE formatter for client code before commits
- **KISS principle**: Keep it simple - prefer readable code over clever code
- **Naming**: `snake_case` functions, `ALL_CAPS` constants (Python), `camelCase` functions, `ALL_CAPS` constants (Arduino)
- **Testing**: Manual testing via curl endpoints, unit tests where applicable
- **Trailing newlines**: Required in all files

## Commands
```bash
# Build
uv run server/app.py              # Run with uv (auto-installs dependencies)

# Development
uv run server/app.py              # Start development server
curl localhost:7777                # Test endpoint

# Format
uv run --with ruff black server/  # Code formatting for Python

# Check
uv run --with ruff ruff check server/ && curl localhost:7777  # Lint and test
```

## Development Guidelines

### Contribution Standards
- **Code Changes**: Follow sorting rules and maintain test coverage
- **Documentation**: Keep all docs synchronized and cross-referenced
- **Feature Changes**: Update README.md and ARCHITECTURE.md when adding features

### Documentation Structure
- **ARCHITECTURE.md**: Technical design and implementation details
- **CLAUDE.md**: Development standards and project guidelines
- **README.md**: Tool overview and usage guide

## API Interface Standards
- **Clear responses**: Provide meaningful HTTP status codes and error messages
- **Consistent endpoints**: Use RESTful conventions where applicable
- **Error messages**: Include request context and timestamps in logs
- **Health checks**: Always include basic health endpoint

## Development Workflow Standards

### Environment Management
- Use **uv** for Python dependency management via script headers
- Dependencies defined in script via `# /// script` blocks
- Python 3.12+ required as specified in script headers

## Error Handling Standards
- **Contextual errors**: Include request context and timestamps in logs
- **Graceful degradation**: Continue serving cached data when external APIs fail
- **Informative messages**: Clear error responses for client debugging
- **User-friendly output**: Meaningful HTTP status codes and error messages

### Required Development Tasks
- **build**: Create Docker image
- **check**: All validation (fmt + test)
- **dev**: Development validation cycle
- **fmt**: Code formatting
- **test**: Run test suite

## Project Structure
- **server/app.py**: Main Flask application with data aggregation and PNG rendering (dependencies in script headers)
- **client/client.ino**: ESP32 client firmware for M5Paper S3 display
- **docker-compose.yml**: Docker deployment configuration
- **Dockerfile**: Multi-platform container build configuration

## README Guidelines
- **Badges**: Include relevant status badges (license, status, language, docker)
- **Code examples**: Always include working examples in code blocks
- **Installation**: Provide copy-paste commands that work
- **Quick Start**: Get users running in under 5 minutes
- **Structure**: Title → Badges → Description → Quick Start → Features → Installation → Usage → Contributing

## Tech Stack
- **Backend**: Python 3.12+ with Flask and Gunicorn
- **Client**: Arduino C++ with ESP32 and FastEPD library
- **Testing**: Manual testing via curl endpoints, unit tests where applicable

---

*Development guide for the DailyDisplay open source project.*

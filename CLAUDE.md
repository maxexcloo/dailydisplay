# CLAUDE.md - Development Guide

## Project Overview
**Purpose**: E-ink dashboard with Python Flask server + Arduino ESP32 client displaying calendar events and weather
**Status**: Active
**Language**: Python 3.12+ (server), Arduino C++ (client)

## Code Standards

### Organization
- **Config/Data**: Alphabetical and recursive (imports, dependencies, object keys, mise tasks)
- **Documentation**: Sort sections, lists, and references alphabetically when logical
- **Files**: Alphabetical in documentation and directories
- **Functions**: Group by purpose, alphabetical within groups
- **Variables**: Alphabetical within scope

### Quality
- **Comments**: Minimal - only for complex business logic
- **Documentation**: Update ARCHITECTURE.md and README.md with every feature change
- **Error handling**: Graceful degradation with extensive logging throughout
- **Formatting**: Run `mise run fmt` for Python, Arduino IDE formatter for client code before commits
- **KISS principle**: Keep it simple - prefer readable code over clever code
- **Naming**: `snake_case` functions, `ALL_CAPS` constants (Python), `camelCase` functions, `ALL_CAPS` constants (Arduino)
- **Testing**: Manual testing via curl endpoints, unit tests where applicable
- **Trailing newlines**: Required in all files

## Commands
```bash
# Build
mise run build           # Run server with uv

# Development
mise run dev             # Start development server

# Format
mise run fmt             # Format Python code

# Check
mise run check           # All validation (fmt and test)

# Lint
mise run lint            # Lint Python code

# Test
mise run test            # Test endpoint
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
- **build**: Run server with uv
- **check**: All validation (fmt and test)
- **dev**: Start development server
- **fmt**: Format Python code
- **lint**: Lint Python code
- **test**: Test endpoint

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

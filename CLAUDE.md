# CLAUDE.md - Development Guide

## Project Overview
**Purpose**: E-ink dashboard with Python Flask server + Arduino ESP32 client displaying calendar events and weather
**Status**: Active
**Language**: Python 3.12+ (server), Arduino C++ (client)

## Code Standards

### Organization
- **Config/Data**: Alphabetical and recursive (imports, dependencies, object keys)
- **Documentation**: Sort alphabetically and recursively when it makes logical sense - apply to sections, subsections, lists, and references
- **Files**: Alphabetical in documentation and directories
- **Functions**: Group by purpose, alphabetical within groups
- **Variables**: Alphabetical within scope

### Quality
- **Comments**: Minimal - only for complex business logic
- **Documentation**: Update README.md and docs with every feature change
- **Error handling**: Graceful degradation with extensive logging throughout
- **Formatting**: Run `black` for Python, Arduino IDE formatter for client code before commits
- **KISS principle**: Keep it simple - prefer readable code over clever code
- **Naming**: `snake_case` functions, `ALL_CAPS` constants (Python), `camelCase` functions, `ALL_CAPS` constants (Arduino)
- **Testing**: Manual testing via curl endpoints, unit tests where applicable
- **Trailing newlines**: Required in all files

## Development Guidelines

### Documentation Structure
- **ARCHITECTURE.md**: Technical design and implementation details
- **CLAUDE.md**: Development standards and project guidelines (this file)
- **README.md**: Tool overview and usage guide

### Contribution Standards
- **Code Changes**: Follow sorting rules and maintain test coverage
- **Documentation**: Keep all docs synchronized and cross-referenced
- **Feature Changes**: Update README.md and ARCHITECTURE.md when adding features

## API Interface Standards
- **Clear responses**: Provide meaningful HTTP status codes and error messages
- **Consistent endpoints**: Use RESTful conventions where applicable
- **Error messages**: Include request context and timestamps in logs
- **Health checks**: Always include basic health endpoint

## Development Workflow Standards

### Environment Management
- Use **Docker** for consistent deployment environments
- Pin Python versions in requirements and Dockerfile
- Define common tasks in shell scripts or Makefile

### Required Development Tasks
- **build**: Create Docker image
- **dev**: Start development server (cd server && python app.py)
- **fmt**: Code formatting (Black for Python, Arduino IDE formatter)
- **test**: Run test suite (curl endpoints, unit tests)

## Error Handling Standards
- **Contextual errors**: Include request context and timestamps in logs
- **Graceful degradation**: Continue serving cached data when external APIs fail
- **Informative messages**: Clear error responses for client debugging
- **User-friendly output**: Meaningful HTTP status codes and error messages

## Extension Guidelines
- **Backward compatibility**: Maintain API endpoints and configuration format
- **Configuration files**: Single CONFIG environment variable with JSON structure
- **Feature flags**: Allow gradual feature rollout through configuration
- **Plugin architecture**: Design for future display types and data sources

---
*Development guide for the dailydisplay open source project.*
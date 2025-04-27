# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "caldav",
#     "icalendar",
#     "flask",
#     "gunicorn",
#     "pillow",
#     "requests",
#     "watchdog",
# ]
# ///

# Standard Library Imports
import datetime
import io
import os
import threading
import time
import traceback
import urllib.parse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Third-Party Imports
import caldav                     # CalDAV client library
import requests                   # HTTP requests library
from flask import Flask, abort, send_file  # Web framework
from icalendar import Calendar    # iCalendar parsing library
from PIL import Image, ImageDraw, ImageFont  # Image manipulation library

# ==============================================================================
# Configuration Constants
# ==============================================================================

# --- Image Rendering ---
BLACK_COLOR = 0
GRAY_COLOR = 128  # Mid-gray value for 'L' mode (0=black, 255=white)
RENDER_SCALE = 2
TARGET_IMG_HEIGHT = 540
TARGET_IMG_WIDTH = 960
WHITE_COLOR = 255
# Computed Image Dimensions
IMG_HEIGHT = TARGET_IMG_HEIGHT * RENDER_SCALE
IMG_WIDTH = TARGET_IMG_WIDTH * RENDER_SCALE

# --- Layout ---
DATE_FONT_SIZE_BASE = 30
EVENT_FONT_SIZE_BASE = 22
EVENT_TIME_WIDTH_BASE = 75
HEADER_FONT_SIZE_BASE = 26
ICON_VERTICAL_ADJUSTMENT_BASE = 5 # Pixels at base scale to adjust weather icon vertically
LEFT_PANE_WIDTH_BASE = 320
PADDING_BASE = 20
# Computed Layout Dimensions
COL_WIDTH = (IMG_WIDTH - (LEFT_PANE_WIDTH_BASE * RENDER_SCALE)) // 2
DATE_FONT_SIZE = DATE_FONT_SIZE_BASE * RENDER_SCALE
EVENT_FONT_SIZE = EVENT_FONT_SIZE_BASE * RENDER_SCALE
EVENT_TIME_WIDTH = EVENT_TIME_WIDTH_BASE * RENDER_SCALE
EVENT_TITLE_MARGIN = 10 * RENDER_SCALE
HEADER_FONT_SIZE = HEADER_FONT_SIZE_BASE * RENDER_SCALE
ICON_VERTICAL_ADJUSTMENT = ICON_VERTICAL_ADJUSTMENT_BASE * RENDER_SCALE
LEFT_PANE_WIDTH = LEFT_PANE_WIDTH_BASE * RENDER_SCALE
PADDING = PADDING_BASE * RENDER_SCALE
RIGHT_PANE_WIDTH = IMG_WIDTH - LEFT_PANE_WIDTH

# --- Fonts ---
FONT_DIR = os.environ.get("FONT_DIR", "fonts")
FONT_BOLD_NAME = os.environ.get("FONT_BOLD_NAME", "Inter.ttc") # Use Inter.ttc for both regular and bold, selecting via index later
FONT_REGULAR_NAME = os.environ.get("FONT_REGULAR_NAME", "Inter.ttc")
FONT_WEATHER_ICON_NAME = os.environ.get("FONT_WEATHER_ICON_NAME", "weathericons-regular-webfont.ttf")
# Computed Font Paths
FONT_BOLD_PATH = os.path.join(FONT_DIR, FONT_BOLD_NAME)
FONT_REGULAR_PATH = os.path.join(FONT_DIR, FONT_REGULAR_NAME)
FONT_WEATHER_ICON_PATH = os.path.join(FONT_DIR, FONT_WEATHER_ICON_NAME)

# --- Data Fetching & Background Task ---
CALDAV_FETCH_TIMEOUT = 30  # Timeout for CalDAV client connections
REFRESH_INTERVAL_SECONDS = 10 * 60  # Refresh every 10 minutes
WEATHER_FETCH_TIMEOUT = 10  # Timeout for weather API requests

# --- Weather API ---
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
# Weather Icons (Day)
OPEN_METEO_WMO_ICON_MAP = {
    0: "\uf00d", # Clear sky
    1: "\uf002", # Mainly clear
    2: "\uf00c",
    3: "\uf013",
    45: "\uf014",
    48: "\uf0b6",
    51: "\uf017",
    53: "\uf017",
    55: "\uf017",
    56: "\uf017",
    57: "\uf017",
    61: "\uf019",
    63: "\uf019",
    65: "\uf018",
    66: "\uf018",
    67: "\uf018",
    71: "\uf01b",
    73: "\uf01b",
    75: "\uf076",
    77: "\uf01b",
    80: "\uf01a",
    81: "\uf01a",
    82: "\uf01a",
    85: "\uf01b",
    86: "\uf01b",
    95: "\uf01e",
    96: "\uf01e", # Thunderstorm with slight hail
    99: "\uf01e", # Thunderstorm with heavy hail
    "unknown": "\uf07b", # Unknown/fallback
}
# Weather Icons (Night - Overrides for specific codes)
OPEN_METEO_WMO_ICON_MAP_NIGHT = {
    0: "\uf02e", # Clear sky (night)
    1: "\uf086", # Mainly clear (night)
    2: "\uf086", # Partly cloudy (night) - Using same as mainly clear night
    # Other codes use the day map by default
}

# ==============================================================================
# Global State (for Background Task)
# ==============================================================================

app = Flask(__name__)
APP_DATA = {}
APP_DATA_LOCK = threading.Lock()

# ==============================================================================
# User Configuration Loading
# ==============================================================================
USER_CONFIG = {}
try:
    USER_HASHES_STR = os.environ.get("USER_HASHES", "")
    if not USER_HASHES_STR:
        print("Warning: USER_HASHES environment variable not set or empty.")
    else:
        for user_hash in USER_HASHES_STR.split(","):
            user_hash = user_hash.strip()
            if not user_hash:
                continue

            weather_loc_var = f"WEATHER_LOCATION_{user_hash}"
            tz_var = f"TIMEZONE_{user_hash}"
            caldav_urls_var = f"CALDAV_URLS_{user_hash}"
            caldav_filter_var = f"CALDAV_FILTER_NAMES_{user_hash}"  # New variable name

            weather_loc = os.environ.get(weather_loc_var)
            tz_str = os.environ.get(tz_var)
            caldav_urls_str = os.environ.get(caldav_urls_var, "")
            caldav_filter_str = os.environ.get(caldav_filter_var)  # Read the new variable

            if not weather_loc:
                raise ValueError(f"Missing environment variable: {weather_loc_var}")
            if not tz_str:
                raise ValueError(f"Missing environment variable: {tz_var}")

            try:
                ZoneInfo(tz_str)
            except ZoneInfoNotFoundError:
                raise ValueError(f"Invalid timezone '{tz_str}' specified in {tz_var}")

            caldav_urls = [url.strip() for url in caldav_urls_str.split(",") if url.strip()]

            # Parse the filter list if provided
            caldav_filters = None
            if caldav_filter_str:
                caldav_filters = {name.strip() for name in caldav_filter_str.split(",") if name.strip()}
                print(f"  Applying calendar name filter for user '{user_hash}': {caldav_filters}")

            # Store all config including the filters
            USER_CONFIG[user_hash] = {
                "caldav_urls": caldav_urls,
                "weather_location": weather_loc,
                "timezone": tz_str,
                "caldav_filters": caldav_filters,  # Store the filter set (or None)
            }

            print(f"Loaded config for user '{user_hash}': TZ={tz_str}, Loc={weather_loc}, URLs={len(caldav_urls)}, Filters={'Yes' if caldav_filters else 'No'}")

except ValueError as e:
    print(f"Configuration Error: {e}")
    raise
except Exception as e:
    print(f"Unexpected error loading user configuration: {e}")
    traceback.print_exc()
    raise RuntimeError("Failed to load user configuration") from e

if not USER_CONFIG and USER_HASHES_STR:
    print("Error: USER_HASHES is set, but no valid user configurations could be loaded.")
    raise RuntimeError("Failed to load any valid user configurations.")
elif not USER_CONFIG:
    print("Warning: No users configured.")


# ==============================================================================
# Font Loading
# ==============================================================================
try:
    DATE_FONT_SIZE = DATE_FONT_SIZE_BASE * RENDER_SCALE  # Compute scaled date font size
    LOADED_FONTS = {
        # Bold fonts - Assuming index 1 in Inter.ttc is Bold
        "time": ImageFont.truetype(FONT_BOLD_PATH, 144, index=1),
        "weather_temp": ImageFont.truetype(FONT_BOLD_PATH, 64, index=1),
        "header": ImageFont.truetype(FONT_BOLD_PATH, HEADER_FONT_SIZE, index=1),
        "event_time": ImageFont.truetype(FONT_BOLD_PATH, EVENT_FONT_SIZE, index=1),
        # Regular fonts - Assuming index 0 in Inter.ttc is Regular
        "date": ImageFont.truetype(FONT_REGULAR_PATH, DATE_FONT_SIZE, index=0),
        "weather_details": ImageFont.truetype(FONT_REGULAR_PATH, 52, index=0),
        "event_title": ImageFont.truetype(FONT_REGULAR_PATH, EVENT_FONT_SIZE, index=0),
        # Weather icon font remains the same
        "weather_icon": ImageFont.truetype(FONT_WEATHER_ICON_PATH, 160),
    }
    print("Successfully pre-loaded all required fonts (using Inter.ttc with indices).")
except IOError as e:
    print(f"CRITICAL ERROR: Could not load font file: {e}")
    print(f"Ensure font files exist: Regular='{FONT_REGULAR_PATH}', Bold='{FONT_BOLD_PATH}', Weather='{FONT_WEATHER_ICON_PATH}'")
    raise RuntimeError(f"Failed to load required font file: {e}") from e

# ==============================================================================
# Function Definitions (Sorted Alphabetically)
# ==============================================================================

def _fetch_lat_lon(location_name, session):
    """Internal helper to fetch lat/lon for weather."""
    params = {"name": location_name, "count": 1, "language": "en", "format": "json"}
    try:
        response = session.get(OPEN_METEO_GEOCODE_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data and data.get("results"):
            result = data["results"][0]
            return result.get("latitude"), result.get("longitude")
        print(f"Warning: Geocoding failed for '{location_name}'. No results.")
        return None, None
    except requests.exceptions.RequestException as e:
        print(f"Error during geocoding request for '{location_name}': {e}")
        return None, None
    except Exception as e:
        print(f"Error processing geocoding response for '{location_name}': {e}")
        return None, None


def background_refresh_loop():
    """Runs the refresh_all_data function periodically."""
    print("Background thread started.")
    while True:
        # Wait *before* fetching, so the initial fetch isn't immediately followed by another
        print(f"Background thread sleeping for {REFRESH_INTERVAL_SECONDS} seconds...")
        time.sleep(REFRESH_INTERVAL_SECONDS)
        try:
            refresh_all_data()
        except Exception as e:
            print(f"Error in background refresh loop: {e}")
            traceback.print_exc()


def draw_text_with_wrapping(draw, text, position, font, max_width, fill=0):
    """Helper to draw wrapped text, returns Y position after drawing."""
    lines = []
    words = text.split()
    if not words:
        return position[1]
    current_line = words[0]
    for word in words[1:]:
        bbox = draw.textbbox((0, 0), f"{current_line} {word}", font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line = f"{current_line} {word}"
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    x, y = position
    line_height = sum(font.getmetrics())  # Sum of ascent & descent
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + (2 * RENDER_SCALE)  # Scaled line spacing
    return y


def fetch_calendar_events(caldav_urls, start_date_local, end_date_local, timezone_str, caldav_filters=None):
    """Fetches and processes calendar events from CalDAV URLs, optionally filtering by calendar name."""
    all_today, timed_today, all_tomorrow, timed_tomorrow, errors = [], [], [], [], []
    added_all_today_titles = set()
    added_timed_today_keys = set()
    added_all_tomorrow_titles = set()
    added_timed_tomorrow_keys = set()

    user_tz = ZoneInfo(timezone_str)
    today_start = start_date_local
    today_end = today_start + datetime.timedelta(days=1)
    tomorrow_start = today_end
    tomorrow_end = tomorrow_start + datetime.timedelta(days=1)

    for url in caldav_urls:
        print(f"Processing CalDAV URL: {url[:url.find('@') + 1]}...")
        username, password, url_display_name = None, None, url
        try:
            parsed_url = urllib.parse.urlparse(url)
            url_display_name = parsed_url.hostname or url
            if parsed_url.username:
                username = urllib.parse.unquote(parsed_url.username)
            if parsed_url.password:
                password = urllib.parse.unquote(parsed_url.password)
            url_no_creds = parsed_url._replace(netloc=parsed_url.hostname + (f":{parsed_url.port}" if parsed_url.port else "")).geturl()

            with caldav.DAVClient(url=url_no_creds, username=username, password=password, timeout=CALDAV_FETCH_TIMEOUT) as client:
                principal = client.principal()
                calendars = principal.calendars()
                if not calendars:
                    continue

                for calendar in calendars:
                    # Apply calendar name filtering if filters are provided
                    if caldav_filters and calendar.name not in caldav_filters:
                        print(f"  Skipping calendar (filtered out): {calendar.name}")
                        continue
                    print(f"  Searching calendar: {calendar.name}")  # Process this calendar

                    results = calendar.date_search(start=start_date_local, end=end_date_local, expand=True)

                    for event in results:
                        summary = "UNKNOWN_EVENT" # Default summary for error reporting
                        try:
                            # Parse the iCalendar data directly from the event object's data attribute
                            if not hasattr(event, "data") or not event.data:
                                print(f"    Skipping event: No data attribute found on event object. URL: {getattr(event, 'url', 'N/A')}")
                                continue

                            ical_component = None
                            try:
                                # Ensure event.data is bytes if needed by from_ical, or decode if it's already bytes
                                ics_data = event.data
                                if isinstance(ics_data, bytes):
                                    # Attempt decoding with utf-8, fallback to latin-1 if needed
                                    try:
                                        ics_data = ics_data.decode("utf-8")
                                    except UnicodeDecodeError:
                                        print(f"    Warning: Decoding event data as UTF-8 failed, trying latin-1. URL: {getattr(event, 'url', 'N/A')}")
                                        ics_data = ics_data.decode("latin-1", errors="replace")

                                cal = Calendar.from_ical(ics_data)
                                # Find the first VEVENT component in the parsed data
                                for component in cal.walk("VEVENT"):
                                    ical_component = component
                                    break  # Use the first VEVENT found
                            except Exception as parse_ex:
                                print(f"    Error parsing event data: {parse_ex}. URL: {getattr(event, 'url', 'N/A')}")
                                continue  # Skip this event if parsing fails

                            if not ical_component:
                                print(f"    Skipping event: No VEVENT component found in event data. URL: {getattr(event, 'url', 'N/A')}")
                                continue

                            # Now extract components from the parsed VEVENT
                            summary_comp = ical_component.get("summary")
                            dtstart_comp = ical_component.get("dtstart")
                            recurrence_id_comp = ical_component.get("recurrence-id")  # Get recurrence ID component

                            if not summary_comp or not dtstart_comp:
                                print(f"    Skipping event: Missing summary or dtstart. Raw dtstart: {dtstart_comp}")
                                continue

                            summary = str(summary_comp) # Update summary for potential error messages
                            original_start_time_obj = dtstart_comp.dt  # Keep original for reference/fallback

                            # --- Determine the actual start time for this instance ---
                            instance_start_time_obj = original_start_time_obj  # Default to original dtstart
                            if recurrence_id_comp:
                                recurrence_dt = recurrence_id_comp.dt
                                # Prefer recurrence ID if it's a datetime (for timed events)
                                if isinstance(recurrence_dt, datetime.datetime):
                                    instance_start_time_obj = recurrence_dt
                                # If recurrence ID is a date, check if original was all-day
                                elif isinstance(recurrence_dt, datetime.date):
                                    original_is_all_day = isinstance(original_start_time_obj, datetime.date) and not isinstance(
                                        original_start_time_obj, datetime.datetime
                                    )
                                    if original_is_all_day:
                                        instance_start_time_obj = recurrence_dt  # Use the date for all-day instance
                                    else:
                                        # Original was timed, recurrence ID is just a date. Fall back to original dtstart.
                                        print(f"      Warning: Timed event '{summary}' has date-only Recurrence-ID. Falling back to original dtstart for this instance.")
                                else:
                                    print(f"      Warning: Unexpected Recurrence-ID type for event '{summary}': {type(recurrence_dt)}. Using original dtstart.")
                            # --- End Determine actual start time ---

                            # --- Determine if All Day based on the *instance* start time ---
                            is_all_day = isinstance(instance_start_time_obj, datetime.date) and not isinstance(instance_start_time_obj, datetime.datetime)

                            # --- Localize and Format ---
                            if is_all_day:
                                # Combine the date part with midnight, then make timezone aware
                                naive_dt = datetime.datetime.combine(instance_start_time_obj, datetime.time.min)
                                event_start_local = naive_dt.replace(tzinfo=user_tz)  # Assign local timezone
                                time_str = "All Day"
                            elif isinstance(instance_start_time_obj, datetime.datetime):
                                # Handle timezone: Convert aware times, assume naive times are in user's TZ
                                if instance_start_time_obj.tzinfo:
                                    event_start_local = instance_start_time_obj.astimezone(user_tz)
                                else:  # Naive datetime
                                    event_start_local = instance_start_time_obj.replace(tzinfo=user_tz) # Assign user's timezone directly
                                time_str = event_start_local.strftime("%H:%M")
                            else:
                                print(f"    Skipping event '{summary}': Unexpected instance_start_time_obj type: {type(instance_start_time_obj)}")
                                continue

                            details = {"time": time_str, "title": summary, "sort_key": event_start_local}

                            # Add event to the correct list if not already added (using localized instance start time)
                            if today_start <= event_start_local < today_end:
                                if is_all_day:
                                    if summary not in added_all_today_titles:
                                        all_today.append(details)
                                        added_all_today_titles.add(summary)
                                else:
                                    event_key = (time_str, summary)
                                    if event_key not in added_timed_today_keys:
                                        timed_today.append(details)
                                        added_timed_today_keys.add(event_key)
                            elif tomorrow_start <= event_start_local < tomorrow_end:
                                if is_all_day:
                                    if summary not in added_all_tomorrow_titles:
                                        all_tomorrow.append(details)
                                        added_all_tomorrow_titles.add(summary)
                                else:
                                    event_key = (time_str, summary)
                                    if event_key not in added_timed_tomorrow_keys:
                                        timed_tomorrow.append(details)
                                        added_timed_tomorrow_keys.add(event_key)

                        except Exception as event_ex:
                            print(f"    Error processing event '{summary}': {event_ex}")
                            traceback.print_exc()

        except caldav.lib.error.AuthorizationError:
            err_msg = f"Auth Fail: {url_display_name}"
        except requests.exceptions.Timeout:
            err_msg = f"Timeout: {url_display_name}"
        except requests.exceptions.ConnectionError:
            err_msg = f"Connect Fail: {url_display_name}"
        except Exception as cal_ex:
            err_msg = f"Load Fail: {url_display_name}"
            print(f"  Error loading calendar from {url_display_name}: {cal_ex}")
            traceback.print_exc()
        else:
            continue # Skip error appending if loop finished normally
        print(f"  {err_msg}")
        errors.append({"time": "ERR", "title": err_msg, "sort_key": today_start})

    # Sort events: All-day alphabetically, timed by start time
    all_today.sort(key=lambda x: x["title"])
    timed_today.sort(key=lambda x: x["sort_key"])
    all_tomorrow.sort(key=lambda x: x["title"])
    timed_tomorrow.sort(key=lambda x: x["sort_key"])

    # Combine errors, all-day, and timed events for each day
    return errors + all_today + timed_today, all_tomorrow + timed_tomorrow


def fetch_weather_data(location, timezone_str):
    """Fetches weather data from Open-Meteo API. Returns fetched data or None on failure."""
    print(f"Attempting to fetch weather for {location} (Timezone: {timezone_str})")
    weather_data = {"temp": None, "high": None, "low": None, "humidity": None, "icon_code": "unknown", "is_day": 1}

    with requests.Session() as session:
        lat, lon = _fetch_lat_lon(location, session)
        if lat is None or lon is None:
            print(f"Weather fetch failed for {location}: Could not get coordinates.")
            return None  # Indicate failure

        params = {
            "latitude": lat,
            "longitude": lon,
            "timezone": timezone_str,
            "current": "temperature_2m,relative_humidity_2m,is_day,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 1,
        }
        try:
            response = session.get(OPEN_METEO_FORECAST_URL, params=params, timeout=WEATHER_FETCH_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            current = data.get("current", {})
            daily = data.get("daily", {})
            weather_data.update(
                {
                    "temp": current.get("temperature_2m"),
                    "humidity": current.get("relative_humidity_2m"),
                    "icon_code": current.get("weather_code", "unknown"),
                    "is_day": current.get("is_day", 1),
                    "high": daily.get("temperature_2m_max", [None])[0],
                    "low": daily.get("temperature_2m_min", [None])[0],
                }
            )
            # Fallback to daily weather code if current is unknown
            if weather_data["icon_code"] == "unknown" and daily.get("weather_code"):
                weather_data["icon_code"] = daily["weather_code"][0]
            print(f"Successfully fetched weather for {location}")
            return weather_data  # Return fetched data
        except requests.exceptions.RequestException as e:
            print(f"Error during Open-Meteo forecast request for '{location}': {e}")
        except Exception as e:
            print(f"Error processing Open-Meteo forecast response for '{location}': {e}")
            traceback.print_exc()

    return None  # Indicate failure


def generate_image(current_datetime_local, weather_info, today_events, tomorrow_events):
    """Generates the display image using pre-fetched data."""
    img_large = Image.new("L", (IMG_WIDTH, IMG_HEIGHT), color=WHITE_COLOR)
    draw = ImageDraw.Draw(img_large)
    fonts = LOADED_FONTS  # Use pre-loaded fonts

    # Format current time and date strings
    current_time_str = current_datetime_local.strftime("%H:%M")
    current_date_str = current_datetime_local.strftime("%a, %d %b")  # Short day/month

    event_time_font = fonts["event_time"]
    event_title_font = fonts["event_title"]

    # --- Draw Left Pane (Time, Date, Weather) ---
    # Draw Time (Centered)
    time_font = fonts["time"]
    time_bbox = draw.textbbox((0, 0), current_time_str, font=time_font)
    time_width = time_bbox[2] - time_bbox[0]
    time_height = time_bbox[3] - time_bbox[1]
    time_x = (LEFT_PANE_WIDTH - time_width) // 2
    time_y = PADDING
    draw.text((time_x, time_y), current_time_str, font=time_font, fill=BLACK_COLOR)

    # Draw Date (Centered below Time)
    date_font = fonts["date"]
    date_bbox = draw.textbbox((0, 0), current_date_str, font=date_font)
    date_width = date_bbox[2] - date_bbox[0]
    date_height = date_bbox[3] - date_bbox[1]
    date_x = (LEFT_PANE_WIDTH - date_width) // 2
    date_y = time_y + time_height + (25 * RENDER_SCALE) # Spacing below time
    draw.text((date_x, date_y), current_date_str, font=date_font, fill=BLACK_COLOR)

    # Draw Weather (Centered Horizontally, Bottom Aligned Vertically)
    weather_icon_font = fonts["weather_icon"]
    weather_temp_font = fonts["weather_temp"]
    weather_details_font = fonts["weather_details"]

    # Calculate heights of weather elements
    icon_bbox = draw.textbbox((0, 0), "\uf00d", font=weather_icon_font) # Sample icon for metrics
    icon_height = icon_bbox[3] - icon_bbox[1]
    temp_bbox = draw.textbbox((0, 0), "00°C", font=weather_temp_font)
    temp_height = temp_bbox[3] - temp_bbox[1]
    details_bbox_hilo = draw.textbbox((0, 0), "H:00° L:00°", font=weather_details_font)
    details_hilo_height = details_bbox_hilo[3] - details_bbox_hilo[1]
    details_bbox_hum = draw.textbbox((0, 0), "Hum: 00%", font=weather_details_font)
    details_hum_height = details_bbox_hum[3] - details_bbox_hum[1]
    details_spacing = 4 * RENDER_SCALE
    weather_text_block_height = temp_height + details_spacing + details_hilo_height + details_spacing + details_hum_height

    # Calculate widths of weather elements
    icon_w = icon_bbox[2] - icon_bbox[0]
    temp_w = temp_bbox[2] - temp_bbox[0]
    hilo_w = details_bbox_hilo[2] - details_bbox_hilo[0]
    hum_w = details_bbox_hum[2] - details_bbox_hum[0]
    weather_text_block_width = max(temp_w, hilo_w, hum_w)
    weather_padding_between = PADDING
    total_weather_width = icon_w + weather_padding_between + weather_text_block_width

    # Calculate positions for weather elements
    weather_x_start = (LEFT_PANE_WIDTH - total_weather_width) // 2 # Center block horizontally
    icon_x = weather_x_start
    text_x = icon_x + icon_w + weather_padding_between
    section_bottom_y = IMG_HEIGHT - PADDING # Align bottom edge here
    text_y_start = section_bottom_y - weather_text_block_height
    icon_y_base = section_bottom_y - icon_height
    icon_y = icon_y_base - ICON_VERTICAL_ADJUSTMENT # Apply adjustment

    # Prepare weather data strings
    temp, high, low, hum, wmo_code, is_day = (None,) * 6
    if weather_info:
        temp = weather_info.get("temp")
        high = weather_info.get("high")
        low = weather_info.get("low")
        hum = weather_info.get("humidity")
        wmo_code = weather_info.get("icon_code", "unknown")
        is_day = weather_info.get("is_day", 1)
    else:
        wmo_code, is_day = "unknown", 1 # Default if fetch failed

    temp_str = f"{temp:.0f}°C" if isinstance(temp, (int, float)) else "--°C"
    hilo_str = f"H:{high:.0f}° L:{low:.0f}°" if isinstance(high, (int, float)) and isinstance(low, (int, float)) else "H:--° L:--°"
    hum_str = f"Hum: {hum:.0f}%" if isinstance(hum, (int, float)) else "Hum: --%"

    # Determine weather icon character
    icon_char = (
        OPEN_METEO_WMO_ICON_MAP_NIGHT.get(wmo_code)
        if not is_day and wmo_code in OPEN_METEO_WMO_ICON_MAP_NIGHT
        else OPEN_METEO_WMO_ICON_MAP.get(wmo_code, OPEN_METEO_WMO_ICON_MAP["unknown"])
    )

    # Draw weather icon
    draw.text((icon_x, icon_y), icon_char, font=weather_icon_font, fill=BLACK_COLOR)

    # Draw weather text lines
    current_text_y = text_y_start
    draw.text((text_x, current_text_y), temp_str, font=weather_temp_font, fill=BLACK_COLOR)
    current_text_y += temp_height + details_spacing
    draw.text((text_x, current_text_y), hilo_str, font=weather_details_font, fill=BLACK_COLOR)
    current_text_y += details_hilo_height + details_spacing
    draw.text((text_x, current_text_y), hum_str, font=weather_details_font, fill=BLACK_COLOR)

    # --- Draw Right Pane (Dividers, Headers, Events) ---
    # Draw vertical dividers
    line_w = 1 * RENDER_SCALE
    draw.line([(LEFT_PANE_WIDTH, 0), (LEFT_PANE_WIDTH, IMG_HEIGHT)], fill=BLACK_COLOR, width=line_w)
    col_div_x = LEFT_PANE_WIDTH + COL_WIDTH
    draw.line([(col_div_x, 0), (col_div_x, IMG_HEIGHT)], fill=BLACK_COLOR, width=line_w)

    # Draw Headers ("Today", "Tomorrow")
    header_y = PADDING
    header_font = fonts["header"]
    head_today_bbox = draw.textbbox((0, 0), "Today", font=header_font)
    head_tmrw_bbox = draw.textbbox((0, 0), "Tomorrow", font=header_font)
    header_h = head_today_bbox[3] - head_today_bbox[1]
    today_head_w = head_today_bbox[2] - head_today_bbox[0]
    today_head_x = LEFT_PANE_WIDTH + (COL_WIDTH - today_head_w) // 2
    tmrw_head_w = head_tmrw_bbox[2] - head_tmrw_bbox[0]
    tmrw_head_x = col_div_x + (COL_WIDTH - tmrw_head_w) // 2
    draw.text((today_head_x, header_y), "Today", font=header_font, fill=BLACK_COLOR)
    draw.text((tmrw_head_x, header_y), "Tomorrow", font=header_font, fill=BLACK_COLOR)

    # Draw Events
    event_y_start = header_y + header_h + (15 * RENDER_SCALE)
    event_title_margin = EVENT_TITLE_MARGIN
    event_spacing_after = 6 * RENDER_SCALE

    # Draw Today's Events
    y_today = event_y_start
    for event in today_events:
        if y_today > IMG_HEIGHT - PADDING: break # Stop if exceeding bounds
        time_str = event.get("time", "--:--")
        title_str = event.get("title", "No Title")
        is_all_day = time_str == "All Day"
        is_error = time_str == "ERR"

        # Determine color (gray out past timed events)
        event_color = BLACK_COLOR
        if not is_all_day and not is_error:
            event_start_time = event.get("sort_key")
            if event_start_time and event_start_time < current_datetime_local:
                event_color = GRAY_COLOR

        # Calculate positions and draw time/title
        if not is_all_day and not is_error:
            time_bbox = draw.textbbox((0, 0), "00:00", font=event_time_font) # Use fixed width for alignment
            actual_time_width = time_bbox[2] - time_bbox[0]
            draw.text((LEFT_PANE_WIDTH + PADDING, y_today), time_str, font=event_time_font, fill=event_color)
            title_x = LEFT_PANE_WIDTH + PADDING + actual_time_width + event_title_margin
            title_max_w = COL_WIDTH - PADDING - actual_time_width - event_title_margin - PADDING
        else: # All-day or error event
            title_x = LEFT_PANE_WIDTH + PADDING
            title_max_w = COL_WIDTH - (2 * PADDING)

        y_after_title = draw_text_with_wrapping(draw, title_str, (title_x, y_today), event_title_font, title_max_w, fill=event_color)
        y_today = y_after_title + event_spacing_after

    # Draw Tomorrow's Events (Always black)
    y_tmrw = event_y_start
    for event in tomorrow_events:
        if y_tmrw > IMG_HEIGHT - PADDING: break # Stop if exceeding bounds
        time_str = event.get("time", "--:--")
        title_str = event.get("title", "No Title")
        is_all_day = time_str == "All Day"

        # Calculate positions and draw time/title
        if not is_all_day:
            time_bbox = draw.textbbox((0, 0), "00:00", font=event_time_font) # Use fixed width for alignment
            actual_time_width = time_bbox[2] - time_bbox[0]
            draw.text((col_div_x + PADDING, y_tmrw), time_str, font=event_time_font, fill=BLACK_COLOR)
            title_x = col_div_x + PADDING + actual_time_width + event_title_margin
            title_max_w = COL_WIDTH - PADDING - actual_time_width - event_title_margin - PADDING
        else: # All-day event
            title_x = col_div_x + PADDING
            title_max_w = COL_WIDTH - (2 * PADDING)

        y_after_title = draw_text_with_wrapping(draw, title_str, (title_x, y_tmrw), event_title_font, title_max_w, fill=BLACK_COLOR)
        y_tmrw = y_after_title + event_spacing_after

    # --- Downscale and Return ---
    img_final = img_large.resize((TARGET_IMG_WIDTH, TARGET_IMG_HEIGHT), Image.Resampling.LANCZOS)
    return img_final


def img_to_bytes(img):
    """Converts PIL Image object to PNG image bytes."""
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr


def refresh_all_data():
    """Fetches weather and calendar data for all configured users."""
    print(f"Background task: Starting data refresh cycle at {datetime.datetime.now()}")
    global APP_DATA
    new_data = {}  # Build new data separately

    for user_hash, config in USER_CONFIG.items():
        print(f"  Refreshing data for user: {user_hash}")
        timezone_str = config["timezone"]
        location = config["weather_location"]
        caldav_urls = config["caldav_urls"]
        caldav_filters = config.get("caldav_filters") # Get filters for this user
        user_tz = ZoneInfo(timezone_str)

        # Fetch Weather
        weather_info = fetch_weather_data(location, timezone_str)

        # Fetch Calendar Events
        now_local = datetime.datetime.now(user_tz)
        start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        # Fetch events slightly beyond tomorrow to catch multi-day events correctly
        end_of_fetch_range = start_of_today + datetime.timedelta(days=2)

        # Pass filters to the fetch function
        today_events, tomorrow_events = fetch_calendar_events(caldav_urls, start_of_today, end_of_fetch_range, timezone_str, caldav_filters)

        new_data[user_hash] = {
            "weather": weather_info,  # Will be None if fetch failed
            "today_events": today_events,
            "tomorrow_events": tomorrow_events,
            "last_updated": time.time(),
        }

    # Update the global state safely
    with APP_DATA_LOCK:
        APP_DATA = new_data
    print(f"Background task: Data refresh cycle finished at {datetime.datetime.now()}")


# ==============================================================================
# Flask App Initialization & Route
# ==============================================================================

app = Flask(__name__)

@app.route("/display/<user_hash>")
def display_image(user_hash):
    """Main Flask route to generate and return the display image."""
    config = USER_CONFIG.get(user_hash)
    if not config:
        abort(404, description="User configuration not found")

    timezone_str = config["timezone"]
    user_tz = ZoneInfo(timezone_str)  # Should be valid due to startup check

    # Get data from the background-populated store
    with APP_DATA_LOCK:
        user_data = APP_DATA.get(user_hash)

    if not user_data:
        print(f"Warning: Data not yet available for user '{user_hash}'.")
        abort(503, description="Data is being refreshed, please try again shortly.")  # 503 Service Unavailable

    # Get current time/date for display
    now_user_tz = datetime.datetime.now(user_tz)

    # Use the fetched data
    weather_info = user_data.get("weather")
    today_events = user_data.get("today_events", [])
    tomorrow_events = user_data.get("tomorrow_events", [])
    last_updated_ts = user_data.get("last_updated", 0)
    print(f"Generating image for '{user_hash}' using data last updated at: {datetime.datetime.fromtimestamp(last_updated_ts)}")

    # Generate image
    try:
        # Pass the current datetime object to the image generator
        img_obj = generate_image(now_user_tz, weather_info, today_events, tomorrow_events)
        img_bytes = img_to_bytes(img_obj)
    except Exception as e:
        print(f"Error during image generation for user '{user_hash}': {e}")
        traceback.print_exc()
        abort(500, description="Failed to generate display image")

    return send_file(img_bytes, mimetype="image/png", as_attachment=False)


# ==============================================================================
# Main Execution
# ==============================================================================
if __name__ == "__main__":
    if not USER_CONFIG and os.environ.get("USER_HASHES"):
        print("Server cannot start: USER_HASHES set but no valid configurations loaded.")
        exit(1)
    if not USER_CONFIG:
        print("Warning: No users configured, background refresh will do nothing.")

    # Perform initial data fetch before starting the server
    print("Performing initial data fetch...")
    refresh_all_data()
    print("Initial data fetch complete.")

    # Start the background refresh thread
    refresh_thread = threading.Thread(target=background_refresh_loop, daemon=True)
    refresh_thread.start()

    print("Starting Flask development server with auto-reloading enabled...")
    # Note: Flask's built-in server is NOT recommended for production.
    # Use Gunicorn or another WSGI server via Docker as planned.
    # Auto-reloading is enabled for development. Ensure 'watchdog' is installed for better reliability with threads.
    app.run(host="0.0.0.0", port=5050, debug=True, use_reloader=True)

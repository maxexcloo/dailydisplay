# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "caldav",
#     "icalendar",
#     "flask",
#     "gunicorn",
#     "pillow",
#     "requests",
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
import caldav
import requests
from flask import Flask, abort, request, send_file
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# Configuration Constants
# ==============================================================================

# --- Image Rendering ---
RENDER_SCALE = 2
TARGET_IMG_HEIGHT = 540
TARGET_IMG_WIDTH = 960
# Computed Image Dimensions
IMG_HEIGHT = TARGET_IMG_HEIGHT * RENDER_SCALE
IMG_WIDTH = TARGET_IMG_WIDTH * RENDER_SCALE
GRAY_COLOR = 128  # Mid-gray value for 'L' mode (0=black, 255=white)
BLACK_COLOR = 0
WHITE_COLOR = 255

# --- Layout ---
PADDING_BASE = 20
LEFT_PANE_WIDTH_BASE = 320
EVENT_COUNT_THRESHOLD = 10
EVENT_FONT_SIZE_NORMAL_BASE = 24
EVENT_FONT_SIZE_SMALL_BASE = 20
EVENT_TIME_WIDTH_BASE = 70  # Width allocated for HH:MM time
EVENT_ALL_DAY_WIDTH_BASE = 90  # Approx width needed for "All Day" text
# Computed Layout Dimensions
PADDING = PADDING_BASE * RENDER_SCALE
LEFT_PANE_WIDTH = LEFT_PANE_WIDTH_BASE * RENDER_SCALE
RIGHT_PANE_WIDTH = IMG_WIDTH - LEFT_PANE_WIDTH
COL_WIDTH = RIGHT_PANE_WIDTH // 2
EVENT_FONT_SIZE_NORMAL = EVENT_FONT_SIZE_NORMAL_BASE * RENDER_SCALE
EVENT_FONT_SIZE_SMALL = EVENT_FONT_SIZE_SMALL_BASE * RENDER_SCALE
EVENT_TIME_WIDTH = EVENT_TIME_WIDTH_BASE * RENDER_SCALE
EVENT_ALL_DAY_WIDTH = EVENT_ALL_DAY_WIDTH_BASE * RENDER_SCALE
EVENT_TITLE_MARGIN = 10 * RENDER_SCALE  # Margin between time/allday and title

# --- Fonts ---
FONT_DIR = os.environ.get("FONT_DIR", "fonts")
FONT_BOLD_NAME = os.environ.get("FONT_BOLD_NAME", "DejaVuSans-Bold.ttf")
FONT_REGULAR_NAME = os.environ.get("FONT_REGULAR_NAME", "DejaVuSans.ttf")
FONT_WEATHER_ICON_NAME = os.environ.get("FONT_WEATHER_ICON_NAME", "weathericons-regular-webfont.ttf")
# Computed Font Paths
FONT_BOLD_PATH = os.path.join(FONT_DIR, FONT_BOLD_NAME)
FONT_REGULAR_PATH = os.path.join(FONT_DIR, FONT_REGULAR_NAME)
FONT_WEATHER_ICON_PATH = os.path.join(FONT_DIR, FONT_WEATHER_ICON_NAME)

# --- Data Fetching & Background Task ---
REFRESH_INTERVAL_SECONDS = 10 * 60  # Refresh every 10 minutes
WEATHER_FETCH_TIMEOUT = 10  # Timeout for weather API requests
CALDAV_FETCH_TIMEOUT = 30  # Timeout for CalDAV client connections

# --- Weather ---
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_WMO_ICON_MAP = {
    0: "\uf00d",
    1: "\uf002",
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
    96: "\uf01e",
    99: "\uf01e",
    "unknown": "\uf07b",
}
OPEN_METEO_WMO_ICON_MAP_NIGHT = {
    0: "\uf02e",
    1: "\uf086",
    2: "\uf086",
    61: "\uf019",
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
            caldav_filter_var = f"CALDAV_FILTER_NAMES_{user_hash}" # New variable name

            weather_loc = os.environ.get(weather_loc_var)
            tz_str = os.environ.get(tz_var)
            caldav_urls_str = os.environ.get(caldav_urls_var, "")
            caldav_filter_str = os.environ.get(caldav_filter_var) # Read the new variable

            if not weather_loc:
                raise ValueError(f"Missing environment variable: {weather_loc_var}")
            if not tz_str:
                raise ValueError(f"Missing environment variable: {tz_var}")

            try:
                ZoneInfo(tz_str)
            except ZoneInfoNotFoundError:
                raise ValueError(f"Invalid timezone '{tz_str}' specified in {tz_var}")

            caldav_urls = [url.strip() for url in caldav_urls_str.split(",") if url.strip()]
            USER_CONFIG[user_hash] = {"caldav_urls": caldav_urls, "weather_location": weather_loc, "timezone": tz_str}
            print(f"Loaded config for user '{user_hash}': TZ={tz_str}, Loc={weather_loc}, URLs={len(caldav_urls)}")

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
    LOADED_FONTS = {
        "time": ImageFont.truetype(FONT_BOLD_PATH, 144),  # 72 * RENDER_SCALE
        "date": ImageFont.truetype(FONT_REGULAR_PATH, 72),  # 36 * RENDER_SCALE
        "weather_temp": ImageFont.truetype(FONT_BOLD_PATH, 64),  # 32 * RENDER_SCALE
        "weather_details": ImageFont.truetype(FONT_REGULAR_PATH, 52),  # 26 * RENDER_SCALE
        "header": ImageFont.truetype(FONT_BOLD_PATH, 60),  # 30 * RENDER_SCALE
        "event_time_normal": ImageFont.truetype(FONT_BOLD_PATH, EVENT_FONT_SIZE_NORMAL),
        "event_title_normal": ImageFont.truetype(FONT_REGULAR_PATH, EVENT_FONT_SIZE_NORMAL),
        "event_time_small": ImageFont.truetype(FONT_BOLD_PATH, EVENT_FONT_SIZE_SMALL),
        "event_title_small": ImageFont.truetype(FONT_REGULAR_PATH, EVENT_FONT_SIZE_SMALL),
        "weather_icon": ImageFont.truetype(FONT_WEATHER_ICON_PATH, 160),  # 80 * RENDER_SCALE
    }
    print("Successfully pre-loaded all required fonts.")
except IOError as e:
    print(f"CRITICAL ERROR: Could not load font file: {e}")
    print(f"Ensure font files exist: Regular='{FONT_REGULAR_PATH}', Bold='{FONT_BOLD_PATH}', Weather='{FONT_WEATHER_ICON_PATH}'")
    raise RuntimeError(f"Failed to load required font file: {e}") from e

# ==============================================================================
# Data Fetching Functions (for background task)
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

    # Retrieve calendar name filters for the current user (needs access to USER_CONFIG)
    # Assuming USER_CONFIG is accessible globally here. Find the right user_hash first.
    # This function needs the user_hash to get the correct filters. Let's modify its signature.
    # --- NOTE: This requires changing the call site in refresh_all_data ---

    # Find user_hash associated with this timezone_str (assuming unique timezones for simplicity, might need better mapping)
    current_user_hash = None
    for uh, cfg in USER_CONFIG.items():
        if cfg["timezone"] == timezone_str and cfg["caldav_urls"] == caldav_urls: # Find user by matching config
             current_user_hash = uh
             break

    caldav_filters = None
    if current_user_hash:
        caldav_filters = USER_CONFIG[current_user_hash].get("caldav_filters")


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
                    print(f"  Searching calendar: {calendar.name}") # Process this calendar

                    results = calendar.date_search(start=start_date_local, end=end_date_local, expand=True)

                    for event in results:
                        # --- RECURRENCE DEBUG ---
                        print(f"  Processing result: Event URL: {getattr(event, 'url', 'N/A')}, Event ID: {getattr(event, 'id', 'N/A')}")
                        # print(f"    Raw event data: {event.data}") # Potentially very verbose, uncomment if needed
                        # --- END RECURRENCE DEBUG ---
                        try:
                            # Load the full iCalendar component for the event/instance
                            ical_component = event.load().icalendar_component
                            # print(f"    Loaded iCal component: {ical_component}") # Also verbose

                            summary_comp = ical_component.get("summary")
                            dtstart_comp = ical_component.get("dtstart")
                            recurrence_id_comp = ical_component.get("recurrence-id") # Get recurrence ID component

                            if not summary_comp or not dtstart_comp:
                                print(f"    Skipping event: Missing summary or dtstart. Raw dtstart: {dtstart_comp}")
                                continue

                            summary = str(summary_comp)
                            original_start_time_obj = dtstart_comp.dt # Keep original for reference/fallback

                            # --- Determine the actual start time for this instance ---
                            instance_start_time_obj = original_start_time_obj # Default to original dtstart
                            using_recurrence_id = False
                            if recurrence_id_comp:
                                recurrence_dt = recurrence_id_comp.dt
                                print(f"      Detected Recurrence-ID: {recurrence_dt}") # DEBUG
                                # Prefer recurrence ID if it's a datetime (for timed events)
                                if isinstance(recurrence_dt, datetime.datetime):
                                    instance_start_time_obj = recurrence_dt
                                    using_recurrence_id = True
                                    print(f"      Using Recurrence-ID (datetime) as instance start: {instance_start_time_obj}") # DEBUG
                                # If recurrence ID is a date, check if original was all-day
                                elif isinstance(recurrence_dt, datetime.date):
                                    original_is_all_day = isinstance(original_start_time_obj, datetime.date) and not isinstance(original_start_time_obj, datetime.datetime)
                                    if original_is_all_day:
                                        instance_start_time_obj = recurrence_dt # Use the date for all-day instance
                                        using_recurrence_id = True
                                        print(f"      Using Recurrence-ID (date) as instance start: {instance_start_time_obj}") # DEBUG
                                    else:
                                        # This is tricky: original was timed, recurrence ID is just a date.
                                        # Combine recurrence date with original time?
                                        # For now, log and fall back to original dtstart.
                                        # TODO: Potentially combine recurrence_dt with original_start_time_obj.time() and tzinfo
                                        print(f"      Warning: Timed event has date-only Recurrence-ID. Falling back to original dtstart for this instance.")
                                else:
                                    print(f"      Warning: Unexpected Recurrence-ID type: {type(recurrence_dt)}. Using original dtstart.")
                            # --- End Determine actual start time ---

                            # --- Determine if All Day based on the *instance* start time ---
                            is_all_day = isinstance(instance_start_time_obj, datetime.date) and not isinstance(instance_start_time_obj, datetime.datetime)
                            print(f"      Instance Is All Day: {is_all_day}") # DEBUG

                            # --- DETAILED TIMEZONE DEBUG ---
                            raw_tzinfo = getattr(instance_start_time_obj, 'tzinfo', 'N/A (Not datetime)')
                            recurrence_id_log_str = f", Recurrence-ID used: {using_recurrence_id}" # Renamed variable
                            print(f"    Processing event: '{summary}', Instance start: {instance_start_time_obj}, Type: {type(instance_start_time_obj)}, Raw TZInfo: {raw_tzinfo}{recurrence_id_log_str}") # DEBUG
                            # --- END DETAILED TIMEZONE DEBUG ---


                            # --- Localize and Format ---
                            if is_all_day:
                                # Combine the date part with midnight, then make timezone aware
                                naive_dt = datetime.datetime.combine(instance_start_time_obj, datetime.time.min)
                                event_start_local = naive_dt.replace(tzinfo=user_tz) # Assign local timezone
                                time_str = "All Day"
                            elif isinstance(instance_start_time_obj, datetime.datetime):
                                # Handle timezone: Convert aware times, assume naive times are in user's TZ
                                if instance_start_time_obj.tzinfo:
                                    event_start_local = instance_start_time_obj.astimezone(user_tz)
                                else: # Naive datetime
                                    # Assign user's timezone directly
                                    event_start_local = instance_start_time_obj.replace(tzinfo=user_tz)
                                time_str = event_start_local.strftime("%H:%M")
                            else: # Should not happen
                                print(f"    Skipping event '{summary}': Unexpected instance_start_time_obj type: {type(instance_start_time_obj)}")
                                continue

                            details = {"time": time_str, "title": summary, "sort_key": event_start_local}
                            print(f"      -> Localized Instance Start: {event_start_local}, Time Str: '{time_str}'") # DEBUG

                            # Add event to the correct list if not already added (using localized instance start time)
                            if today_start <= event_start_local < today_end:
                                print(f"      -> Categorizing as Today") # DEBUG
                                if is_all_day:
                                    if summary not in added_all_today_titles:
                                        print(f"      -> Adding to all_today") # DEBUG
                                        all_today.append(details)
                                        added_all_today_titles.add(summary)
                                    else: # DEBUG
                                        print(f"      -> Skipping all_today (duplicate title: {summary})") # DEBUG
                                else:
                                    event_key = (time_str, summary)
                                    if event_key not in added_timed_today_keys:
                                        print(f"      -> Adding to timed_today") # DEBUG
                                        print(f"      -> Adding to timed_today") # DEBUG
                                        timed_today.append(details)
                                        added_timed_today_keys.add(event_key)
                                    else: # DEBUG
                                        print(f"      -> Skipping timed_today (duplicate key: {event_key})") # DEBUG
                            elif tomorrow_start <= event_start_local < tomorrow_end:
                                print(f"      -> Categorizing as Tomorrow") # DEBUG
                                if is_all_day:
                                    if summary not in added_all_tomorrow_titles:
                                        print(f"      -> Adding to all_tomorrow") # DEBUG
                                        print(f"      -> Adding to all_tomorrow") # DEBUG
                                        all_tomorrow.append(details)
                                        added_all_tomorrow_titles.add(summary)
                                    else: # DEBUG
                                        print(f"      -> Skipping all_tomorrow (duplicate title: {summary})") # DEBUG
                                else:
                                    event_key = (time_str, summary)
                                    if event_key not in added_timed_tomorrow_keys:
                                        print(f"      -> Adding to timed_tomorrow") # DEBUG
                                        print(f"      -> Adding to timed_tomorrow") # DEBUG
                                        timed_tomorrow.append(details)
                                        added_timed_tomorrow_keys.add(event_key)
                                    else: # DEBUG
                                        print(f"      -> Skipping timed_tomorrow (duplicate key: {event_key})") # DEBUG
                            else: # DEBUG
                                print(f"      -> Skipping event: Instance start {event_start_local} is Outside Today/Tomorrow range ({today_start} to {tomorrow_end})") # DEBUG
                        except Exception as event_ex:
                            print(f"    Error processing event '{summary if 'summary' in locals() else 'UNKNOWN'}': {event_ex}")
                            traceback.print_exc() # DEBUG - More detail on event processing errors

        except caldav.lib.error.AuthorizationError:
            err_msg = f"Auth Fail: {url_display_name}"
        except requests.exceptions.Timeout:
            err_msg = f"Timeout: {url_display_name}"
        except requests.exceptions.ConnectionError:
            err_msg = f"Connect Fail: {url_display_name}"
        except Exception as cal_ex:
            err_msg = f"Load Fail: {url_display_name}"
            print(f"  Error: {cal_ex}")
            traceback.print_exc()
        else:
            continue
        print(f"  {err_msg}")
        errors.append({"time": "ERR", "title": err_msg, "sort_key": today_start})

    all_today.sort(key=lambda x: x["title"])
    timed_today.sort(key=lambda x: x["sort_key"])
    all_tomorrow.sort(key=lambda x: x["title"])
    timed_tomorrow.sort(key=lambda x: x["sort_key"])

    return errors + all_today + timed_today, all_tomorrow + timed_tomorrow


# ==============================================================================
# Background Data Refresh Task
# ==============================================================================


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
        user_tz = ZoneInfo(timezone_str)

        # Fetch Weather
        weather_info = fetch_weather_data(location, timezone_str)

        # Fetch Calendar Events
        now_local = datetime.datetime.now(user_tz)
        start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        # Fetch events slightly beyond tomorrow to catch multi-day events correctly
        end_of_fetch_range = start_of_today + datetime.timedelta(days=2)

        # Get filters for this user
        caldav_filters = config.get("caldav_filters")

        # Pass filters to the fetch function
        today_events, tomorrow_events = fetch_calendar_events(
            caldav_urls, start_of_today, end_of_fetch_range, timezone_str, caldav_filters
        )

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


# ==============================================================================
# Image Generation
# ==============================================================================


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


def generate_image(current_datetime_local, weather_info, today_events, tomorrow_events):
    """Generates the display image using pre-fetched data."""
    img_large = Image.new("L", (IMG_WIDTH, IMG_HEIGHT), color=WHITE_COLOR)  # Use constant
    draw = ImageDraw.Draw(img_large)
    fonts = LOADED_FONTS  # Use pre-loaded fonts

    # Format current time and date strings
    current_time_str = current_datetime_local.strftime("%H:%M")
    current_date_str = current_datetime_local.strftime("%A, %d %B")

    total_events = len(today_events) + len(tomorrow_events)
    use_small_font = total_events > EVENT_COUNT_THRESHOLD
    event_time_font = fonts["event_time_small"] if use_small_font else fonts["event_time_normal"]
    event_title_font = fonts["event_title_small"] if use_small_font else fonts["event_title_normal"]

    # --- Draw Left Pane ---
    time_bbox = draw.textbbox((0, 0), current_time_str, font=fonts["time"])
    time_x = (LEFT_PANE_WIDTH - (time_bbox[2] - time_bbox[0])) // 2
    time_y = PADDING + (10 * RENDER_SCALE)
    draw.text((time_x, time_y), current_time_str, font=fonts["time"], fill=BLACK_COLOR)

    date_bbox = draw.textbbox((0, 0), current_date_str, font=fonts["date"])
    date_x = (LEFT_PANE_WIDTH - (date_bbox[2] - date_bbox[0])) // 2
    date_y = time_y + (time_bbox[3] - time_bbox[1]) + (15 * RENDER_SCALE)
    draw.text((date_x, date_y), current_date_str, font=fonts["date"], fill=BLACK_COLOR)

    weather_section_h = 120 * RENDER_SCALE
    weather_y_start = IMG_HEIGHT - PADDING - weather_section_h
    icon_x, icon_y = PADDING, weather_y_start + (10 * RENDER_SCALE)

    temp, high, low, hum, wmo_code, is_day = (None,) * 6  # Defaults
    if weather_info:
        temp, high, low, hum = (weather_info.get(k) for k in ("temp", "high", "low", "humidity"))
        wmo_code, is_day = weather_info.get("icon_code", "unknown"), weather_info.get("is_day", 1)
    else:
        wmo_code, is_day = "unknown", 1

    icon_char = (
        OPEN_METEO_WMO_ICON_MAP_NIGHT.get(wmo_code)
        if not is_day and wmo_code in OPEN_METEO_WMO_ICON_MAP_NIGHT
        else OPEN_METEO_WMO_ICON_MAP.get(wmo_code, OPEN_METEO_WMO_ICON_MAP["unknown"])
    )
    draw.text((icon_x, icon_y), icon_char, font=fonts["weather_icon"], fill=BLACK_COLOR)

    icon_w = 80 * RENDER_SCALE  # Assumed width for positioning text
    text_x, text_y = icon_x + icon_w + (15 * RENDER_SCALE), icon_y + (5 * RENDER_SCALE)
    temp_str = f"{temp:.0f}°C" if isinstance(temp, (int, float)) else "--°C"
    hilo_str = f"H:{high:.0f}° L:{low:.0f}°" if isinstance(high, (int, float)) and isinstance(low, (int, float)) else "H:--° L:--°"
    hum_str = f"Hum: {hum:.0f}%" if isinstance(hum, (int, float)) else "Hum: --%"
    draw.text((text_x, text_y), temp_str, font=fonts["weather_temp"], fill=BLACK_COLOR)
    text_y += sum(fonts["weather_temp"].getmetrics()) + (4 * RENDER_SCALE)
    draw.text((text_x, text_y), hilo_str, font=fonts["weather_details"], fill=BLACK_COLOR)
    text_y += sum(fonts["weather_details"].getmetrics()) + (4 * RENDER_SCALE)
    draw.text((text_x, text_y), hum_str, font=fonts["weather_details"], fill=BLACK_COLOR)

    # --- Draw Right Pane ---
    line_w = 1 * RENDER_SCALE
    draw.line([(LEFT_PANE_WIDTH, 0), (LEFT_PANE_WIDTH, IMG_HEIGHT)], fill=BLACK_COLOR, width=line_w)
    col_div_x = LEFT_PANE_WIDTH + COL_WIDTH
    draw.line([(col_div_x, 0), (col_div_x, IMG_HEIGHT)], fill=BLACK_COLOR, width=line_w)
    header_y = (PADDING // RENDER_SCALE) * RENDER_SCALE
    head_bbox = draw.textbbox((0, 0), "Today", font=fonts["header"])
    draw.text((LEFT_PANE_WIDTH + PADDING, header_y), "Today", font=fonts["header"], fill=BLACK_COLOR)
    draw.text((col_div_x + PADDING, header_y), "Tomorrow", font=fonts["header"], fill=BLACK_COLOR)
    event_y_start = header_y + (head_bbox[3] - head_bbox[1]) + (15 * RENDER_SCALE)
    event_title_margin = EVENT_TITLE_MARGIN

    # Today Column
    y_today = event_y_start
    for event in today_events:
        if y_today > IMG_HEIGHT - PADDING:
            break
        time_str = event.get("time", "--:--")
        title_str = event.get("title", "No Title")
        is_all_day = time_str == "All Day"
        is_error = time_str == "ERR"

        # Determine color: Gray if past timed event, black otherwise
        event_color = BLACK_COLOR
        if not is_all_day and not is_error:
            event_start_time = event.get("sort_key")
            if event_start_time and event_start_time < current_datetime_local:
                event_color = GRAY_COLOR  # Event has passed

        time_w = EVENT_ALL_DAY_WIDTH if is_all_day else EVENT_TIME_WIDTH
        time_x_offset = PADDING // 2 if is_all_day else PADDING
        draw.text((LEFT_PANE_WIDTH + time_x_offset, y_today), time_str, font=event_time_font, fill=event_color)

        title_x = LEFT_PANE_WIDTH + PADDING + (EVENT_ALL_DAY_WIDTH if is_all_day else EVENT_TIME_WIDTH) + event_title_margin
        title_max_w = COL_WIDTH - PADDING - (EVENT_ALL_DAY_WIDTH if is_all_day else EVENT_TIME_WIDTH) - event_title_margin - PADDING
        y_today = draw_text_with_wrapping(draw, title_str, (title_x, y_today), event_title_font, title_max_w, fill=event_color)
        y_today += 10 * RENDER_SCALE  # Spacing between events

    # Tomorrow Column (Always black)
    y_tmrw = event_y_start
    for event in tomorrow_events:
        if y_tmrw > IMG_HEIGHT - PADDING:
            break
        time_str = event.get("time", "--:--")
        title_str = event.get("title", "No Title")
        is_all_day = time_str == "All Day"
        time_w = EVENT_ALL_DAY_WIDTH if is_all_day else EVENT_TIME_WIDTH
        time_x_offset = PADDING // 2 if is_all_day else PADDING
        draw.text((col_div_x + time_x_offset, y_tmrw), time_str, font=event_time_font, fill=BLACK_COLOR)
        title_x = col_div_x + PADDING + (EVENT_ALL_DAY_WIDTH if is_all_day else EVENT_TIME_WIDTH) + event_title_margin
        title_max_w = COL_WIDTH - PADDING - (EVENT_ALL_DAY_WIDTH if is_all_day else EVENT_TIME_WIDTH) - event_title_margin - PADDING
        y_tmrw = draw_text_with_wrapping(draw, title_str, (title_x, y_tmrw), event_title_font, title_max_w, fill=BLACK_COLOR)
        y_tmrw += 10 * RENDER_SCALE

    # --- Downscale and Return ---
    img_final = img_large.resize((TARGET_IMG_WIDTH, TARGET_IMG_HEIGHT), Image.Resampling.LANCZOS)
    return img_final


def img_to_bytes(img):
    """Converts PIL Image object to PNG image bytes."""
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr


# ==============================================================================
# Flask Route
# ==============================================================================
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

    # Get current time/date for display (independent of fetched data time)
    now_user_tz = datetime.datetime.now(user_tz)
    # current_time_str = now_user_tz.strftime("%H:%M") # No longer needed separately
    # current_date_str = now_user_tz.strftime("%A, %d %B") # No longer needed separately

    # Use the fetched data
    weather_info = user_data.get("weather")  # Could be None if fetch failed
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
# Main Execution & Background Task Start
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

    print("Starting Flask development server...")
    # Note: Flask's built-in server is NOT recommended for production.
    # Use Gunicorn or another WSGI server via Docker as planned.
    # Disable reloader when using background threads like this for stability.
    app.run(host="0.0.0.0", port=5050, debug=False, use_reloader=False)

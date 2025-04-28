# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "caldav",
#     "flask",
#     "gunicorn",
#     "icalendar",
#     "pillow",
#     "python-dotenv",
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
import caldav
import requests
from dotenv import load_dotenv
from flask import Flask, abort, send_file
from icalendar import Calendar
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# Load Environment Variables (.env file takes lower precedence)
# ==============================================================================
load_dotenv()
print("Attempted to load configuration from .env file (if present).")


# ==============================================================================
# Configuration Constants
# ==============================================================================

# --- Colors ---
COLOR_BLACK = 0
COLOR_GRAY = 128  # Mid-gray for 'L' mode (used for past events)
COLOR_WHITE = 255

# --- Image Settings ---
IMAGE_WIDTH = 960
IMAGE_HEIGHT = 540

# --- Layout ---
LAYOUT_PADDING = 20
LAYOUT_LEFT_PANE_WIDTH = 320
LAYOUT_RIGHT_PANE_WIDTH = IMAGE_WIDTH - LAYOUT_LEFT_PANE_WIDTH
LAYOUT_COLUMN_WIDTH = LAYOUT_RIGHT_PANE_WIDTH // 2  # Width of Today/Tomorrow columns
LAYOUT_DIVIDER_LINE_WIDTH = 1
LAYOUT_TIME_DATE_SPACING = 25  # Vertical space between time and date
LAYOUT_WEATHER_DETAILS_SPACING = 4  # Vertical space within weather text block
LAYOUT_WEATHER_ICON_V_ADJUST = 5  # Pixels to adjust weather icon vertically relative to bottom alignment
LAYOUT_EVENT_SPACING_AFTER = 6  # Vertical space after an event entry
LAYOUT_EVENT_TITLE_MARGIN = 10  # Horizontal space between event time and title
LAYOUT_EVENT_LINE_SPACING_EXTRA = 1  # Extra vertical space between wrapped text lines

# --- Fonts ---
#   Font Files & Paths (Environment variables override defaults)
FONT_DIR = os.environ.get("FONT_DIR", "fonts")
FONT_FILE_BOLD = os.environ.get("FONT_BOLD_NAME", "Inter.ttc")
FONT_FILE_REGULAR = os.environ.get("FONT_REGULAR_NAME", "Inter.ttc")
FONT_FILE_WEATHER = os.environ.get("FONT_WEATHER_ICON_NAME", "weathericons-regular-webfont.ttf")
FONT_PATH_BOLD = os.path.join(FONT_DIR, FONT_FILE_BOLD)
FONT_PATH_REGULAR = os.path.join(FONT_DIR, FONT_FILE_REGULAR)
FONT_PATH_WEATHER = os.path.join(FONT_DIR, FONT_FILE_WEATHER)
#   Font Sizes
FONT_SIZE_DATE = 30
FONT_SIZE_EVENT_TIME = 22
FONT_SIZE_EVENT_TITLE = 22
FONT_SIZE_HEADER = 26  # For "Today", "Tomorrow"
FONT_SIZE_TIME = 72
FONT_SIZE_WEATHER_DETAILS = 26  # For Hi/Lo, Humidity
FONT_SIZE_WEATHER_ICON = 80
FONT_SIZE_WEATHER_TEMP = 32

# --- Data Fetching & Background Task ---
FETCH_CALDAV_TIMEOUT = 30
FETCH_WEATHER_TIMEOUT = 10
REFRESH_INTERVAL_SECONDS = 10 * 60

# --- Weather API & Icons ---
API_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
API_OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
# Weather Icons from weathericons-regular-webfont.ttf (Unicode Private Use Area)
WEATHER_ICON_MAP_DAY = {
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
WEATHER_ICON_MAP_NIGHT = {0: "\uf02e", 1: "\uf086", 2: "\uf086"}  # Overrides for night

# ==============================================================================
# Global State & App Initialization
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

            # Construct environment variable names dynamically
            weather_loc_var = f"WEATHER_LOCATION_{user_hash}"
            tz_var = f"TIMEZONE_{user_hash}"
            caldav_urls_var = f"CALDAV_URLS_{user_hash}"
            caldav_filter_var = f"CALDAV_FILTER_NAMES_{user_hash}"

            # Retrieve values from environment (could be from OS or .env)
            weather_loc = os.environ.get(weather_loc_var)
            tz_str = os.environ.get(tz_var)
            caldav_urls_str = os.environ.get(caldav_urls_var, "")
            caldav_filter_str = os.environ.get(caldav_filter_var)

            # Validate required configuration
            if not weather_loc:
                raise ValueError(f"Missing configuration: {weather_loc_var}")
            if not tz_str:
                raise ValueError(f"Missing configuration: {tz_var}")

            # Validate Timezone
            try:
                user_tz = ZoneInfo(tz_str)
            except ZoneInfoNotFoundError:
                raise ValueError(f"Invalid timezone '{tz_str}' in {tz_var}")

            # Parse CalDAV URLs
            caldav_urls = [url.strip() for url in caldav_urls_str.split(",") if url.strip()]

            # Parse CalDAV calendar name filters (optional, case-insensitive)
            caldav_filters = None
            if caldav_filter_str:
                caldav_filters = {name.strip().lower() for name in caldav_filter_str.split(",") if name.strip()}

            # Store validated configuration for the user hash
            USER_CONFIG[user_hash] = {
                "caldav_urls": caldav_urls,
                "weather_location": weather_loc,
                "timezone": tz_str,
                "timezone_obj": user_tz,  # Store the ZoneInfo object for efficiency
                "caldav_filters": caldav_filters,
            }
            filter_msg = f"Yes: {', '.join(caldav_filters)}" if caldav_filters else "No"
            print(f"Loaded config for user '{user_hash}': TZ={tz_str}, Loc={weather_loc}, URLs={len(caldav_urls)}, Filters={filter_msg}")

except ValueError as e:
    print(f"Configuration Error: {e}")
    raise
except Exception as e:
    print(f"Unexpected error loading user configuration: {e}")
    traceback.print_exc()
    raise RuntimeError("Failed to load user configuration") from e

# Final check after parsing all hashes
if not USER_CONFIG and USER_HASHES_STR:
    print("Error: USER_HASHES is set, but no valid user configurations could be loaded.")
    raise RuntimeError("Failed to load any valid user configurations.")
elif not USER_CONFIG:
    print("Warning: No users configured.")

# ==============================================================================
# Font Loading
# ==============================================================================
LOADED_FONTS = {}
try:
    # Load fonts using computed sizes and specific paths
    # Assumes Inter.ttc indices: 0=Regular, 1=Bold (adjust index if your font differs)
    LOADED_FONTS["time"] = ImageFont.truetype(FONT_PATH_BOLD, FONT_SIZE_TIME, index=1)
    LOADED_FONTS["date"] = ImageFont.truetype(FONT_PATH_REGULAR, FONT_SIZE_DATE, index=0)
    LOADED_FONTS["header"] = ImageFont.truetype(FONT_PATH_BOLD, FONT_SIZE_HEADER, index=1)
    LOADED_FONTS["event_time"] = ImageFont.truetype(FONT_PATH_BOLD, FONT_SIZE_EVENT_TIME, index=1)
    LOADED_FONTS["event_title"] = ImageFont.truetype(FONT_PATH_REGULAR, FONT_SIZE_EVENT_TITLE, index=0)
    LOADED_FONTS["weather_temp"] = ImageFont.truetype(FONT_PATH_BOLD, FONT_SIZE_WEATHER_TEMP, index=1)
    LOADED_FONTS["weather_details"] = ImageFont.truetype(FONT_PATH_REGULAR, FONT_SIZE_WEATHER_DETAILS, index=0)
    LOADED_FONTS["weather_icon"] = ImageFont.truetype(FONT_PATH_WEATHER, FONT_SIZE_WEATHER_ICON)
    print("Successfully pre-loaded all required fonts.")
except IOError as e:
    print(f"CRITICAL ERROR: Could not load font file: {e}")
    print(f"Ensure font files exist at specified paths: Bold='{FONT_PATH_BOLD}', Regular='{FONT_PATH_REGULAR}', Weather='{FONT_PATH_WEATHER}'")
    raise RuntimeError(f"Failed to load required font file: {e}") from e
except Exception as e:
    print(f"CRITICAL ERROR: Unexpected error loading fonts: {e}")
    raise RuntimeError(f"Failed to load fonts: {e}") from e


# ==============================================================================
# Helper Function Definitions (Sorted Alphabetically)
# ==============================================================================


def _draw_date_section(draw, current_datetime_local, fonts, pane_width, start_y):
    """Draws the date string, centered horizontally, below the given start_y."""
    date_font = fonts["date"]
    current_date_str = current_datetime_local.strftime("%a, %d %b")
    date_bbox = draw.textbbox((0, 0), current_date_str, font=date_font)
    date_width = date_bbox[2] - date_bbox[0]
    date_height = date_bbox[3] - date_bbox[1]
    date_x = (pane_width - date_width) // 2
    draw.text((date_x, start_y), current_date_str, font=date_font, fill=COLOR_BLACK)
    return start_y + date_height


def _draw_event_column(draw, events, column_x_start, column_width, y_start, fonts, max_y, current_time=None, default_color=COLOR_BLACK):
    """Draws a column of events, handling wrapping and past event graying."""
    y_pos = y_start
    event_time_font = fonts["event_time"]
    event_title_font = fonts["event_title"]
    col_padding = LAYOUT_PADDING
    title_x_no_time = column_x_start + col_padding
    title_max_width_no_time = column_width - (2 * col_padding)

    sample_time_bbox = draw.textbbox((0, 0), "00:00", font=event_time_font)
    actual_time_width = sample_time_bbox[2] - sample_time_bbox[0]
    title_x_with_time = column_x_start + col_padding + actual_time_width + LAYOUT_EVENT_TITLE_MARGIN
    title_max_width_with_time = column_width - col_padding - actual_time_width - LAYOUT_EVENT_TITLE_MARGIN - col_padding

    for event in events:
        if y_pos > max_y:
            break

        time_str = event.get("time", "--:--")
        title_str = event.get("title", "No Title")
        is_all_day = time_str == "All Day"
        is_error = time_str == "ERR"
        event_color = default_color

        # Gray out past timed events if current_time is provided
        if current_time and not is_all_day and not is_error:
            event_start_time = event.get("sort_key")
            if event_start_time and isinstance(event_start_time, datetime.datetime) and event_start_time.tzinfo is not None:
                if event_start_time < current_time:
                    event_color = COLOR_GRAY
            elif event_start_time:
                print(f"Warning: Event '{title_str}' has unexpected sort_key type: {type(event_start_time)}")

        time_x = column_x_start + col_padding
        if not is_all_day and not is_error:
            draw.text((time_x, y_pos), time_str, font=event_time_font, fill=event_color)
            title_x = title_x_with_time
            title_max_w = title_max_width_with_time
        else:
            title_x = title_x_no_time
            title_max_w = title_max_width_no_time
            if is_all_day:
                draw.text((time_x, y_pos), time_str, font=event_title_font, fill=event_color)
                title_x = title_x_no_time

        y_after_title = draw_text_with_wrapping(draw, title_str, (title_x, y_pos), event_title_font, title_max_w, fill=event_color)

        ascent, descent = event_title_font.getmetrics()
        line_height = ascent + descent
        min_event_height = line_height + LAYOUT_EVENT_SPACING_AFTER
        actual_event_height = (y_after_title - y_pos) + LAYOUT_EVENT_SPACING_AFTER
        y_pos += max(min_event_height, actual_event_height)


def _draw_time_section(draw, current_datetime_local, fonts, pane_width, start_y):
    """Draws the time string, centered horizontally, at the given start_y."""
    time_font = fonts["time"]
    current_time_str = current_datetime_local.strftime("%H:%M")
    time_bbox = draw.textbbox((0, 0), current_time_str, font=time_font)
    time_width = time_bbox[2] - time_bbox[0]
    time_height = time_bbox[3] - time_bbox[1]
    time_x = (pane_width - time_width) // 2
    draw.text((time_x, start_y), current_time_str, font=time_font, fill=COLOR_BLACK)
    return start_y + time_height


def _draw_weather_section(draw, weather_info, fonts, pane_width, bottom_y):
    """Draws the weather icon and details, aligned to the bottom_y coordinate."""
    weather_icon_font = fonts["weather_icon"]
    weather_temp_font = fonts["weather_temp"]
    weather_details_font = fonts["weather_details"]

    temp, high, low, hum, wmo_code, is_day = (None,) * 6
    if weather_info:
        temp = weather_info.get("temp")
        high = weather_info.get("high")
        low = weather_info.get("low")
        hum = weather_info.get("humidity")
        wmo_code = weather_info.get("icon_code", "unknown")
        is_day = weather_info.get("is_day", 1)
    else:
        wmo_code, is_day = "unknown", 1

    temp_str = f"{temp:.0f}°C" if isinstance(temp, (int, float)) else "--°C"
    hilo_str = f"H:{high:.0f}° L:{low:.0f}°" if isinstance(high, (int, float)) and isinstance(low, (int, float)) else "H:--° L:--°"
    hum_str = f"Hum: {hum:.0f}%" if isinstance(hum, (int, float)) else "Hum: --%"
    icon_char = (
        WEATHER_ICON_MAP_NIGHT.get(wmo_code)
        if not is_day and wmo_code in WEATHER_ICON_MAP_NIGHT
        else WEATHER_ICON_MAP_DAY.get(wmo_code, WEATHER_ICON_MAP_DAY["unknown"])
    )

    icon_bbox = draw.textbbox((0, 0), icon_char, font=weather_icon_font)
    icon_width, icon_height = icon_bbox[2] - icon_bbox[0], icon_bbox[3] - icon_bbox[1]
    temp_bbox = draw.textbbox((0, 0), temp_str, font=weather_temp_font)
    temp_width, temp_height = temp_bbox[2] - temp_bbox[0], temp_bbox[3] - temp_bbox[1]
    hilo_bbox = draw.textbbox((0, 0), hilo_str, font=weather_details_font)
    hilo_width, hilo_height = hilo_bbox[2] - hilo_bbox[0], hilo_bbox[3] - hilo_bbox[1]
    hum_bbox = draw.textbbox((0, 0), hum_str, font=weather_details_font)
    hum_width, hum_height = hum_bbox[2] - hum_bbox[0], hum_bbox[3] - hum_bbox[1]

    weather_text_block_height = temp_height + LAYOUT_WEATHER_DETAILS_SPACING + hilo_height + LAYOUT_WEATHER_DETAILS_SPACING + hum_height
    weather_text_block_width = max(temp_width, hilo_width, hum_width)
    weather_padding_between = LAYOUT_PADDING
    total_weather_width = icon_width + weather_padding_between + weather_text_block_width
    weather_x_start = (pane_width - total_weather_width) // 2
    icon_x = weather_x_start
    text_x = icon_x + icon_width + weather_padding_between

    text_y_start = bottom_y - weather_text_block_height
    icon_y = bottom_y - icon_height - LAYOUT_WEATHER_ICON_V_ADJUST

    draw.text((icon_x, icon_y), icon_char, font=weather_icon_font, fill=COLOR_BLACK)
    current_text_y = text_y_start
    draw.text((text_x, current_text_y), temp_str, font=weather_temp_font, fill=COLOR_BLACK)
    current_text_y += temp_height + LAYOUT_WEATHER_DETAILS_SPACING
    draw.text((text_x, current_text_y), hilo_str, font=weather_details_font, fill=COLOR_BLACK)
    current_text_y += hilo_height + LAYOUT_WEATHER_DETAILS_SPACING
    draw.text((text_x, current_text_y), hum_str, font=weather_details_font, fill=COLOR_BLACK)


def _fetch_lat_lon(location_name, session):
    """Internal helper to fetch latitude/longitude using Open-Meteo Geocoding."""
    params = {"name": location_name, "count": 1, "language": "en", "format": "json"}
    try:
        response = session.get(API_OPEN_METEO_GEOCODE_URL, params=params, timeout=FETCH_WEATHER_TIMEOUT // 2)
        response.raise_for_status()
        data = response.json()
        if data and data.get("results"):
            result = data["results"][0]
            lat, lon = result.get("latitude"), result.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return lat, lon
            else:
                print(f"Warning: Geocoding for '{location_name}' returned invalid lat/lon types: {lat}, {lon}")
        else:
            print(f"Warning: Geocoding failed for '{location_name}'. No results found.")
    except requests.exceptions.Timeout:
        print(f"Error: Geocoding request for '{location_name}' timed out.")
    except requests.exceptions.RequestException as e:
        print(f"Error during geocoding request for '{location_name}': {e}")
    except (KeyError, IndexError, ValueError) as e:
        print(f"Error processing geocoding response for '{location_name}': {e}")
    except Exception as e:
        print(f"Unexpected error during geocoding for '{location_name}': {e}")
        traceback.print_exc()
    return None, None


def background_refresh_loop():
    """Runs the refresh_all_data function periodically in a background thread."""
    print("Background refresh thread started.")
    while True:
        time.sleep(REFRESH_INTERVAL_SECONDS)
        print(f"Background thread: Woke up, attempting refresh at {datetime.datetime.now()}")
        try:
            refresh_all_data()
            print(f"Background thread: Refresh cycle completed.")
        except Exception as e:
            print(f"ERROR in background refresh loop: {e}")
            traceback.print_exc()


def draw_text_with_wrapping(draw, text, position, font, max_width, fill=COLOR_BLACK):
    """Draws text, wrapping lines to fit max_width. Returns Y coord below text."""
    lines = []
    words = text.split()
    if not words:
        return position[1]

    current_line = words[0]
    for word in words[1:]:
        try:
            bbox = draw.textbbox((0, 0), f"{current_line} {word}", font=font)
            line_width = bbox[2] - bbox[0]
        except Exception as e:
            print(f"Warning: Error getting textbbox in draw_text_with_wrapping: {e}. Text: '{current_line} {word}'")
            line_width = max_width + 1

        if line_width <= max_width:
            current_line = f"{current_line} {word}"
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)

    x, y = position
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + LAYOUT_EVENT_LINE_SPACING_EXTRA

    return y - LAYOUT_EVENT_LINE_SPACING_EXTRA


def fetch_calendar_events(caldav_urls, start_date_local, end_date_local, user_tz, caldav_filters=None):
    """
    Fetches and processes calendar events from CalDAV URLs for today and tomorrow.
    Handles all-day/timed events, recurrence, timezones, filtering, and basic errors.
    """
    all_today, timed_today, all_tomorrow, timed_tomorrow, errors = [], [], [], [], []
    # Use sets for efficient duplicate checking *per day*
    added_all_today_titles, added_timed_today_keys = set(), set()
    added_all_tomorrow_titles, added_timed_tomorrow_keys = set(), set()

    # Define date ranges based on the local start date
    today_start = start_date_local
    today_end = today_start + datetime.timedelta(days=1)
    tomorrow_start = today_end
    tomorrow_end = tomorrow_start + datetime.timedelta(days=1)
    print(f"Fetching calendar events from {today_start.strftime('%Y-%m-%d')} to {end_date_local.strftime('%Y-%m-%d')} for timezone {user_tz}")

    for url in caldav_urls:
        username, password, url_display_name = None, None, url
        try:
            parsed_url = urllib.parse.urlparse(url)
            url_display_name = parsed_url.hostname or url
            if parsed_url.username:
                username = urllib.parse.unquote(parsed_url.username)
            if parsed_url.password:
                password = urllib.parse.unquote(parsed_url.password)
            url_no_creds = parsed_url._replace(netloc=parsed_url.hostname + (f":{parsed_url.port}" if parsed_url.port else "")).geturl()
            print(f"  Connecting to: {url_no_creds} (as user: {'yes' if username else 'no'})")

            with caldav.DAVClient(url=url_no_creds, username=username, password=password, timeout=FETCH_CALDAV_TIMEOUT) as client:
                principal = client.principal()
                calendars = principal.calendars()
                if not calendars:
                    print(f"    No calendars found at {url_display_name}.")
                    continue

                for calendar in calendars:
                    calendar_name_lower = getattr(calendar, "name", "").lower()
                    if caldav_filters and calendar_name_lower not in caldav_filters:
                        continue

                    # Fetch events, expand=True handles recurrence
                    results = calendar.date_search(start=start_date_local, end=end_date_local, expand=True)

                    for event in results:
                        summary = "UNKNOWN_EVENT"
                        ical_component = None
                        try:
                            if not hasattr(event, "data") or not event.data:
                                continue

                            ics_data = event.data
                            if isinstance(ics_data, bytes):
                                try:
                                    ics_data = ics_data.decode("utf-8")
                                except UnicodeDecodeError:
                                    ics_data = ics_data.decode("latin-1", errors="replace")

                            cal = Calendar.from_ical(ics_data)

                            # Robustly get the first VEVENT
                            vevent_components = cal.walk("VEVENT")
                            ical_component = None
                            if isinstance(vevent_components, list):
                                if vevent_components:
                                    ical_component = vevent_components[0]
                            else:
                                try:
                                    ical_component = next(vevent_components, None)
                                except TypeError:
                                    print(f"      Warning: cal.walk('VEVENT') returned non-iterable type: {type(vevent_components)}.")

                            if not ical_component:
                                continue

                            summary_comp = ical_component.get("summary")
                            dtstart_comp = ical_component.get("dtstart")
                            if not summary_comp or not dtstart_comp:
                                continue
                            summary = str(summary_comp)
                            original_start_time_obj = dtstart_comp.dt

                            # Determine effective start time for this instance
                            instance_start_time_obj = original_start_time_obj
                            recurrence_id_comp = ical_component.get("recurrence-id")
                            if recurrence_id_comp:
                                recurrence_dt = recurrence_id_comp.dt
                                if isinstance(recurrence_dt, datetime.datetime):
                                    instance_start_time_obj = recurrence_dt
                                elif isinstance(recurrence_dt, datetime.date):
                                    original_is_date_only = isinstance(original_start_time_obj, datetime.date) and not isinstance(
                                        original_start_time_obj, datetime.datetime
                                    )
                                    if original_is_date_only:
                                        instance_start_time_obj = recurrence_dt
                                    elif isinstance(original_start_time_obj, datetime.datetime):
                                        instance_start_time_obj = datetime.datetime.combine(
                                            recurrence_dt, original_start_time_obj.time(), tzinfo=original_start_time_obj.tzinfo
                                        )
                                    else:
                                        instance_start_time_obj = datetime.datetime.combine(recurrence_dt, datetime.time.min)

                            # Determine if All Day & Localize Time
                            is_all_day = isinstance(instance_start_time_obj, datetime.date) and not isinstance(instance_start_time_obj, datetime.datetime)
                            event_start_local = None
                            time_str = "??:??"

                            if is_all_day:
                                naive_dt = datetime.datetime.combine(instance_start_time_obj, datetime.time.min)
                                event_start_local = user_tz.localize(naive_dt)
                                time_str = "All Day"
                            elif isinstance(instance_start_time_obj, datetime.datetime):
                                if instance_start_time_obj.tzinfo:
                                    event_start_local = instance_start_time_obj.astimezone(user_tz)
                                else:
                                    event_start_local = user_tz.localize(instance_start_time_obj)
                                time_str = event_start_local.strftime("%H:%M")
                            else:
                                continue

                            details = {"time": time_str, "title": summary, "sort_key": event_start_local}

                            # Add event to the correct list if not duplicate *for that specific day*
                            if today_start <= event_start_local < today_end:
                                if is_all_day:
                                    if summary not in added_all_today_titles:
                                        all_today.append(details)
                                        added_all_today_titles.add(summary)
                                else:
                                    key = (time_str, summary)
                                    if key not in added_timed_today_keys:
                                        timed_today.append(details)
                                        added_timed_today_keys.add(key)
                            elif tomorrow_start <= event_start_local < tomorrow_end:
                                if is_all_day:
                                    if summary not in added_all_tomorrow_titles:
                                        all_tomorrow.append(details)
                                        added_all_tomorrow_titles.add(summary)
                                else:
                                    key = (time_str, summary)
                                    if key not in added_timed_tomorrow_keys:
                                        timed_tomorrow.append(details)
                                        added_timed_tomorrow_keys.add(key)

                        except Exception as event_ex:
                            current_summary = getattr(ical_component, "get", lambda k, d=None: d)("summary", summary)
                            print(f"      Error processing event '{current_summary}' (URL: {getattr(event, 'url', 'N/A')}): {event_ex}")
                            traceback.print_exc()

        except caldav.lib.error.AuthorizationError:
            err_msg = f"Auth Fail: {url_display_name}"
            errors.append({"time": "ERR", "title": err_msg, "sort_key": today_start})
        except requests.exceptions.Timeout:
            err_msg = f"Timeout: {url_display_name}"
            errors.append({"time": "ERR", "title": err_msg, "sort_key": today_start})
        except requests.exceptions.ConnectionError:
            err_msg = f"Connect Fail: {url_display_name}"
            errors.append({"time": "ERR", "title": err_msg, "sort_key": today_start})
        except Exception as cal_ex:
            err_msg = f"Load Fail: {url_display_name}"
            print(f"  Error loading calendar {url_display_name}: {cal_ex}")
            traceback.print_exc()
            errors.append({"time": "ERR", "title": err_msg, "sort_key": today_start})

    # Sort events
    all_today.sort(key=lambda x: x["title"])
    timed_today.sort(key=lambda x: x["sort_key"])
    all_tomorrow.sort(key=lambda x: x["title"])
    timed_tomorrow.sort(key=lambda x: x["sort_key"])

    # Combine results
    return errors + all_today + timed_today, all_tomorrow + timed_tomorrow


def fetch_weather_data(location, timezone_str):
    """Fetches weather data from Open-Meteo API, returning dict or None on failure."""
    print(f"Fetching weather data for: '{location}', timezone: {timezone_str}")
    weather_data = {"temp": None, "high": None, "low": None, "humidity": None, "icon_code": "unknown", "is_day": 1}
    with requests.Session() as session:
        lat, lon = _fetch_lat_lon(location, session)
        if lat is None or lon is None:
            print(f"  Weather fetch failed for {location}: Could not get coordinates.")
            return None

        params = {
            "latitude": lat,
            "longitude": lon,
            "timezone": timezone_str,
            "current": "temperature_2m,relative_humidity_2m,is_day,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 1,
        }
        try:
            response = session.get(API_OPEN_METEO_FORECAST_URL, params=params, timeout=FETCH_WEATHER_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            current, daily = data.get("current", {}), data.get("daily", {})
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
                daily_code = daily["weather_code"][0]
                if daily_code is not None:
                    weather_data["icon_code"] = daily_code
                    print(f"  Using daily weather code ({daily_code}) as current code is unknown.")

            print(f"  Weather fetch successful for {location}.")
            return weather_data

        except requests.exceptions.Timeout:
            print(f"Error: Open-Meteo forecast request for '{location}' timed out.")
        except requests.exceptions.RequestException as e:
            print(f"Error during Open-Meteo forecast request for '{location}': {e}")
        except (KeyError, IndexError, ValueError) as e:
            print(f"Error processing Open-Meteo forecast response for '{location}': {e}")
        except Exception as e:
            print(f"Unexpected error processing Open-Meteo forecast for '{location}': {e}")
            traceback.print_exc()

    print(f"  Weather fetch failed for {location} after encountering errors.")
    return None


def generate_image(current_datetime_local, weather_info, today_events, tomorrow_events):
    """Generates the dashboard display image using helper functions for drawing sections."""
    print(f"Generating image for time: {current_datetime_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    img_display = Image.new("L", (IMAGE_WIDTH, IMAGE_HEIGHT), color=COLOR_WHITE)
    draw = ImageDraw.Draw(img_display)
    fonts = LOADED_FONTS

    # --- Draw Left Pane ---
    time_bottom_y = _draw_time_section(draw, current_datetime_local, fonts, LAYOUT_LEFT_PANE_WIDTH, LAYOUT_PADDING)
    date_start_y = time_bottom_y + LAYOUT_TIME_DATE_SPACING
    _draw_date_section(draw, current_datetime_local, fonts, LAYOUT_LEFT_PANE_WIDTH, date_start_y)
    weather_bottom_y = IMAGE_HEIGHT - LAYOUT_PADDING
    _draw_weather_section(draw, weather_info, fonts, LAYOUT_LEFT_PANE_WIDTH, weather_bottom_y)

    # --- Draw Right Pane ---
    # Vertical dividers
    draw.line([(LAYOUT_LEFT_PANE_WIDTH, 0), (LAYOUT_LEFT_PANE_WIDTH, IMAGE_HEIGHT)], fill=COLOR_BLACK, width=LAYOUT_DIVIDER_LINE_WIDTH)
    col_divider_x = LAYOUT_LEFT_PANE_WIDTH + LAYOUT_COLUMN_WIDTH
    draw.line([(col_divider_x, 0), (col_divider_x, IMAGE_HEIGHT)], fill=COLOR_BLACK, width=LAYOUT_DIVIDER_LINE_WIDTH)

    # Headers ("Today", "Tomorrow") centered in their columns
    header_y = LAYOUT_PADDING
    header_font = fonts["header"]
    head_today_bbox = draw.textbbox((0, 0), "Today", font=header_font)
    header_h = head_today_bbox[3] - head_today_bbox[1]
    today_head_w = head_today_bbox[2] - head_today_bbox[0]
    today_head_x = LAYOUT_LEFT_PANE_WIDTH + (LAYOUT_COLUMN_WIDTH - today_head_w) // 2
    draw.text((today_head_x, header_y), "Today", font=header_font, fill=COLOR_BLACK)
    head_tmrw_bbox = draw.textbbox((0, 0), "Tomorrow", font=header_font)
    tmrw_head_w = head_tmrw_bbox[2] - head_tmrw_bbox[0]
    tmrw_head_x = col_divider_x + (LAYOUT_COLUMN_WIDTH - tmrw_head_w) // 2
    draw.text((tmrw_head_x, header_y), "Tomorrow", font=header_font, fill=COLOR_BLACK)

    # Event Columns
    event_y_start = header_y + header_h + (LAYOUT_EVENT_SPACING_AFTER * 2)
    max_event_y = IMAGE_HEIGHT - LAYOUT_PADDING
    _draw_event_column(draw, today_events, LAYOUT_LEFT_PANE_WIDTH, LAYOUT_COLUMN_WIDTH, event_y_start, fonts, max_event_y, current_datetime_local)
    _draw_event_column(draw, tomorrow_events, col_divider_x, LAYOUT_COLUMN_WIDTH, event_y_start, fonts, max_event_y)

    print("Image generation complete.")
    return img_display


def img_to_bytes(img):
    """Converts a PIL Image object to PNG image bytes in memory."""
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr


def refresh_all_data():
    """Fetches fresh weather and calendar data for ALL configured users."""
    global APP_DATA
    print("Starting data refresh cycle for all users...")
    new_data = {}
    start_time = time.time()

    for user_hash, config in USER_CONFIG.items():
        print(f"  Refreshing data for user: {user_hash}")
        timezone_str = config["timezone"]
        location = config["weather_location"]
        caldav_urls = config["caldav_urls"]
        caldav_filters = config.get("caldav_filters")
        user_tz = config["timezone_obj"]

        weather_info = fetch_weather_data(location, timezone_str)

        now_local = datetime.datetime.now(user_tz)
        start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_fetch_range = start_of_today + datetime.timedelta(days=2)
        today_events, tomorrow_events = fetch_calendar_events(caldav_urls, start_of_today, end_of_fetch_range, user_tz, caldav_filters)

        new_data[user_hash] = {
            "weather": weather_info,
            "today_events": today_events,
            "tomorrow_events": tomorrow_events,
            "last_updated": time.time(),
            "timezone_str": timezone_str,
            "timezone_obj": user_tz,
        }
        print(f"  Finished fetching data for user: {user_hash}")

    with APP_DATA_LOCK:
        APP_DATA = new_data
        print("Global APP_DATA updated with new data.")

    end_time = time.time()
    print(f"Data refresh cycle finished for all users. Duration: {end_time - start_time:.2f} seconds.")


# ==============================================================================
# Flask App Route
# ==============================================================================


@app.route("/display/<user_hash>")
def display_image(user_hash):
    """Flask route to generate and return the display image for a specific user."""
    if user_hash not in USER_CONFIG:
        print(f"Request failed: User hash '{user_hash}' not found in configuration.")
        abort(404, description=f"User '{user_hash}' not found.")

    user_data = None
    with APP_DATA_LOCK:
        user_data = APP_DATA.get(user_hash)

    if not user_data:
        print(f"Request failed: Data not yet available for user '{user_hash}'. Initial refresh might be pending.")
        abort(503, description="Data is being refreshed, please try again shortly.")

    weather_info = user_data.get("weather")
    today_events = user_data.get("today_events", [])
    tomorrow_events = user_data.get("tomorrow_events", [])
    user_tz = user_data.get("timezone_obj")
    last_updated_ts = user_data.get("last_updated", 0)

    if not user_tz:
        print(f"Internal Server Error: Timezone object missing for user '{user_hash}'.")
        abort(500, description="Internal server error: User timezone configuration issue.")

    now_user_tz = datetime.datetime.now(user_tz)

    try:
        img_obj = generate_image(now_user_tz, weather_info, today_events, tomorrow_events)
        img_bytes_io = img_to_bytes(img_obj)
    except Exception as e:
        print(f"Error during image generation for user '{user_hash}': {e}")
        traceback.print_exc()
        abort(500, description="Failed to generate display image due to an internal error.")

    update_time_str = datetime.datetime.fromtimestamp(last_updated_ts).strftime("%Y-%m-%d %H:%M:%S")
    print(f"Successfully generated and sending image for user '{user_hash}'. Data last updated: {update_time_str}")
    return send_file(img_bytes_io, mimetype="image/png", as_attachment=False, download_name=f"display_{user_hash}.png")


# ==============================================================================
# Initial Data Fetch & Background Task Start
# ==============================================================================
if USER_CONFIG:
    print("Performing initial data fetch before starting server...")
    try:
        refresh_all_data()
        print("Initial data fetch complete.")
    except Exception as e:
        print(f"ERROR during initial data fetch: {e}")
        print("Server will start, but data might be unavailable until the first background refresh.")
        traceback.print_exc()

    refresh_thread = threading.Thread(target=background_refresh_loop, daemon=True)
    refresh_thread.start()
    print("Background data refresh thread started.")
else:
    print("Warning: No users configured in environment or .env file.")
    print("Server will run, but '/display/<user_hash>' endpoint will return 404.")
    print("Background refresh thread not started as there is no data to refresh.")


# ==============================================================================
# Main Execution Block (for direct script running / debugging)
# ==============================================================================
if __name__ == "__main__":
    print("-" * 60)
    print("Starting Flask development server (for debugging)...")
    print(f"Access the display at: http://<your-ip>:5050/display/<user_hash>")
    print("Use a WSGI server (e.g., Gunicorn) for production deployments.")
    print("-" * 60)
    app.run(host="0.0.0.0", port=5050, debug=True, use_reloader=True)

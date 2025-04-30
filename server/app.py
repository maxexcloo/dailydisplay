# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "caldav",
#     "flask",
#     "gunicorn",
#     "icalendar",
#     "playwright",
#     "python-dotenv",
#     "requests",
#     "watchdog",
# ]
# ///

import datetime
import json
import os
import threading
import time
import traceback
import urllib.parse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import caldav
import requests
from dotenv import load_dotenv
from flask import Flask, abort, render_template, Response
from icalendar import Calendar
from playwright.sync_api import sync_playwright, Error as PlaywrightError

# ==============================================================================
# Load Environment Variables
# ==============================================================================
load_dotenv()
print("Attempted to load configuration from .env file (if present).")

# ==============================================================================
# Configuration Constants
# ==============================================================================
API_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
API_OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

FETCH_CALDAV_TIMEOUT = 30
FETCH_WEATHER_TIMEOUT = 15
REFRESH_INTERVAL_SECONDS = 60

PNG_VIEWPORT_WIDTH = 960
PNG_VIEWPORT_HEIGHT = 540
PNG_TIMEOUT = 30000

WEATHER_ICON_CLASS_MAP_DAY = {
    0: "wi-day-sunny",
    1: "wi-day-cloudy",
    2: "wi-day-cloudy-gusts",
    3: "wi-cloudy",
    45: "wi-fog",
    48: "wi-fog",
    51: "wi-day-sprinkle",
    53: "wi-day-sprinkle",
    55: "wi-day-showers",
    56: "wi-day-sleet",
    57: "wi-day-sleet",
    61: "wi-day-rain",
    63: "wi-rain",
    65: "wi-rain-wind",
    66: "wi-day-sleet",
    67: "wi-sleet",
    71: "wi-day-snow",
    73: "wi-snow",
    75: "wi-snow-wind",
    77: "wi-snow",
    80: "wi-day-showers",
    81: "wi-showers",
    82: "wi-thunderstorm",
    85: "wi-day-snow",
    86: "wi-snow",
    95: "wi-day-thunderstorm",
    96: "wi-day-hail",
    99: "wi-storm-showers",
    "unknown": "wi-na",
}
WEATHER_ICON_CLASS_MAP_NIGHT = {
    0: "wi-night-clear",
    1: "wi-night-alt-cloudy",
    2: "wi-night-alt-cloudy-gusts",
    3: "wi-night-cloudy",
    45: "wi-fog",
    48: "wi-fog",
    51: "wi-night-alt-sprinkle",
    53: "wi-night-alt-sprinkle",
    55: "wi-night-alt-showers",
    56: "wi-night-alt-sleet",
    57: "wi-night-alt-sleet",
    61: "wi-night-alt-rain",
    66: "wi-night-alt-sleet",
    67: "wi-sleet",
    71: "wi-night-alt-snow",
    73: "wi-snow",
    75: "wi-snow-wind",
    77: "wi-snow",
    80: "wi-night-alt-showers",
    81: "wi-showers",
    82: "wi-thunderstorm",
    85: "wi-night-alt-snow",
    86: "wi-snow",
    95: "wi-night-alt-thunderstorm",
    96: "wi-night-alt-hail",
    99: "wi-storm-showers",
    "unknown": "wi-na",
}

# ==============================================================================
# Global State & App Initialization
# ==============================================================================
app = Flask(__name__)
APP_DATA = {}
APP_DATA_LOCK = threading.Lock()
PNG_CACHE = {}
PNG_CACHE_LOCK = threading.Lock()

# ==============================================================================
# User Configuration Loading
# ==============================================================================
USER_CONFIG = {}
try:
    config_json_str = os.environ.get("CONFIG")
    if not config_json_str:
        print("Warning: CONFIG environment variable not set or empty.")
    else:
        print("Loading configuration from CONFIG environment variable (JSON)...")
        config_data = json.loads(config_json_str)
        if not isinstance(config_data, dict):
            raise ValueError("CONFIG JSON must be a dictionary")

        for user_hash, user_settings in config_data.items():
            user_hash = user_hash.strip()
            if not user_hash or not isinstance(user_settings, dict):
                print(f"  Warning: Skipping invalid entry: {user_hash}")
                continue

            try:
                tz_str = user_settings["timezone"]
                weather_loc = user_settings["weather_location"]
                user_tz = ZoneInfo(tz_str)
                caldav_urls_str = user_settings.get("caldav_urls", "")
                caldav_filter_str = user_settings.get("caldav_filter_names")
                caldav_urls = [url.strip() for url in caldav_urls_str.split(",") if url.strip()]
                caldav_filters = {name.strip().lower() for name in caldav_filter_str.split(",")} if caldav_filter_str else None

                USER_CONFIG[user_hash] = {
                    "caldav_filters": caldav_filters,
                    "caldav_urls": caldav_urls,
                    "timezone": tz_str,
                    "timezone_obj": user_tz,
                    "weather_location": weather_loc,
                }
                print(f"Loaded config for user '{user_hash}'")

            except (KeyError, ValueError, ZoneInfoNotFoundError) as e:
                print(f"  Configuration Error for user '{user_hash}': {e}. Skipping.")
            except Exception as e:
                print(f"  Unexpected error loading configuration for user '{user_hash}': {e}")
                traceback.print_exc()
                print(f"  Skipping user '{user_hash}'.")

except (json.JSONDecodeError, ValueError) as e:
    print(f"Configuration Error: Invalid JSON or structure in CONFIG: {e}")
    raise RuntimeError("Failed to parse JSON configuration") from e
except Exception as e:
    print(f"Fatal error during configuration loading: {e}")
    traceback.print_exc()
    raise RuntimeError("Failed to load user configuration") from e

if not USER_CONFIG:
    print("Warning: No valid user configurations loaded.")

# ==============================================================================
# Helper Function Definitions
# ==============================================================================


def _fetch_lat_lon(location_name, session):
    """Internal helper to fetch latitude/longitude using Open-Meteo Geocoding."""
    params = {"name": location_name, "count": 1, "language": "en", "format": "json"}
    try:
        response = session.get(API_OPEN_METEO_GEOCODE_URL, params=params, timeout=FETCH_WEATHER_TIMEOUT / 2)
        response.raise_for_status()
        data = response.json()
        if data and data.get("results"):
            result = data["results"][0]
            lat, lon = result.get("latitude"), result.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return lat, lon
        print(f"Warning: Geocoding failed or returned invalid data for '{location_name}'.")
    except requests.exceptions.RequestException as e:
        print(f"Error during geocoding request for '{location_name}': {e}")
    except Exception as e:
        print(f"Unexpected error during geocoding for '{location_name}': {e}")
    return None, None


def _process_event_data(ics_data_str, user_tz):
    """Parses ICS data, extracts VEVENT details, localizes time."""
    try:
        cal = Calendar.from_ical(ics_data_str)
        ical_component = next(cal.walk("VEVENT"), None)
        if not ical_component:
            return None, None

        summary_comp = ical_component.get("summary")
        dtstart_comp = ical_component.get("dtstart")
        if not summary_comp or not dtstart_comp:
            return None, None

        summary = str(summary_comp)
        instance_start_time_obj = dtstart_comp.dt

        is_all_day = isinstance(instance_start_time_obj, datetime.date) and not isinstance(instance_start_time_obj, datetime.datetime)
        event_start_local = None
        time_str = "ERR"

        if is_all_day:
            naive_dt = datetime.datetime.combine(instance_start_time_obj, datetime.time.min)
            event_start_local = user_tz.localize(naive_dt) if naive_dt.tzinfo is None else naive_dt.astimezone(user_tz)
            time_str = "All Day"
        elif isinstance(instance_start_time_obj, datetime.datetime):
            event_start_local = instance_start_time_obj.astimezone(user_tz) if instance_start_time_obj.tzinfo else user_tz.localize(instance_start_time_obj)
            time_str = event_start_local.strftime("%H:%M")
        else:
            return None, None

        if event_start_local is None:
            return None, None

        details = {"time": time_str, "title": summary, "sort_key": event_start_local}
        return details, is_all_day

    except Exception as e:
        print(f"        Error parsing single event data: {e}")
        return None, None


def _regenerate_all_pngs(hashes_to_render):
    """Iterates through specified users and regenerates their cached PNGs using Playwright."""
    global PNG_CACHE
    if not hashes_to_render:
        return

    print(f"  Starting PNG cache regeneration for {len(hashes_to_render)} users...")
    start_png_time = time.time()
    generated_count = 0
    failed_count = 0
    browser = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_viewport_size({"width": PNG_VIEWPORT_WIDTH, "height": PNG_VIEWPORT_HEIGHT})

            for user_hash in hashes_to_render:
                user_data_copy = None
                with APP_DATA_LOCK:
                    user_data_copy = APP_DATA.get(user_hash, {}).copy()

                if not user_data_copy or "timezone_obj" not in user_data_copy:
                    print(f"    Skipping PNG render for {user_hash}, data missing.")
                    failed_count += 1
                    continue

                try:
                    user_tz = user_data_copy["timezone_obj"]
                    now_user_tz = datetime.datetime.now(user_tz)
                    last_updated_ts = user_data_copy.get("last_updated", 0)
                    last_updated_dt = datetime.datetime.fromtimestamp(last_updated_ts, tz=datetime.UTC).astimezone(user_tz)
                    template_context = {
                        "user_hash": user_hash,
                        "current_date_str": now_user_tz.strftime("%a, %d %b"),
                        "current_time_str": now_user_tz.strftime("%H:%M"),
                        "last_updated_str": last_updated_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "now_local": now_user_tz,
                        "refresh_interval": REFRESH_INTERVAL_SECONDS,
                        "today_events": user_data_copy.get("today_events", []),
                        "tomorrow_events": user_data_copy.get("tomorrow_events", []),
                        "weather_info": user_data_copy.get("weather", {}),
                    }
                except Exception as context_err:
                    print(f"    Error building template context for {user_hash}: {context_err}")
                    failed_count += 1
                    continue

                png_data = _render_png_for_hash(user_hash, page, template_context)
                if png_data:
                    with PNG_CACHE_LOCK:
                        PNG_CACHE[user_hash] = png_data
                    generated_count += 1
                else:
                    failed_count += 1

            browser.close()
    except (PlaywrightError, Exception) as e:
        print(f"  FATAL Playwright/PNG Error: {e}")
        traceback.print_exc()
        failed_count = len(hashes_to_render)
    finally:
        if browser and browser.is_connected():
            try:
                browser.close()
            except Exception as close_err:
                print(f"    Error closing browser: {close_err}")

    end_png_time = time.time()
    print(f"  PNG regeneration finished. Generated: {generated_count}, Failed: {failed_count}. Duration: {end_png_time - start_png_time:.2f}s.")


def _render_png_for_hash(user_hash, page, template_context):
    """Helper to render PNG for a specific hash using Playwright page.set_content()."""
    try:
        with app.app_context():
            html_string = render_template("index.html", **template_context)
        page.set_content(html_string, wait_until="networkidle", timeout=PNG_TIMEOUT)
        png_bytes = page.screenshot(type="png")
        print(f"    Rendered PNG for {user_hash}")
        return png_bytes
    except (PlaywrightError, Exception) as e:
        print(f"    Error generating PNG for {user_hash}: {e}")
    return None


def background_refresh_loop():
    """Runs the refresh_all_data function periodically in a background thread."""
    print("Background refresh thread started.")
    while True:
        time.sleep(REFRESH_INTERVAL_SECONDS)
        print(f"Background thread: Refreshing data at {datetime.datetime.now(datetime.UTC)}")
        try:
            refresh_all_data()
        except Exception as e:
            print(f"ERROR in background refresh loop: {e}")
            traceback.print_exc()
            time.sleep(15)


# ==============================================================================
# Flask Routes
# ==============================================================================


@app.route("/<user_hash>")
def display_page(user_hash):
    """Flask route to render the display page for a specific user."""
    if user_hash not in USER_CONFIG:
        abort(404, description=f"User '{user_hash}' not found.")

    with APP_DATA_LOCK:
        user_data = APP_DATA.get(user_hash, {}).copy()

    if not user_data or "timezone_obj" not in user_data or "last_updated" not in user_data:
        status = 503 if user_hash in USER_CONFIG else 404
        description = "Data unavailable, please try again shortly." if status == 503 else f"User '{user_hash}' not configured."
        abort(status, description=description)

    try:
        user_tz = user_data["timezone_obj"]
        now_user_tz = datetime.datetime.now(user_tz)
        last_updated_dt = datetime.datetime.fromtimestamp(user_data["last_updated"], tz=datetime.UTC).astimezone(user_tz)

        return render_template(
            "index.html",
            current_date_str=now_user_tz.strftime("%a, %d %b"),
            current_time_str=now_user_tz.strftime("%H:%M"),
            last_updated_str=last_updated_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
            now_local=now_user_tz,
            refresh_interval=REFRESH_INTERVAL_SECONDS,
            today_events=user_data.get("today_events", []),
            tomorrow_events=user_data.get("tomorrow_events", []),
            user_hash=user_hash,
            weather_info=user_data.get("weather", {}),
        )
    except Exception as e:
        print(f"Error during template rendering for user '{user_hash}': {e}")
        traceback.print_exc()
        abort(500, description="Internal error rendering display page.")


@app.route("/<user_hash>.png")
def display_page_png(user_hash):
    """Flask route to serve the proactively cached PNG image."""
    if user_hash not in USER_CONFIG:
        abort(404, description=f"User '{user_hash}' not found.")

    with PNG_CACHE_LOCK:
        png_bytes = PNG_CACHE.get(user_hash)

    if png_bytes:
        return Response(png_bytes, mimetype="image/png")
    else:
        with APP_DATA_LOCK:
            data_exists = user_hash in APP_DATA and APP_DATA[user_hash]
        status = 500 if data_exists else 503
        description = "PNG unavailable (rendering error?)." if status == 500 else "Data/PNG unavailable, please try again shortly."
        abort(status, description=description)


def fetch_calendar_events(caldav_filters, caldav_urls, start_date_local, user_tz):
    """Fetches and processes calendar events from CalDAV URLs for today and tomorrow."""
    all_today, timed_today, all_tomorrow, timed_tomorrow, errors = [], [], [], [], []
    added_all_today_titles, added_timed_today_keys = set(), set()
    added_all_tomorrow_titles, added_timed_tomorrow_keys = set(), set()

    today_start = start_date_local
    today_end = today_start + datetime.timedelta(days=1)
    tomorrow_start = today_end
    tomorrow_end = tomorrow_start + datetime.timedelta(days=1)

    if not caldav_urls:
        return [], []

    for url in caldav_urls:
        username, password, url_display_name = None, None, url
        try:
            parsed_url = urllib.parse.urlparse(url)
            url_display_name = parsed_url.hostname if parsed_url.hostname else url
            username = urllib.parse.unquote(parsed_url.username) if parsed_url.username else None
            password = urllib.parse.unquote(parsed_url.password) if parsed_url.password else None
            url_no_creds = parsed_url._replace(netloc=parsed_url.hostname + (f":{parsed_url.port}" if parsed_url.port else "")).geturl()

            with caldav.DAVClient(url=url_no_creds, username=username, password=password, timeout=FETCH_CALDAV_TIMEOUT) as client:
                principal = client.principal()
                calendars = principal.calendars()
                if not calendars:
                    continue

                for calendar in calendars:
                    try:
                        calendar_name = calendar.name or "Unknown"
                    except Exception:
                        calendar_name = "Unknown(Err)"
                    calendar_name_lower = calendar_name.lower()

                    if caldav_filters and calendar_name_lower not in caldav_filters:
                        continue

                    try:
                        results_today = calendar.date_search(start=today_start, end=today_end, expand=True)
                        for event in results_today:
                            if not hasattr(event, "data") or not event.data:
                                continue
                            ics_data = event.data
                            if isinstance(ics_data, bytes):
                                try:
                                    ics_data = ics_data.decode("utf-8")
                                except UnicodeDecodeError:
                                    ics_data = ics_data.decode("latin-1", errors="replace")

                            details, is_all_day = _process_event_data(ics_data, user_tz)
                            if details and details.get("sort_key") and today_start <= details["sort_key"] < today_end:
                                summary = details["title"]
                                if is_all_day:
                                    if summary not in added_all_today_titles:
                                        all_today.append(details)
                                        added_all_today_titles.add(summary)
                                else:
                                    key = (details["time"], summary)
                                    if key not in added_timed_today_keys:
                                        timed_today.append(details)
                                        added_timed_today_keys.add(key)
                    except Exception as search_ex:
                        print(f"          Error searching '{calendar_name}' TODAY: {search_ex}")
                        errors.append({"time": "ERR", "title": f"SearchFail TODAY: {calendar_name[:15]}", "sort_key": today_start})

                    try:
                        results_tomorrow = calendar.date_search(start=tomorrow_start, end=tomorrow_end, expand=True)
                        for event in results_tomorrow:
                            if not hasattr(event, "data") or not event.data:
                                continue
                            ics_data = event.data
                            if isinstance(ics_data, bytes):
                                try:
                                    ics_data = ics_data.decode("utf-8")
                                except UnicodeDecodeError:
                                    ics_data = ics_data.decode("latin-1", errors="replace")

                            details, is_all_day = _process_event_data(ics_data, user_tz)
                            if details and details.get("sort_key") and tomorrow_start <= details["sort_key"] < tomorrow_end:
                                summary = details["title"]
                                if is_all_day:
                                    if summary not in added_all_tomorrow_titles:
                                        all_tomorrow.append(details)
                                        added_all_tomorrow_titles.add(summary)
                                else:
                                    key = (details["time"], summary)
                                    if key not in added_timed_tomorrow_keys:
                                        timed_tomorrow.append(details)
                                        added_timed_tomorrow_keys.add(key)
                    except Exception as search_ex:
                        print(f"          Error searching '{calendar_name}' TOMORROW: {search_ex}")

        except (caldav.lib.error.AuthorizationError, requests.exceptions.Timeout, requests.exceptions.ConnectionError) as client_ex:
            error_type = type(client_ex).__name__.replace("Error", " Fail").replace("Timeout", "Timeout")
            print(f"      CalDAV {error_type} for {url_display_name}.")
            errors.append({"time": "ERR", "title": f"{error_type}: {url_display_name}", "sort_key": today_start})
        except Exception as client_ex:
            print(f"      Unexpected CalDAV Error for {url_display_name}: {client_ex}")
            traceback.print_exc()
            errors.append({"time": "ERR", "title": f"Load Fail: {url_display_name}", "sort_key": today_start})

    timed_today.sort(key=lambda x: x["sort_key"])
    all_today.sort(key=lambda x: x["title"])
    timed_tomorrow.sort(key=lambda x: x["sort_key"])
    all_tomorrow.sort(key=lambda x: x["title"])

    final_today = errors + all_today + timed_today
    final_tomorrow = all_tomorrow + timed_tomorrow
    return final_today, final_tomorrow


def fetch_weather_data(location, timezone_str):
    """Fetches weather data from Open-Meteo API."""
    weather_data = {"temp": None, "high": None, "low": None, "humidity": None, "icon_code": "unknown", "is_day": 1}
    with requests.Session() as session:
        lat, lon = _fetch_lat_lon(location, session)
        if lat is None or lon is None:
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
            current = data.get("current", {})
            daily = data.get("daily", {})

            weather_data["temp"] = current.get("temperature_2m")
            weather_data["humidity"] = current.get("relative_humidity_2m")
            weather_data["icon_code"] = current.get("weather_code", "unknown")
            weather_data["is_day"] = current.get("is_day", 1)
            weather_data["high"] = daily.get("temperature_2m_max", [None])[0]
            weather_data["low"] = daily.get("temperature_2m_min", [None])[0]

            if weather_data["icon_code"] is None or weather_data["icon_code"] == "unknown":
                daily_codes = daily.get("weather_code", [None])
                weather_data["icon_code"] = daily_codes[0] if daily_codes and daily_codes[0] is not None else "unknown"

            for key in ["temp", "high", "low", "humidity"]:
                value = weather_data[key]
                if value is not None and not isinstance(value, (int, float)):
                    weather_data[key] = None
            if not isinstance(weather_data.get("is_day"), int) or weather_data.get("is_day") not in [0, 1]:
                weather_data["is_day"] = 1

            current_icon_code = weather_data.get("icon_code")
            if current_icon_code != "unknown" and current_icon_code is not None:
                try:
                    weather_data["icon_code"] = int(current_icon_code)
                except (ValueError, TypeError):
                    weather_data["icon_code"] = "unknown"
            elif current_icon_code is None:
                weather_data["icon_code"] = "unknown"

            return weather_data

        except requests.exceptions.RequestException as e:
            print(f"      Error during Open-Meteo request for '{location}': {e}")
        except (KeyError, IndexError, ValueError, TypeError) as e:
            print(f"      Error processing Open-Meteo response for '{location}': {e}")
        except Exception as e:
            print(f"      Unexpected error processing Open-Meteo forecast for '{location}': {e}")
            traceback.print_exc()
    return None


def get_weather_icon_class(is_day, wmo_code):
    """Gets the appropriate Weather Icons CSS class based on WMO code and day/night."""
    lookup_code = wmo_code if isinstance(wmo_code, int) else "unknown"
    if is_day == 0:
        return WEATHER_ICON_CLASS_MAP_NIGHT.get(lookup_code, WEATHER_ICON_CLASS_MAP_DAY.get(lookup_code, WEATHER_ICON_CLASS_MAP_DAY["unknown"]))
    else:
        return WEATHER_ICON_CLASS_MAP_DAY.get(lookup_code, WEATHER_ICON_CLASS_MAP_DAY["unknown"])


def refresh_all_data():
    """Fetches fresh weather and calendar data for ALL configured users and triggers PNG cache regeneration."""
    global APP_DATA
    print("Starting data refresh cycle...")
    new_data = {}
    start_time = time.time()
    hashes_to_render = []

    if not USER_CONFIG:
        return

    for user_hash, config in USER_CONFIG.items():
        print(f"  Refreshing data for user: {user_hash}")
        try:
            user_tz = config["timezone_obj"]
            now_local = datetime.datetime.now(user_tz)
            start_of_today_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

            weather_info = fetch_weather_data(config["weather_location"], config["timezone"])
            today_events, tomorrow_events = fetch_calendar_events(config.get("caldav_filters"), config.get("caldav_urls", []), start_of_today_local, user_tz)

            if weather_info:
                weather_info["icon_class"] = get_weather_icon_class(weather_info.get("is_day", 1), weather_info.get("icon_code"))
            else:
                print(f"    Weather fetch failed for {user_hash}, using defaults.")
                weather_info = {"temp": None, "high": None, "low": None, "humidity": None, "icon_code": "unknown", "is_day": 1, "icon_class": "wi-na"}

            new_data[user_hash] = {
                "last_updated": time.time(),
                "timezone_obj": user_tz,
                "timezone_str": config["timezone"],
                "today_events": today_events,
                "tomorrow_events": tomorrow_events,
                "weather": weather_info,
            }
            hashes_to_render.append(user_hash)

        except Exception as e:
            print(f"  Unexpected error refreshing data for user {user_hash}: {e}")
            traceback.print_exc()

    with APP_DATA_LOCK:
        APP_DATA = new_data
        print("Global APP_DATA updated.")

    if hashes_to_render:
        _regenerate_all_pngs(hashes_to_render)

    end_time = time.time()
    print(f"Data refresh cycle finished. Duration: {end_time - start_time:.2f}s.")


# ==============================================================================
# Initial Data Fetch & Background Task Start
# ==============================================================================
if USER_CONFIG:
    print("Performing initial data fetch...")
    initial_refresh_thread = threading.Thread(target=refresh_all_data, daemon=False)
    initial_refresh_thread.start()
    print("Initial data fetch thread started.")

    refresh_thread = threading.Thread(target=background_refresh_loop, daemon=True)
    refresh_thread.start()
else:
    print("Warning: No users configured. Background refresh thread not started.")

# ==============================================================================
# Main Execution Block
# ==============================================================================
if __name__ == "__main__":
    print("-" * 60)
    print("Starting Flask development server...")
    if USER_CONFIG:
        print("Available user endpoints:")
        for uh in USER_CONFIG.keys():
            print(f"  HTML: http://127.0.0.1:8000/{uh}")
            print(f"  PNG:  http://127.0.0.1:8000/{uh}.png")
    else:
        print("No users configured.")
    print("Use a WSGI server (e.g., Gunicorn) for production.")
    print("-" * 60)
    app.run(debug=True, host="0.0.0.0", port=8000, use_reloader=True)

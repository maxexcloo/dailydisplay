# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "caldav",
#     "flask",
#     "gunicorn",
#     "icalendar",
#     "python-dotenv",
#     "requests",
#     "watchdog",
# ]
# ///

import datetime
import os
import threading
import time
import traceback
import urllib.parse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import caldav
import requests
from dotenv import load_dotenv
from flask import Flask, abort, render_template
from icalendar import Calendar

# ==============================================================================
# Load Environment Variables
# ==============================================================================
load_dotenv()
print("Attempted to load configuration from .env file (if present).")

# ==============================================================================
# Configuration Constants
# ==============================================================================

# --- API URLs ---
API_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
API_OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# --- Data Fetching & Background Task ---
FETCH_CALDAV_TIMEOUT = 30
FETCH_WEATHER_TIMEOUT = 15
REFRESH_INTERVAL_SECONDS = 60

# --- Weather Icon Mapping ---
# Ref: https://erikflowers.github.io/weather-icons/ & https://open-meteo.com/en/docs#weathervariables
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
    51: "wi-night-alt-sprinkle",
    53: "wi-night-alt-sprinkle",
    55: "wi-night-alt-showers",
    56: "wi-night-alt-sleet",
    57: "wi-night-alt-sleet",
    61: "wi-night-alt-rain",
    66: "wi-night-alt-sleet",
    71: "wi-night-alt-snow",
    80: "wi-night-alt-showers",
    85: "wi-night-alt-snow",
    95: "wi-night-alt-thunderstorm",
    96: "wi-night-alt-hail",
    "unknown": "wi-na",
}

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

            caldav_filter_var = f"CALDAV_FILTER_NAMES_{user_hash}"
            caldav_urls_var = f"CALDAV_URLS_{user_hash}"
            tz_var = f"TIMEZONE_{user_hash}"
            weather_loc_var = f"WEATHER_LOCATION_{user_hash}"

            caldav_filter_str = os.environ.get(caldav_filter_var)
            caldav_urls_str = os.environ.get(caldav_urls_var, "")
            tz_str = os.environ.get(tz_var)
            weather_loc = os.environ.get(weather_loc_var)

            if not weather_loc:
                raise ValueError(f"Missing configuration: {weather_loc_var}")
            if not tz_str:
                raise ValueError(f"Missing configuration: {tz_var}")

            try:
                user_tz = ZoneInfo(tz_str)
            except ZoneInfoNotFoundError:
                raise ValueError(f"Invalid timezone '{tz_str}' in {tz_var}")

            caldav_urls = [url.strip() for url in caldav_urls_str.split(",") if url.strip()]
            caldav_filters = {name.strip().lower() for name in caldav_filter_str.split(",")} if caldav_filter_str else None

            USER_CONFIG[user_hash] = {
                "caldav_filters": caldav_filters,
                "caldav_urls": caldav_urls,
                "timezone": tz_str,
                "timezone_obj": user_tz,
                "weather_location": weather_loc,
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

if not USER_CONFIG and USER_HASHES_STR:
    print("Error: USER_HASHES is set, but no valid user configurations could be loaded.")
    raise RuntimeError("Failed to load any valid user configurations.")
elif not USER_CONFIG:
    print("Warning: No users configured.")

# ==============================================================================
# Helper Function Definitions (Sorted Alphabetically)
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


def _process_event_data(ics_data_str, user_tz):
    """
    Parses ICS data, extracts VEVENT details, localizes time.
    Returns (details_dict, is_all_day_flag) or (None, None) on failure.
    """
    try:
        cal = Calendar.from_ical(ics_data_str)
        components = cal.walk("VEVENT")
        ical_component = next(iter(components), None)

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
        time_str = "??:??"

        if is_all_day:
            naive_dt = datetime.datetime.combine(instance_start_time_obj, datetime.time.min)
            event_start_local = user_tz.localize(naive_dt) if naive_dt.tzinfo is None else naive_dt.astimezone(user_tz)
            time_str = "All Day"
        elif isinstance(instance_start_time_obj, datetime.datetime):
            event_start_local = (
                user_tz.localize(instance_start_time_obj) if instance_start_time_obj.tzinfo is None else instance_start_time_obj.astimezone(user_tz)
            )
            time_str = event_start_local.strftime("%H:%M")
        else:
            return None, None

        if event_start_local is None:
            return None, None

        details = {"time": time_str, "title": summary, "sort_key": event_start_local}
        return details, is_all_day

    except Exception as e:
        print(f"        Error parsing/processing single event data: {e}")
        return None, None


def background_refresh_loop():
    """Runs the refresh_all_data function periodically in a background thread."""
    print("Background refresh thread started.")
    while True:
        time.sleep(REFRESH_INTERVAL_SECONDS * 60)
        print(f"Background thread: Woke up, attempting refresh at {datetime.datetime.now(datetime.UTC)}")
        try:
            refresh_all_data()
            print(f"Background thread: Refresh cycle completed.")
        except Exception as e:
            print(f"ERROR in background refresh loop: {e}")
            traceback.print_exc()


@app.route("/<user_hash>")
def display_page(user_hash):
    """Flask route to render the display page for a specific user."""
    if user_hash not in USER_CONFIG:
        print(f"Request failed: User hash '{user_hash}' not found in configuration.")
        abort(404, description=f"User '{user_hash}' not found.")

    user_data = None
    with APP_DATA_LOCK:
        user_data = APP_DATA.get(user_hash, {}).copy()

    if not user_data or "timezone_obj" not in user_data:
        print(f"Request failed: Data not yet available for user '{user_hash}'. Initial refresh might be pending or failed.")
        abort(503, description="Data is being refreshed or is not yet available, please try again shortly.")

    weather_info = user_data.get("weather", {})
    today_events = user_data.get("today_events", [])
    tomorrow_events = user_data.get("tomorrow_events", [])
    user_tz = user_data.get("timezone_obj")
    last_updated_ts = user_data.get("last_updated", 0)

    now_user_tz = datetime.datetime.now(user_tz)
    current_time_str = now_user_tz.strftime("%H:%M")
    current_date_str = now_user_tz.strftime("%a, %d %b")

    last_updated_dt = datetime.datetime.fromtimestamp(last_updated_ts, tz=datetime.UTC).astimezone(user_tz)
    last_updated_str = last_updated_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"Rendering page for user '{user_hash}'. Data last updated: {last_updated_str}")

    try:
        return render_template(
            "index.html",
            current_date_str=current_date_str,
            current_time_str=current_time_str,
            last_updated_str=last_updated_str,
            now_local=now_user_tz,
            refresh_interval=REFRESH_INTERVAL_SECONDS,
            today_events=today_events,
            tomorrow_events=tomorrow_events,
            user_hash=user_hash,
            weather_info=weather_info,
        )
    except Exception as e:
        print(f"Error during template rendering for user '{user_hash}': {e}")
        traceback.print_exc()
        abort(500, description="Failed to render display page due to an internal error.")


def fetch_calendar_events(caldav_filters, caldav_urls, end_date_local, start_date_local, user_tz):
    """
    Fetches and processes calendar events from CalDAV URLs for today and tomorrow
    using separate searches and a helper function for processing.
    """
    all_today, timed_today, all_tomorrow, timed_tomorrow, errors = [], [], [], [], []
    added_all_today_titles, added_timed_today_keys = set(), set()
    added_all_tomorrow_titles, added_timed_tomorrow_keys = set(), set()

    today_start = start_date_local
    today_end = today_start + datetime.timedelta(days=1)
    tomorrow_start = today_end
    tomorrow_end = tomorrow_start + datetime.timedelta(days=1)

    for url in caldav_urls:
        username, password, url_display_name = None, None, url
        try:
            parsed_url = urllib.parse.urlparse(url)
            url_display_name = parsed_url.hostname or url
            username = urllib.parse.unquote(parsed_url.username) if parsed_url.username else None
            password = urllib.parse.unquote(parsed_url.password) if parsed_url.password else None
            url_no_creds = parsed_url._replace(netloc=parsed_url.hostname + (f":{parsed_url.port}" if parsed_url.port else "")).geturl()

            with caldav.DAVClient(url=url_no_creds, username=username, password=password, timeout=FETCH_CALDAV_TIMEOUT) as client:
                principal = client.principal()
                calendars = principal.calendars()
                if not calendars:
                    continue

                for calendar in calendars:
                    calendar_name = getattr(calendar, "name", "UnknownCalendarName")
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

                            if details and details.get("sort_key"):
                                if today_start <= details["sort_key"] < today_end:
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

                    except Exception as search_ex_today:
                        print(f"      Error searching calendar '{calendar_name}' for TODAY: {search_ex_today}")
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

                            if details and details.get("sort_key"):
                                if tomorrow_start <= details["sort_key"] < tomorrow_end:
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

                    except Exception as search_ex_tomorrow:
                        print(f"      Error searching calendar '{calendar_name}' for TOMORROW: {search_ex_tomorrow}")

        except caldav.lib.error.AuthorizationError:
            errors.append({"time": "ERR", "title": f"Auth Fail: {url_display_name}", "sort_key": today_start})
        except requests.exceptions.Timeout:
            errors.append({"time": "ERR", "title": f"Timeout: {url_display_name}", "sort_key": today_start})
        except requests.exceptions.ConnectionError:
            errors.append({"time": "ERR", "title": f"Connect Fail: {url_display_name}", "sort_key": today_start})
        except Exception as client_ex:
            print(f"  Error connecting to or processing calendar source {url_display_name}: {client_ex}")
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
    """Fetches weather data from Open-Meteo API, returning dict or None on failure."""
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
                if daily_codes and daily_codes[0] is not None:
                    weather_data["icon_code"] = daily_codes[0]
                else:
                    weather_data["icon_code"] = "unknown"

            for key in ["temp", "high", "low", "humidity"]:
                if weather_data[key] is not None and not isinstance(weather_data[key], (int, float)):
                    print(f"  Warning: Unexpected type for weather data '{key}': {type(weather_data[key])}. Setting to None.")
                    weather_data[key] = None
            if not isinstance(weather_data.get("is_day"), int):
                weather_data["is_day"] = 1

            current_icon_code = weather_data.get("icon_code")
            if current_icon_code != "unknown":
                try:
                    weather_data["icon_code"] = int(current_icon_code)
                except (ValueError, TypeError):
                    weather_data["icon_code"] = "unknown"

            return weather_data

        except requests.exceptions.Timeout:
            print(f"Error: Open-Meteo forecast request for '{location}' timed out.")
        except requests.exceptions.RequestException as e:
            print(f"Error during Open-Meteo forecast request for '{location}': {e}")
        except (KeyError, IndexError, ValueError, TypeError) as e:
            print(f"Error processing Open-Meteo forecast response for '{location}': {e}")
        except Exception as e:
            print(f"Unexpected error processing Open-Meteo forecast for '{location}': {e}")
            traceback.print_exc()

    return None


def get_weather_icon_class(is_day, wmo_code):
    """Gets the appropriate Weather Icons CSS class based on WMO code and day/night."""
    lookup_code = "unknown"
    if isinstance(wmo_code, int):
        lookup_code = wmo_code
    elif wmo_code != "unknown" and wmo_code is not None:
        try:
            lookup_code = int(wmo_code)
        except (ValueError, TypeError):
            pass

    if is_day == 0:
        return WEATHER_ICON_CLASS_MAP_NIGHT.get(lookup_code, WEATHER_ICON_CLASS_MAP_DAY.get(lookup_code, WEATHER_ICON_CLASS_MAP_DAY["unknown"]))
    else:
        return WEATHER_ICON_CLASS_MAP_DAY.get(lookup_code, WEATHER_ICON_CLASS_MAP_DAY["unknown"])


def refresh_all_data():
    """Fetches fresh weather and calendar data for ALL configured users."""
    global APP_DATA
    print("Starting data refresh cycle for all users...")
    new_data = {}
    start_time = time.time()

    for user_hash, config in USER_CONFIG.items():
        print(f"  Refreshing data for user: {user_hash}")
        caldav_filters = config.get("caldav_filters")
        caldav_urls = config["caldav_urls"]
        location = config["weather_location"]
        timezone_str = config["timezone"]
        user_tz = config["timezone_obj"]

        weather_info = fetch_weather_data(location, timezone_str)

        now_local = datetime.datetime.now(user_tz)
        start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_fetch_range = start_of_today + datetime.timedelta(days=2)

        today_events, tomorrow_events = fetch_calendar_events(caldav_filters, caldav_urls, end_of_fetch_range, start_of_today, user_tz)

        if weather_info:
            weather_info["icon_class"] = get_weather_icon_class(weather_info.get("is_day", 1), weather_info.get("icon_code"))
        else:
            weather_info = {"temp": None, "high": None, "low": None, "humidity": None, "icon_code": "unknown", "is_day": 1, "icon_class": "wi-na"}

        new_data[user_hash] = {
            "last_updated": time.time(),
            "timezone_obj": user_tz,
            "timezone_str": timezone_str,
            "today_events": today_events,
            "tomorrow_events": tomorrow_events,
            "weather": weather_info,
        }
        print(f"  Finished fetching data for user: {user_hash}")

    with APP_DATA_LOCK:
        APP_DATA = new_data
        print("Global APP_DATA updated with new data.")

    end_time = time.time()
    print(f"Data refresh cycle finished for all users. Duration: {end_time - start_time:.2f} seconds.")


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
    print("Server will run, but '/<user_hash>' endpoint will return 404 for any hash.")
    print("Background refresh thread not started as there is no data to refresh.")

# ==============================================================================
# Main Execution Block
# ==============================================================================
if __name__ == "__main__":
    print("-" * 60)
    print("Starting Flask development server (for debugging)...")
    print("Access the display at URLs like: http://<your-ip>:5050/<user_hash>")
    print("Use a WSGI server (e.g., Gunicorn) for production deployments.")
    print("-" * 60)
    app.run(debug=True, host="0.0.0.0", port=5050, use_reloader=True)

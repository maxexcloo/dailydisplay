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
HTML_PAGE_REFRESH_SECONDS = 60
TARGET_REFRESH_MINUTE = 58

PNG_TIMEOUT = 30000
PNG_VIEWPORT_HEIGHT = 540
PNG_VIEWPORT_WIDTH = 960

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
# Helper Function Definitions (Alphabetically Sorted)
# ==============================================================================
def _build_template_context(user_hash, user_data):
    user_tz = user_data["timezone_obj"]
    now_user_tz = datetime.datetime.now(user_tz)
    last_updated_ts = user_data.get("last_updated", 0)
    last_updated_dt = datetime.datetime.fromtimestamp(last_updated_ts, tz=datetime.UTC).astimezone(user_tz)
    today_date_header_str = now_user_tz.strftime("%a, %b %d")
    tomorrow_date_obj = now_user_tz + datetime.timedelta(days=1)
    tomorrow_date_header_str = tomorrow_date_obj.strftime("%a, %b %d")
    return {"user_hash": user_hash, "current_date_str": now_user_tz.strftime("%a, %d %b"), "last_updated_str": last_updated_dt.strftime("%Y-%m-%d %H:%M:%S %Z"), "now_local": now_user_tz, "refresh_interval": HTML_PAGE_REFRESH_SECONDS, "today_events": user_data.get("today_events", []), "tomorrow_events": user_data.get("tomorrow_events", []), "weather_info": user_data.get("weather", {}), "today_date_header_str": today_date_header_str, "tomorrow_date_header_str": tomorrow_date_header_str}


def _fetch_lat_lon(location_name, session):
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
    try:
        cal = Calendar.from_ical(ics_data_str)
        ical_component = next(iter(cal.walk("VEVENT")), None)
        if not ical_component:
            return None, None
        summary_comp = ical_component.get("summary")
        dtstart_comp = ical_component.get("dtstart")
        if not summary_comp or not dtstart_comp:
            return None, None
        summary = str(summary_comp)
        instance_start_time_obj = dtstart_comp.dt
        is_all_day = isinstance(instance_start_time_obj, datetime.date) and not isinstance(instance_start_time_obj, datetime.datetime)
        event_start_local, time_str = None, "ERR"
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
        return {"time": time_str, "title": summary, "sort_key": event_start_local}, is_all_day
    except Exception as e:
        print(f"        Error parsing single event data ({'Iterator Issue' if 'object is not an iterator' in str(e) else 'General'}): {e}")
        return None, None


def _regenerate_all_pngs(hashes_to_render):
    global PNG_CACHE
    if not hashes_to_render:
        return
    print(f"  Starting PNG cache regeneration for {len(hashes_to_render)} users...")
    start_png_time, generated_count, failed_count = time.time(), 0, 0

    playwright_instance_successfully_started = False
    try:
        with sync_playwright() as p:
            playwright_instance_successfully_started = True
            browser = None
            context = None
            page = None
            try:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(device_scale_factor=1)
                page = context.new_page()
                page.set_viewport_size({"width": PNG_VIEWPORT_WIDTH, "height": PNG_VIEWPORT_HEIGHT})

                for user_hash in hashes_to_render:
                    with APP_DATA_LOCK:
                        user_data_copy = APP_DATA.get(user_hash, {}).copy()

                    if not user_data_copy or "timezone_obj" not in user_data_copy:
                        print(f"    Skipping PNG render for {user_hash}, essential data missing.")
                        failed_count += 1
                        continue

                    template_context = None
                    try:
                        template_context = _build_template_context(user_hash, user_data_copy)
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

            except PlaywrightError as e_pw_inner:
                print(f"  Playwright Error during PNG generation process: {e_pw_inner}")
                traceback.print_exc()
                failed_count = len(hashes_to_render) - generated_count
            except Exception as e_other_inner:
                print(f"  Unexpected error during PNG generation process: {e_other_inner}")
                traceback.print_exc()
                failed_count = len(hashes_to_render) - generated_count
            finally:
                if page:
                    try:
                        page.close()
                    except PlaywrightError as pe_page:
                        print(f"    Error closing Playwright page: {pe_page}")
                if context:
                    try:
                        context.close()
                    except PlaywrightError as pe_context:
                        print(f"    Error closing Playwright context: {pe_context}")
                if browser:
                    try:
                        browser.close()
                    except PlaywrightError as pe_browser:
                        print(f"    Error closing Playwright browser: {pe_browser}")

    except PlaywrightError as e_pw_outer:
        print(f"  FATAL: Playwright failed to initialize or suffered a critical error: {e_pw_outer}")
        traceback.print_exc()
        if not playwright_instance_successfully_started:
            failed_count = len(hashes_to_render)
            generated_count = 0
    except Exception as e_other_outer:
        print(f"  FATAL: Unexpected error outside main Playwright block: {e_other_outer}")
        traceback.print_exc()
        if not playwright_instance_successfully_started:
            failed_count = len(hashes_to_render)
            generated_count = 0

    print(f"  PNG regeneration finished. Generated: {generated_count}, Failed: {failed_count}. Duration: {time.time() - start_png_time:.2f}s.")


def _render_png_for_hash(user_hash, page, template_context):
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


# ==============================================================================
# Background Task
# ==============================================================================
def background_refresh_loop():
    print(f"Background refresh thread started. Will aim to refresh data around HH:{TARGET_REFRESH_MINUTE:02d} UTC.")
    time.sleep(10)
    while True:
        now_utc = datetime.datetime.now(datetime.UTC)
        next_refresh_time_utc = now_utc.replace(minute=TARGET_REFRESH_MINUTE, second=0, microsecond=0)
        if now_utc.minute >= TARGET_REFRESH_MINUTE:
            next_refresh_time_utc += datetime.timedelta(hours=1)
        sleep_duration_seconds = (next_refresh_time_utc - now_utc).total_seconds()
        if sleep_duration_seconds < 0:
            sleep_duration_seconds = 5
            print(f"Warning: Calculated sleep duration is negative ({sleep_duration_seconds}s). Fallback to 5s sleep.")
        print(f"Background thread: Current UTC is {now_utc.strftime('%Y-%m-%d %H:%M:%S')}. Next refresh at {next_refresh_time_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC. Sleeping for {sleep_duration_seconds:.2f}s.")
        time.sleep(sleep_duration_seconds)
        print(f"Background thread: Woke up at {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')}. Triggering data refresh.")
        try:
            refresh_all_data()
        except Exception as e:
            print(f"ERROR in background_refresh_loop during refresh_all_data: {e}")
            traceback.print_exc()
            print("An error occurred during data refresh. Waiting for 60 seconds before next attempt.")
            time.sleep(60)


# ==============================================================================
# Flask Routes
# ==============================================================================
@app.route("/")
def default_route():
    return "E-Ink Dashboard Server OK", 200, {"Content-Type": "text/plain"}


@app.route("/<user_hash>")
def display_page(user_hash):
    if user_hash not in USER_CONFIG:
        abort(404, description=f"User '{user_hash}' not found or not configured.")
    with APP_DATA_LOCK:
        user_data = APP_DATA.get(user_hash, {}).copy()
    if not user_data or "timezone_obj" not in user_data or "last_updated" not in user_data:
        print(f"Data not ready for user '{user_hash}'. Current APP_DATA keys: {list(APP_DATA.keys())}")
        abort(503, description="Data for this user is currently unavailable. Please try again shortly.")
    try:
        template_context = _build_template_context(user_hash, user_data)
        return render_template("index.html", **template_context)
    except Exception as e:
        print(f"Error during template rendering for user '{user_hash}': {e}")
        traceback.print_exc()
        abort(500, description="Internal error rendering display page.")


@app.route("/<user_hash>.png")
def display_page_png(user_hash):
    if user_hash not in USER_CONFIG:
        abort(404, description=f"User '{user_hash}' not found or not configured.")
    with PNG_CACHE_LOCK:
        png_bytes = PNG_CACHE.get(user_hash)
    if png_bytes:
        return Response(png_bytes, mimetype="image/png")
    else:
        with APP_DATA_LOCK:
            data_should_exist = user_hash in APP_DATA and APP_DATA[user_hash] is not None
        if data_should_exist:
            print(f"PNG not found in cache for '{user_hash}', but data exists. Possible render issue.")
            abort(500, description="PNG image is currently unavailable (possible rendering error). Please try again shortly.")
        else:
            print(f"PNG not found in cache for '{user_hash}', and underlying data is also missing.")
            abort(503, description="Data and PNG image are currently unavailable. Please try again shortly.")


# ==============================================================================
# Core Data Fetching Logic
# ==============================================================================
def fetch_calendar_events(caldav_filters, caldav_urls, start_date_local, user_tz):
    all_today, timed_today, all_tomorrow, timed_tomorrow, errors = [], [], [], [], []
    added_all_today_titles, added_timed_today_keys = set(), set()
    added_all_tomorrow_titles, added_timed_tomorrow_keys = set(), set()
    today_start, today_end = start_date_local, start_date_local + datetime.timedelta(days=1)
    tomorrow_start, tomorrow_end = today_end, today_end + datetime.timedelta(days=1)
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
                    print(f"      No calendars found for principal at {url_display_name}.")
                    continue
                for calendar_obj in calendars:
                    try:
                        calendar_name = getattr(calendar_obj, "name", "Unknown Calendar") or "Unknown Calendar"
                    except Exception as cal_name_ex:
                        calendar_name = f"Unknown(NameErr: {cal_name_ex})"
                    if caldav_filters and calendar_name.lower() not in caldav_filters:
                        continue
                    for day_period, results_list, all_day_list, timed_list, added_all_day, added_timed in [("TODAY", today_start, all_today, timed_today, added_all_today_titles, added_timed_today_keys), ("TOMORROW", tomorrow_start, all_tomorrow, timed_tomorrow, added_all_tomorrow_titles, added_timed_tomorrow_keys)]:
                        period_end = results_list + datetime.timedelta(days=1)
                        if day_period == "TODAY":
                            period_end = today_end
                        else:
                            period_end = tomorrow_end

                        try:
                            results = calendar_obj.date_search(start=results_list, end=period_end, expand=True)
                            for event in results:
                                if not hasattr(event, "data") or not event.data:
                                    continue
                                ics_data = event.data
                                if isinstance(ics_data, bytes):
                                    try:
                                        ics_data = ics_data.decode("utf-8")
                                    except UnicodeDecodeError:
                                        ics_data = ics_data.decode("latin-1", errors="replace")
                                details, is_all_day_event = _process_event_data(ics_data, user_tz)
                                if details and details.get("sort_key") and results_list <= details["sort_key"] < period_end:
                                    summary = details["title"]
                                    if is_all_day_event:
                                        if summary not in added_all_day:
                                            all_day_list.append(details)
                                            added_all_day.add(summary)
                                    else:
                                        key = (details["time"], summary)
                                        if key not in added_timed:
                                            timed_list.append(details)
                                            added_timed.add(key)
                        except Exception as search_ex:
                            print(f"          Error searching '{calendar_name}' for {day_period}: {search_ex}")
                            if day_period == "TODAY":
                                errors.append({"time": "ERR", "title": f"CalSearchFail {day_period}: {calendar_name[:10]}", "sort_key": today_start})
        except (caldav.lib.error.AuthorizationError, requests.exceptions.Timeout, requests.exceptions.ConnectionError) as client_ex:
            error_type = type(client_ex).__name__.replace("Error", " Fail").replace("Timeout", "Timeout")
            print(f"      CalDAV {error_type} for {url_display_name}.")
            errors.append({"time": "ERR", "title": f"{error_type}: {url_display_name[:20]}", "sort_key": today_start})
        except Exception as client_ex:
            print(f"      Unexpected CalDAV Error for {url_display_name}: {client_ex}")
            traceback.print_exc()
            errors.append({"time": "ERR", "title": f"CalLoad Fail: {url_display_name[:20]}", "sort_key": today_start})
    timed_today.sort(key=lambda x: x["sort_key"])
    all_today.sort(key=lambda x: x["title"])
    timed_tomorrow.sort(key=lambda x: x["sort_key"])
    all_tomorrow.sort(key=lambda x: x["title"])
    return errors + all_today + timed_today, all_tomorrow + timed_tomorrow


def fetch_weather_data(location, timezone_str):
    weather_data = {"temp": None, "high": None, "low": None, "humidity": None, "icon_code": "unknown", "is_day": 1}
    with requests.Session() as session:
        lat, lon = _fetch_lat_lon(location, session)
        if lat is None or lon is None:
            print(f"      Weather fetch failed for '{location}': Could not get coordinates.")
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
            weather_data.update({"temp": current.get("temperature_2m"), "humidity": current.get("relative_humidity_2m"), "icon_code": current.get("weather_code", "unknown"), "is_day": current.get("is_day", 1), "high": daily.get("temperature_2m_max", [None])[0], "low": daily.get("temperature_2m_min", [None])[0]})
            if weather_data["icon_code"] is None or weather_data["icon_code"] == "unknown":
                daily_codes = daily.get("weather_code", [None])
                weather_data["icon_code"] = daily_codes[0] if daily_codes and daily_codes[0] is not None else "unknown"
            for key in ["temp", "high", "low", "humidity"]:
                if weather_data[key] is not None and not isinstance(weather_data[key], (int, float)):
                    print(f"        Warning: Weather data '{key}' for '{location}' not num: {weather_data[key]}. Set to None.")
                    weather_data[key] = None
            if not isinstance(weather_data.get("is_day"), int) or weather_data.get("is_day") not in [0, 1]:
                weather_data["is_day"] = 1
            current_icon_code = weather_data.get("icon_code")
            if current_icon_code not in [None, "unknown"]:
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
    lookup_code = wmo_code if isinstance(wmo_code, int) else "unknown"
    icon_map = WEATHER_ICON_CLASS_MAP_NIGHT if is_day == 0 else WEATHER_ICON_CLASS_MAP_DAY
    return icon_map.get(lookup_code, WEATHER_ICON_CLASS_MAP_DAY.get(lookup_code, WEATHER_ICON_CLASS_MAP_DAY["unknown"]))


def refresh_all_data():
    global APP_DATA
    print("Starting data refresh cycle...")
    new_user_data_map, start_time, hashes_requiring_png_render = {}, time.time(), []
    if not USER_CONFIG:
        print("No users configured. Skipping data refresh.")
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
                print(f"    Weather fetch failed for {user_hash}, using default placeholder.")
                weather_info = {"temp": None, "high": None, "low": None, "humidity": None, "icon_code": "unknown", "is_day": 1, "icon_class": get_weather_icon_class(1, "unknown")}
            new_user_data_map[user_hash] = {
                "last_updated": time.time(),
                "timezone_obj": user_tz,
                "timezone_str": config["timezone"],
                "today_events": today_events,
                "tomorrow_events": tomorrow_events,
                "weather": weather_info,
            }
            hashes_requiring_png_render.append(user_hash)
        except Exception as e:
            print(f"  Unexpected error refreshing data for user {user_hash}: {e}")
            traceback.print_exc()
    with APP_DATA_LOCK:
        APP_DATA = new_user_data_map
        print("Global APP_DATA updated.")
    if hashes_requiring_png_render:
        _regenerate_all_pngs(hashes_requiring_png_render)
    else:
        print("No users had data successfully refreshed or no users to refresh. PNG regeneration skipped.")
    print(f"Data refresh cycle finished. Duration: {time.time() - start_time:.2f}s.")


# ==============================================================================
# Initial Data Fetch & Background Task Start
# ==============================================================================
_app_tasks_initialized = False
_app_initialization_lock = threading.Lock()


def initialize_app_and_background_tasks():
    global _app_tasks_initialized
    with _app_initialization_lock:
        if _app_tasks_initialized:
            return
        print("Performing one-time application initialization...")
        refresh_all_data()
        print("Initial data load complete.")
        if USER_CONFIG:
            print("Starting background refresh loop thread...")
            refresh_thread = threading.Thread(target=background_refresh_loop, daemon=True, name="BackgroundRefreshLoopThread")
            refresh_thread.start()
            print("Background refresh loop thread started.")
        else:
            print("Warning: No users configured. Background refresh thread not started.")
        _app_tasks_initialized = True
        print("One-time application initialization complete.")


# ==============================================================================
# Main Execution Block (for Development & Gunicorn)
# ==============================================================================
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
    initialize_app_and_background_tasks()
elif __name__ == "__main__" and app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    print("Flask Dev Server Reloader (Main Monitor Process): Skipping initialization here.")
    pass


if __name__ == "__main__":
    print("-" * 60)
    print("Starting Flask development server...")
    if USER_CONFIG:
        print("Available user endpoints (approximate for dev server):")
        for user_hash_key in USER_CONFIG.keys():
            print(f"  HTML: http://127.0.0.1:7777/{user_hash_key}")
            print(f"  PNG:  http://127.0.0.1:7777/{user_hash_key}.png")
    else:
        print("No users configured. Server will run but no user-specific data will be available.")
    print("Note: Use a WSGI server (e.g., Gunicorn) for production deployments.")
    print("If using Flask dev server with reloader, initialization happens in the reloaded process.")
    print("-" * 60)
    app.run(debug=True, host="0.0.0.0", port=7777, use_reloader=True)

import logging
from datetime import timedelta
import async_timeout

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

from .const import OPTION_NONE, OPTION_FI, OPTION_EE, EE_FORECAST_URL, FORECAST_POLL_HOURS

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "nordpool_ee_scraper_cache"

class NordpoolCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        self.entry = entry
        self.tomorrow_final = False
        self.current_state = "Waiting"
        self.price_dict = {}
        self.last_poll_time = None
        self.next_poll_time = None
        self.last_date = None
        
        self.api_status_today = "Not Polled"
        self.api_status_tomorrow = "Not Polled"
        self.http_code_today = None
        self.http_code_tomorrow = None
        
        # Interactive settings moved from config flow to state machine
        self.forecast_source = OPTION_NONE
        self.extend_fi_days = 1

        # eupowerprices.com EE price forecast state
        self.api_key = entry.options.get("api_key", entry.data.get("api_key", ""))
        self.ee_forecast = []
        self.last_forecast_poll = None
        self.forecast_status = "Not Polled"
        self.http_code_forecast = None

        self._force_next = False
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._loaded_from_disk = False
        
        super().__init__(
            hass,
            _LOGGER,
            name="Nordpool API Scraper",
            update_interval=timedelta(minutes=1)
        )

    # --- NEW SETTERS FOR THE INTERACTIVE ENTITIES ---
    async def async_set_forecast_source(self, value: str):
        self.forecast_source = value
        await self._async_save_cache()
        await self.async_request_refresh()

    async def async_set_extend_fi_days(self, value: int):
        self.extend_fi_days = value
        await self._async_save_cache()
        await self.async_request_refresh()
    # ------------------------------------------------

    async def async_request_refresh(self):
        self._force_next = True
        await super().async_request_refresh()

    def _build_return_data(self):
        sorted_prices = sorted(self.price_dict.values(), key=lambda x: dt_util.parse_datetime(x["start"]))
        return {
            "prices": sorted_prices,
            "state": self.current_state,
            "api_status_today": self.api_status_today,
            "api_status_tomorrow": self.api_status_tomorrow,
            "http_code_today": self.http_code_today,
            "http_code_tomorrow": self.http_code_tomorrow,
            "last_poll_time": self.last_poll_time,
            "next_poll_time": self.next_poll_time,
            "forecast_source": self.forecast_source,
            "forecast_status": self.forecast_status,
            "http_code_forecast": self.http_code_forecast
        }

    async def _async_save_cache(self):
        await self.store.async_save({
            "price_dict": self.price_dict,
            "current_state": self.current_state,
            "tomorrow_final": self.tomorrow_final,
            "last_date": self.last_date.isoformat() if self.last_date else None,
            "last_poll_time": self.last_poll_time.isoformat() if self.last_poll_time else None,
            "next_poll_time": self.next_poll_time.isoformat() if self.next_poll_time else None,
            "forecast_source": self.forecast_source,
            "extend_fi_days": self.extend_fi_days,
            "ee_forecast": self.ee_forecast,
            "last_forecast_poll": self.last_forecast_poll.isoformat() if self.last_forecast_poll else None
        })

    async def _fetch_ee_forecast(self, force=False):
        """Fetch the eupowerprices.com EE price forecast (throttled hourly)."""
        if self.forecast_source != OPTION_EE or not self.api_key:
            return

        now = dt_util.now()
        if not force and self.last_forecast_poll is not None:
            if (now - self.last_forecast_poll) < timedelta(hours=FORECAST_POLL_HOURS):
                return

        try:
            session = async_get_clientsession(self.hass)
            headers = {"X-API-Key": self.api_key}
            async with async_timeout.timeout(15):
                resp = await session.get(EE_FORECAST_URL, headers=headers)
                self.http_code_forecast = resp.status
                if resp.status == 200:
                    data = await resp.json()
                    parsed = []
                    for item in data.get("series", []):
                        start_dt = dt_util.parse_datetime(item.get("ts_utc"))
                        price = item.get("price_eur_mwh")
                        if start_dt is None or price is None:
                            continue
                        start_local = dt_util.as_local(start_dt)
                        parsed.append({
                            "start": start_local.isoformat(),
                            "value": round(float(price) / 1000.0, 5)
                        })
                    self.ee_forecast = parsed
                    self.forecast_status = f"Success ({len(parsed)} points)"
                    self.last_forecast_poll = now
                    await self._async_save_cache()
                else:
                    self.forecast_status = f"HTTP Error {resp.status}"
        except Exception as e:
            _LOGGER.error("EE forecast fetch failed: %s", e)
            self.forecast_status = f"Exception: {str(e)[:50]}"

    async def _async_update_data(self):
        now = dt_util.now()
        today = now.date()
        today_start = dt_util.start_of_local_day()
        target_1345 = today_start + timedelta(hours=13, minutes=45)
        
        if not self._loaded_from_disk:
            cached_data = await self.store.async_load()
            if cached_data:
                self.price_dict = cached_data.get("price_dict", {})
                self.current_state = cached_data.get("current_state", "Waiting")
                self.tomorrow_final = cached_data.get("tomorrow_final", False)
                self.forecast_source = cached_data.get(
                    "forecast_source",
                    OPTION_FI if cached_data.get("extend_fi") else OPTION_NONE
                )
                self.extend_fi_days = cached_data.get("extend_fi_days", 1)
                self.ee_forecast = cached_data.get("ee_forecast", [])
                last_fc_str = cached_data.get("last_forecast_poll")
                self.last_forecast_poll = dt_util.parse_datetime(last_fc_str) if last_fc_str else None

                last_date_str = cached_data.get("last_date")
                self.last_date = dt_util.parse_date(last_date_str) if last_date_str else None
                
                last_poll_str = cached_data.get("last_poll_time")
                self.last_poll_time = dt_util.parse_datetime(last_poll_str) if last_poll_str else None

                next_poll_str = cached_data.get("next_poll_time")
                self.next_poll_time = dt_util.parse_datetime(next_poll_str) if next_poll_str else None
                
            self._loaded_from_disk = True

        # Refresh the EE price forecast on its own hourly cadence (no-op unless selected).
        await self._fetch_ee_forecast(self._force_next)

        if self.last_date != today:
            self.last_date = today
            self.tomorrow_final = False
            self.current_state = "Waiting"
            self.api_status_today = "Reset"
            self.api_status_tomorrow = "Reset"
            self.http_code_today = None
            self.http_code_tomorrow = None
            
            self.price_dict = {k: v for k, v in self.price_dict.items() if dt_util.parse_datetime(k) >= today_start}
            await self._async_save_cache()

        fast_min = self.entry.options.get("fast_interval", self.entry.data.get("fast_interval", 5))
        slow_hr = self.entry.options.get("slow_interval", self.entry.data.get("slow_interval", 1))

        is_wait_window = now < target_1345
        is_fast_window = (now >= target_1345) and (now < today_start + timedelta(hours=15))
        needs_today_data = len([p for k, p in self.price_dict.items() if dt_util.parse_datetime(k).date() == today]) == 0

        if not self._force_next:
            if self.tomorrow_final:
                self.next_poll_time = target_1345 + timedelta(days=1)
                return self._build_return_data()
                
            if is_wait_window and not needs_today_data:
                self.next_poll_time = target_1345
                return self._build_return_data()

            if self.last_poll_time is not None:
                time_since_last = now - self.last_poll_time
                threshold = timedelta(minutes=fast_min) if is_fast_window else timedelta(hours=slow_hr)
                if time_since_last < threshold:
                    self.next_poll_time = self.last_poll_time + threshold
                    return self._build_return_data()

        was_forced = self._force_next
        self._force_next = False
        self.last_poll_time = now
        
        try:
            session = async_get_clientsession(self.hass)
            
            if needs_today_data or was_forced:
                url_today = f"https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?date={today.strftime('%Y-%m-%d')}&market=DayAhead&deliveryArea=EE&currency=EUR"
                async with async_timeout.timeout(10):
                    resp_today = await session.get(url_today)
                    self.http_code_today = resp_today.status
                    if resp_today.status == 200:
                        json_data = await resp_today.json()
                        if json_data.get("multiAreaEntries"):
                            self.api_status_today = "Success (Prices Loaded)"
                            self._update_dict_from_json(json_data)
                        else:
                            self.api_status_today = "Success (Empty Array)"
                    else:
                        self.api_status_today = f"HTTP Error {resp_today.status}"
                        resp_today.raise_for_status()
            else:
                self.api_status_today = "Skipped (Cached)"

            if not is_wait_window or was_forced:
                tomorrow = today + timedelta(days=1)
                url_tomorrow = f"https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?date={tomorrow.strftime('%Y-%m-%d')}&market=DayAhead&deliveryArea=EE&currency=EUR"
                async with async_timeout.timeout(10):
                    resp_tom = await session.get(url_tomorrow)
                    self.http_code_tomorrow = resp_tom.status
                    if resp_tom.status in (404, 400):
                        self.api_status_tomorrow = f"Not Found (HTTP {resp_tom.status}) - Not Published"
                    elif resp_tom.status == 200:
                        json_data = await resp_tom.json()
                        if json_data.get("multiAreaEntries"):
                            self.api_status_tomorrow = "Success (Prices Loaded)"
                            self._update_dict_from_json(json_data)
                            self._update_state(json_data)
                        else:
                            self.api_status_tomorrow = "Success (Empty Array)"
                    else:
                        self.api_status_tomorrow = f"HTTP Error {resp_tom.status}"
                        resp_tom.raise_for_status()
            else:
                self.api_status_tomorrow = "Skipped (Before 13:45 Window)"
            
            if self.tomorrow_final:
                self.next_poll_time = target_1345 + timedelta(days=1)
            else:
                threshold = timedelta(minutes=fast_min) if is_fast_window else timedelta(hours=slow_hr)
                self.next_poll_time = self.last_poll_time + threshold
                
            await self._async_save_cache()
            return self._build_return_data()
            
        except Exception as e:
            _LOGGER.error("Nordpool scraping failed: %s", e)
            self.api_status_today = f"Exception: {str(e)[:50]}"
            self.api_status_tomorrow = f"Exception: {str(e)[:50]}"
            self.next_poll_time = now + timedelta(minutes=1)
            raise UpdateFailed(f"Failed to fetch data: {e}")

    def _update_state(self, data):
        if not data: return
        areas_states = data.get("areaStates", [])
        state_str = self.current_state
        is_final = False
        for st in areas_states:
            if "EE" in st.get("areas", []):
                state_str = st.get("state", "Preliminary")
                if state_str == "Final": is_final = True
                break
        self.current_state = state_str
        if is_final and len(data.get("multiAreaEntries", [])) > 0: self.tomorrow_final = True

    def _update_dict_from_json(self, data):
        if not data: return
        for entry in data.get("multiAreaEntries", []):
            start_str_z = entry.get("deliveryStart")
            end_str_z = entry.get("deliveryEnd")
            if not start_str_z or not end_str_z: continue
            start_dt = dt_util.parse_datetime(start_str_z)
            end_dt = dt_util.parse_datetime(end_str_z)
            start_local = dt_util.as_local(start_dt)
            end_local = dt_util.as_local(end_dt)
            val = entry.get("entryPerArea", {}).get("EE")
            if val is not None:
                self.price_dict[start_local.isoformat()] = {
                    "start": start_local.isoformat(),
                    "end": end_local.isoformat(),
                    "value": round(float(val) / 1000, 3)
                }

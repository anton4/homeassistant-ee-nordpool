import logging
from datetime import timedelta
import async_timeout

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

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
        
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._loaded_from_disk = False
        
        super().__init__(
            hass,
            _LOGGER,
            name="Nordpool API Scraper",
            update_interval=timedelta(minutes=1)
        )

    async def async_request_refresh(self):
        self.last_poll_time = None
        await super().async_request_refresh()

    def _build_return_data(self):
        sorted_prices = sorted(self.price_dict.values(), key=lambda x: dt_util.parse_datetime(x["start"]))
        return {
            "prices": sorted_prices,
            "state": self.current_state
        }

    async def _async_save_cache(self):
        await self.store.async_save({
            "price_dict": self.price_dict,
            "current_state": self.current_state,
            "tomorrow_final": self.tomorrow_final,
            "last_date": self.last_date.isoformat() if self.last_date else None,
            "last_poll_time": self.last_poll_time.isoformat() if self.last_poll_time else None,
            "next_poll_time": self.next_poll_time.isoformat() if self.next_poll_time else None
        })

    async def _async_update_data(self):
        now = dt_util.now()
        today = now.date()
        today_start = dt_util.start_of_local_day()
        target_1345 = today_start + timedelta(hours=13, minutes=45)
        
        # Load from disk cache on initial startup
        if not self._loaded_from_disk:
            cached_data = await self.store.async_load()
            if cached_data:
                self.price_dict = cached_data.get("price_dict", {})
                self.current_state = cached_data.get("current_state", "Waiting")
                self.tomorrow_final = cached_data.get("tomorrow_final", False)
                
                last_date_str = cached_data.get("last_date")
                self.last_date = dt_util.parse_date(last_date_str) if last_date_str else None
                
                last_poll_str = cached_data.get("last_poll_time")
                self.last_poll_time = dt_util.parse_datetime(last_poll_str) if last_poll_str else None

                next_poll_str = cached_data.get("next_poll_time")
                self.next_poll_time = dt_util.parse_datetime(next_poll_str) if next_poll_str else None
                
                _LOGGER.info("Nordpool cache loaded from disk successfully.")
            self._loaded_from_disk = True
        
        # Midnight Reset
        if self.last_date != today:
            self.last_date = today
            self.tomorrow_final = False
            self.current_state = "Waiting"
            
            self.price_dict = {
                k: v for k, v in self.price_dict.items() 
                if dt_util.parse_datetime(k) >= today_start
            }
            await self._async_save_cache()

        fast_min = self.entry.options.get("fast_interval", self.entry.data.get("fast_interval", 5))
        slow_hr = self.entry.options.get("slow_interval", self.entry.data.get("slow_interval", 1))

        is_wait_window = now < target_1345
        is_fast_window = (now >= target_1345) and (now < today_start + timedelta(hours=15))
        
        needs_today_data = len([p for k, p in self.price_dict.items() if dt_util.parse_datetime(k).date() == today]) == 0

        # Enforce gating rules & calculate next schedule
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

        # Execute live update
        self.last_poll_time = now
        _LOGGER.info("Nordpool Polling Executed Exactly At: %s", now.isoformat())
        
        try:
            session = async_get_clientsession(self.hass)
            made_changes = False
            
            if needs_today_data:
                url_today = f"https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?date={today.strftime('%Y-%m-%d')}&market=DayAhead&deliveryArea=EE&currency=EUR"
                async with async_timeout.timeout(10):
                    resp_today = await session.get(url_today)
                    resp_today.raise_for_status()
                    self._update_dict_from_json(await resp_today.json())
                    made_changes = True

            if not is_wait_window:
                tomorrow = today + timedelta(days=1)
                url_tomorrow = f"https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?date={tomorrow.strftime('%Y-%m-%d')}&market=DayAhead&deliveryArea=EE&currency=EUR"
                
                async with async_timeout.timeout(10):
                    resp_tom = await session.get(url_tomorrow)
                    resp_tom.raise_for_status()
                    data_tom = await resp_tom.json()
                    
                    self._update_dict_from_json(data_tom)
                    self._update_state(data_tom)
                    made_changes = True
            
            # Recalculate next poll time after fresh data
            if self.tomorrow_final:
                self.next_poll_time = target_1345 + timedelta(days=1)
            else:
                threshold = timedelta(minutes=fast_min) if is_fast_window else timedelta(hours=slow_hr)
                self.next_poll_time = self.last_poll_time + threshold
                
            await self._async_save_cache()
            return self._build_return_data()
            
        except Exception as e:
            _LOGGER.error("Nordpool scraping failed: %s", e)
            # If failed, retry on the next 1-minute tick
            self.next_poll_time = now + timedelta(minutes=1)
            raise UpdateFailed(f"Failed to fetch data: {e}")

    def _update_state(self, data):
        areas_states = data.get("areaStates", [])
        state_str = self.current_state
        is_final = False
        
        for st in areas_states:
            if "EE" in st.get("areas", []):
                state_str = st.get("state", "Preliminary")
                if state_str == "Final":
                    is_final = True
                break
        
        self.current_state = state_str
        if is_final and len(data.get("multiAreaEntries", [])) > 0:
            self.tomorrow_final = True

    def _update_dict_from_json(self, data):
        for entry in data.get("multiAreaEntries", []):
            start_str_z = entry.get("deliveryStart")
            end_str_z = entry.get("deliveryEnd")
            
            if not start_str_z or not end_str_z:
                continue
                
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

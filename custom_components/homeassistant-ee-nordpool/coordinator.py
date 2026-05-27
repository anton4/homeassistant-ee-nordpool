import logging
from datetime import timedelta
import async_timeout

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

class NordpoolCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        self.entry = entry
        self.tomorrow_final = False
        self.current_state = "Waiting"
        self.price_dict = {}
        self.last_poll_time = None
        self.last_date = None
        
        super().__init__(
            hass,
            _LOGGER,
            name="Nordpool API Scraper",
            update_interval=timedelta(minutes=1) # Evaluates rules every minute
        )

    async def async_request_refresh(self):
        """Allows the manual button to override the interval thresholds."""
        self.last_poll_time = None
        await super().async_request_refresh()

    def _build_return_data(self):
        """Sorts the dictionary into a sequential list for the attributes."""
        sorted_prices = sorted(self.price_dict.values(), key=lambda x: dt_util.parse_datetime(x["start"]))
        return {
            "prices": sorted_prices,
            "state": self.current_state
        }

    async def _async_update_data(self):
        now = dt_util.now()
        today = now.date()
        
        # 1. Midnight Reset & Purge
        if self.last_date != today:
            self.last_date = today
            self.tomorrow_final = False
            self.current_state = "Waiting"
            
            # Dynamically delete yesterday's prices (keep only Today and Tomorrow)
            today_start = dt_util.start_of_local_day()
            self.price_dict = {
                k: v for k, v in self.price_dict.items() 
                if dt_util.parse_datetime(k) >= today_start
            }

        # 2. Fetch User Configured Intervals
        fast_min = self.entry.options.get("fast_interval", self.entry.data.get("fast_interval", 5))
        slow_hr = self.entry.options.get("slow_interval", self.entry.data.get("slow_interval", 1))

        # 3. Dynamic Windows
        is_wait_window = now.hour < 13 or (now.hour == 13 and now.minute < 45)
        is_fast_window = (now.hour == 13 and now.minute >= 45) or (now.hour == 14)

        # Safety catch: If HA rebooted, we MUST fetch today's data even if it's the wait window.
        needs_today_data = len([p for k, p in self.price_dict.items() if dt_util.parse_datetime(k).date() == today]) == 0

        # 4. Enforce "Stop Polling" Rules
        if self.tomorrow_final:
            # We already have tomorrow's final prices. Stop polling entirely.
            return self._build_return_data()
            
        if is_wait_window and not needs_today_data:
            # It's before 13:45, and we already have today's data. Strictly wait.
            return self._build_return_data()

        # 5. Enforce Intervals
        if self.last_poll_time is not None:
            time_since_last = now - self.last_poll_time
            threshold = timedelta(minutes=fast_min) if is_fast_window else timedelta(hours=slow_hr)
            
            if time_since_last < threshold:
                return self._build_return_data() # Return cached data until threshold met

        # --- EXECUTE POLLING ---
        self.last_poll_time = now
        _LOGGER.info("Nordpool Polling Executed Exactly At: %s", now.isoformat())
        
        try:
            session = self.hass.helpers.aiohttp_client.async_get_clientsession(self.hass)
            
            # Fetch Today (Safety net to populate cache if empty)
            if needs_today_data:
                url_today = f"https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?date={today.strftime('%Y-%m-%d')}&market=DayAhead&deliveryArea=EE&currency=EUR"
                async with async_timeout.timeout(10):
                    resp_today = await session.get(url_today)
                    _LOGGER.info("Nordpool Response Today: %s", await resp_today.text())
                    resp_today.raise_for_status()
                    self._update_dict_from_json(await resp_today.json())

            # Fetch Tomorrow (Only if we are past 13:45)
            if not is_wait_window:
                tomorrow = today + timedelta(days=1)
                url_tomorrow = f"https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?date={tomorrow.strftime('%Y-%m-%d')}&market=DayAhead&deliveryArea=EE&currency=EUR"
                
                async with async_timeout.timeout(10):
                    resp_tom = await session.get(url_tomorrow)
                    _LOGGER.info("Nordpool Response Tomorrow: %s", await resp_tom.text())
                    resp_tom.raise_for_status()
                    data_tom = await resp_tom.json()
                    
                    self._update_dict_from_json(data_tom)
                    self._update_state(data_tom)
                
            return self._build_return_data()
            
        except Exception as e:
            _LOGGER.error("Nordpool scraping failed: %s", e)
            raise UpdateFailed(f"Failed to fetch data: {e}")

    def _update_state(self, data):
        """Extracts the 'Final' state from areaStates."""
        areas_states = data.get("areaStates", [])
        state_str = self.current_state # Default to existing state
        is_final = False
        
        for st in areas_states:
            if "EE" in st.get("areas", []):
                state_str = st.get("state", "Preliminary")
                if state_str == "Final":
                    is_final = True
                break
        
        self.current_state = state_str
        
        # Only lock out polling if we actually received prices alongside the Final state
        if is_final and len(data.get("multiAreaEntries", [])) > 0:
            self.tomorrow_final = True

    def _update_dict_from_json(self, data):
        """Parses the exact JSON structure provided."""
        for entry in data.get("multiAreaEntries", []):
            start_str_z = entry.get("deliveryStart")
            end_str_z = entry.get("deliveryEnd")
            
            if not start_str_z or not end_str_z:
                continue
                
            start_dt = dt_util.parse_datetime(start_str_z)
            end_dt = dt_util.parse_datetime(end_str_z)
            
            # Convert UTC 'Z' times to HA's local timezone
            start_local = dt_util.as_local(start_dt)
            end_local = dt_util.as_local(end_dt)
            
            val = entry.get("entryPerArea", {}).get("EE")
            
            if val is not None:
                self.price_dict[start_local.isoformat()] = {
                    "start": start_local.isoformat(),
                    "end": end_local.isoformat(),
                    "value": round(float(val) / 1000, 3) # Convert EUR/MWh to EUR/kWh
                }

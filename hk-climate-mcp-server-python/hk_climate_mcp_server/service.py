"""
HK Climate Service - Python implementation of the Hong Kong climate and weather API client
"""

import asyncio
import aiohttp
from typing import List, Dict, Optional, Union
from dataclasses import dataclass
import json


@dataclass
class WeatherError(Exception):
    code: str
    message: str
    details: Optional[Dict] = None


class HKClimateService:
    def __init__(self):
        self.base_url = "https://data.weather.gov.hk/weatherAPI/opendata"
        self.request_timeout = 10  # 10 seconds

    async def _fetch_with_timeout(self, url: str, headers: Optional[Dict] = None) -> dict:
        """Async helper to fetch data with timeout."""
        try:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if headers is None:
                    headers = {
                        "Accept": "application/json",
                        "User-Agent": "hk-climate-mcp-server/0.1.0"
                    }

                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        # Check if the response is text/html instead of JSON
                        content_type = response.headers.get('content-type', '')
                        if 'text/html' in content_type or response.status in [404, 400, 500]:
                            text_content = await response.text()
                            raise WeatherError(
                                code="HTTP_ERROR",
                                message=f"HTTP {response.status}: {text_content[:200]}...",
                                details={"url": url, "status_code": response.status, "content": text_content[:500]}
                            )
                        else:
                            raise WeatherError(
                                code="HTTP_ERROR",
                                message=f"HTTP {response.status}: {response.reason}",
                                details={"url": url, "status_code": response.status}
                            )

                    # Try to parse JSON response
                    try:
                        data = await response.json()
                        return data
                    except Exception as json_error:
                        # If JSON parsing fails, return the raw text in an error
                        text_content = await response.text()
                        raise WeatherError(
                            code="JSON_PARSE_ERROR",
                            message=f"Could not parse JSON response: {text_content[:200]}...",
                            details={"url": url, "raw_content": text_content[:500], "error": str(json_error)}
                        )
        except asyncio.TimeoutError:
            raise WeatherError(
                code="TIMEOUT",
                message="Request timed out",
                details={"url": url, "timeout": self.request_timeout}
            )
        except Exception as e:
            raise WeatherError(
                code="FETCH_ERROR",
                message=str(e),
                details={"url": url, "error": str(e)}
            )

    async def get_current_weather(self, lang: str = "en") -> dict:
        """
        Fetch current weather observations from HKO.
        
        Args:
            lang: Language code ('en', 'tc', 'sc') for the response
            
        Returns:
            Dictionary containing current weather data
        """
        url = f"{self.base_url}/weather.php?dataType=rhrread&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_forecast_9day(self, lang: str = "en") -> dict:
        """
        Fetch 9-day weather forecast from HKO.
        
        Args:
            lang: Language code ('en', 'tc', 'sc') for the response
            
        Returns:
            Dictionary containing 9-day forecast data
        """
        url = f"{self.base_url}/weather.php?dataType=fnd&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_forecast_7day(self, lang: str = "en") -> dict:
        """
        Fetch 7-day weather forecast from HKO.
        
        Args:
            lang: Language code ('en', 'tc', 'sc') for the response
            
        Returns:
            Dictionary containing 7-day forecast data
        """
        url = f"{self.base_url}/weather.php?dataType=flw&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_warning_summary(self, lang: str = "en") -> dict:
        """
        Fetch current weather warnings from HKO.
        
        Args:
            lang: Language code ('en', 'tc', 'sc') for the response
            
        Returns:
            Dictionary containing warning information
        """
        url = f"{self.base_url}/weather.php?dataType=warnsum&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_rainfall_map(self, lang: str = "en") -> dict:
        """
        Fetch rainfall distribution map data from HKO.
        
        Args:
            lang: Language code ('en', 'tc', 'sc') for the response
            
        Returns:
            Dictionary containing rainfall map data
        """
        url = f"{self.base_url}/weather.php?dataType=hrlyr&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_uv_index(self, lang: str = "en") -> dict:
        """
        Fetch UV index information from HKO.
        
        Args:
            lang: Language code ('en', 'tc', 'sc') for the response
            
        Returns:
            Dictionary containing UV index data
        """
        url = f"{self.base_url}/weather.php?dataType=uvindex&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_solar_radiation(self, lang: str = "en") -> dict:
        """
        Fetch solar radiation data from HKO.
        
        Args:
            lang: Language code ('en', 'tc', 'sc') for the response
            
        Returns:
            Dictionary containing solar radiation data
        """
        url = f"{self.base_url}/weather.php?dataType=radar&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_tide_data(self, lang: str = "en") -> dict:
        """
        Fetch tide prediction data from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response (default: 'en')

        Returns:
            Dictionary containing tide data
        """
        # Try with lang parameter first
        url = f"{self.base_url}/weather.php?dataType=tide&lang={lang}"
        try:
            return await self._fetch_with_timeout(url)
        except Exception as e:
            # If that fails, try without lang parameter
            url = f"{self.base_url}/weather.php?dataType=tide"
            return await self._fetch_with_timeout(url)

    async def get_astronomical_data(self, lang: str = "en") -> dict:
        """
        Fetch astronomical information (sunrise/sunset) from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response

        Returns:
            Dictionary containing astronomical data
        """
        # Try with the standard URL first
        url = f"{self.base_url}/weather.php?dataType=astro&lang={lang}"
        try:
            return await self._fetch_with_timeout(url)
        except Exception as e:
            # If that fails, try without lang parameter
            url = f"{self.base_url}/weather.php?dataType=astro"
            return await self._fetch_with_timeout(url)

    async def get_lightning_data(self, lang: str = "en") -> dict:
        """
        Fetch lightning flash data from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response (default: 'en')

        Returns:
            Dictionary containing lightning data
        """
        # The lightning endpoint may not exist in the current API
        # Using the working pattern similar to other endpoints
        url = f"{self.base_url}/weather.php?dataType=lightning&lang={lang}"
        try:
            return await self._fetch_with_timeout(url)
        except Exception as e:
            # If the standard endpoint doesn't work, try without lang parameter
            url = f"{self.base_url}/weather.php?dataType=lightning"
            return await self._fetch_with_timeout(url)

    async def get_stations_data(self, lang: str = "en") -> dict:
        """
        Fetch weather station information from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response

        Returns:
            Dictionary containing station data
        """
        url = f"{self.base_url}/weather.php?dataType=swt&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_warning_info(self, lang: str = "en") -> dict:
        """
        Fetch detailed weather warning information from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response

        Returns:
            Dictionary containing detailed warning information
        """
        url = f"{self.base_url}/weather.php?dataType=warningInfo&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_special_weather_tips(self, lang: str = "en") -> dict:
        """
        Fetch special weather tips from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response

        Returns:
            Dictionary containing special weather tips
        """
        # The swt endpoint in TypeScript is specifically for special weather tips (not stations)
        url = f"{self.base_url}/weather.php?dataType=swt&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_earthquake_messages(self, lang: str = "en") -> dict:
        """
        Fetch quick earthquake messages from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response

        Returns:
            Dictionary containing earthquake information
        """
        # Note: This uses earthquake.php instead of weather.php
        base_url_eq = "https://data.weather.gov.hk/weatherAPI/opendata"
        url = f"{base_url_eq}/earthquake.php?dataType=qem&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_felt_earthquake_reports(self, lang: str = "en") -> dict:
        """
        Fetch locally felt earth tremor reports from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response

        Returns:
            Dictionary containing felt earthquake reports
        """
        # Note: This uses earthquake.php instead of weather.php
        base_url_eq = "https://data.weather.gov.hk/weatherAPI/opendata"
        url = f"{base_url_eq}/earthquake.php?dataType=feltearthquake&lang={lang}"
        return await self._fetch_with_timeout(url)

    async def get_hourly_rainfall(self, lang: str = "en") -> dict:
        """
        Fetch hourly rainfall data from HKO.

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response

        Returns:
            Dictionary containing hourly rainfall data
        """
        # Try with the standard URL first
        url = f"{self.base_url}/weather.php?dataType=hourlyRainfall&lang={lang}"
        try:
            return await self._fetch_with_timeout(url)
        except Exception as e:
            # If that fails, try without lang parameter
            url = f"{self.base_url}/weather.php?dataType=hourlyRainfall"
            return await self._fetch_with_timeout(url)
import asyncio
import aiohttp
from typing import List, Dict, Optional, Union, Tuple
import math
from dataclasses import dataclass, field
from enum import Enum


class FlightCategory(Enum):
    VFR = "VFR"
    MVFR = "MVFR"
    IFR = "IFR"
    LIFR = "LIFR"


class AirmetHazardType(Enum):
    IFR = "IFR"
    MOUNTAIN_OBSCURATION = "MOUNTAIN_OBSCURATION"
    TURBULENCE = "TURBULENCE"
    ICING = "ICING"
    STRONG_SURFACE_WINDS = "STRONG_SURFACE_WINDS"
    LOW_LEVEL_WIND_SHEAR = "LOW_LEVEL_WIND_SHEAR"


@dataclass
class CloudLayer:
    type: str  # 'FEW', 'SCT', 'BKN', 'OVC', 'CLR', 'SKC'
    altitude: Optional[int] = None


@dataclass
class MetarData:
    raw: str
    station: str
    observation_time: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    temperature: Optional[float] = None
    dewpoint: Optional[float] = None
    wind_direction: Optional[int] = None
    wind_speed: Optional[int] = None
    wind_gust: Optional[int] = None
    visibility: Optional[float] = None
    altimeter: Optional[float] = None
    clouds: List[CloudLayer] = field(default_factory=list)
    weather: List[str] = field(default_factory=list)
    remarks: Optional[str] = None
    flight_category: Optional[FlightCategory] = None


@dataclass
class TafForecast:
    from_time: str
    to_time: str
    change_type: Optional[str] = None  # 'FM', 'TEMPO', 'BECMG', 'PROB'
    probability: Optional[int] = None
    wind_direction: Optional[int] = None
    wind_speed: Optional[int] = None
    wind_gust: Optional[int] = None
    visibility: Optional[float] = None
    weather: List[str] = field(default_factory=list)
    clouds: List[CloudLayer] = field(default_factory=list)


@dataclass
class TafData:
    raw: str
    station: str
    issue_time: str
    valid_from: str
    valid_to: str
    forecasts: List[TafForecast] = field(default_factory=list)


@dataclass
class TurbulenceReport:
    intensity: str  # 'LIGHT', 'MODERATE', 'SEVERE', 'EXTREME'
    type: Optional[str] = None  # 'CAT', 'CHOP', 'MECH'


@dataclass
class IcingReport:
    intensity: str  # 'TRACE', 'LIGHT', 'MODERATE', 'SEVERE'
    type: Optional[str] = None  # 'RIME', 'CLEAR', 'MIXED'


@dataclass
class PirepData:
    raw: str
    observation_time: str
    report_type: str  # 'ROUTINE', 'URGENT'
    aircraft: Optional[str] = None
    location: str = ""
    altitude: Optional[int] = None
    turbulence: Optional[TurbulenceReport] = None
    icing: Optional[IcingReport] = None
    weather: List[str] = field(default_factory=list)
    remarks: Optional[str] = None


@dataclass
class AirmetData:
    raw: str
    hazard_type: AirmetHazardType
    valid_from: str
    valid_to: str
    area: str = ""
    description: str = ""


@dataclass
class StationInfo:
    icao: str
    iata: Optional[str] = None
    name: str = ""
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    elevation: Optional[int] = None
    timezone: Optional[str] = None


@dataclass
class WeatherError(Exception):
    code: str
    message: str
    details: Optional[Dict] = None


class AviationWeatherService:
    def __init__(self):
        self.base_url = "https://aviationweather.gov/api/data"
        self.request_timeout = 10  # 10 seconds
    
    async def _fetch_with_timeout(self, url: str) -> dict:
        """Async helper to fetch data with timeout."""
        try:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "aviation-weather-mcp-python/0.1.0"
                    }
                ) as response:
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
    
    async def get_metar(
        self, 
        stations: Union[str, List[str]], 
        hours_back: int = 2
    ) -> List[MetarData]:
        """Fetch METAR data for one or more stations."""
        if isinstance(stations, str):
            station_list = [s.strip().upper() for s in stations.split(',')]
        else:
            station_list = [s.strip().upper() for s in stations]
        
        # Build URL
        import urllib.parse
        station_str = ','.join(station_list)
        params = {
            'ids': station_str,
            'format': 'json',
            'hours': str(hours_back)
        }
        param_str = urllib.parse.urlencode(params)
        url = f"{self.base_url}/metar?{param_str}"
        
        data = await self._fetch_with_timeout(url)
        
        if not isinstance(data, list):
            raise WeatherError(
                code="INVALID_RESPONSE",
                message="Expected array of METAR data",
                details={"data": data}
            )
        
        return [self._parse_metar_response(item) for item in data]
    
    async def get_taf(
        self, 
        stations: Union[str, List[str]]
    ) -> List[TafData]:
        """Fetch TAF data for one or more stations."""
        if isinstance(stations, str):
            station_list = [s.strip().upper() for s in stations.split(',')]
        else:
            station_list = [s.strip().upper() for s in stations]
        
        # Build URL
        import urllib.parse
        station_str = ','.join(station_list)
        params = {
            'ids': station_str,
            'format': 'json'
        }
        param_str = urllib.parse.urlencode(params)
        url = f"{self.base_url}/taf?{param_str}"
        
        data = await self._fetch_with_timeout(url)
        
        if not isinstance(data, list):
            raise WeatherError(
                code="INVALID_RESPONSE",
                message="Expected array of TAF data",
                details={"data": data}
            )
        
        return [self._parse_taf_response(item) for item in data]
    
    async def get_pireps(
        self, 
        min_lat: Optional[float] = None,
        max_lat: Optional[float] = None,
        min_lon: Optional[float] = None,
        max_lon: Optional[float] = None,
        hours_back: int = 3
    ) -> List[PirepData]:
        """Fetch PIREPs within a geographic area."""
        import urllib.parse
        
        params = {
            'format': 'json',
            'hours': str(hours_back)
        }
        
        if all(v is not None for v in [min_lat, max_lat, min_lon, max_lon]):
            params.update({
                'minLat': str(min_lat),
                'maxLat': str(max_lat),
                'minLon': str(min_lon),
                'maxLon': str(max_lon)
            })
        
        param_str = urllib.parse.urlencode(params)
        url = f"{self.base_url}/pirep?{param_str}"
        
        data = await self._fetch_with_timeout(url)
        
        if not isinstance(data, list):
            raise WeatherError(
                code="INVALID_RESPONSE",
                message="Expected array of PIREP data",
                details={"data": data}
            )
        
        return [self._parse_pirep_response(item) for item in data]
    
    async def get_airmets(
        self, 
        region: Optional[str] = None
    ) -> List[AirmetData]:
        """Fetch AIRMETs for a specific region."""
        import urllib.parse
        
        params = {'format': 'json'}
        if region:
            params['region'] = region
        
        param_str = urllib.parse.urlencode(params)
        url = f"{self.base_url}/gairmet?{param_str}"
        
        data = await self._fetch_with_timeout(url)
        
        if not isinstance(data, list):
            raise WeatherError(
                code="INVALID_RESPONSE",
                message="Expected array of AIRMET data",
                details={"data": data}
            )
        
        return [self._parse_airmet_response(item) for item in data]
    
    async def get_metar_by_bounds(
        self, 
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        hours_back: int = 2
    ) -> List[MetarData]:
        """Fetch METAR data by geographic bounds."""
        import urllib.parse
        
        # Use bbox parameter format: minLat,minLon,maxLat,maxLon
        bbox = f"{int(math.floor(min_lat))},{int(math.floor(min_lon))},{int(math.ceil(max_lat))},{int(math.ceil(max_lon))}"
        
        params = {
            'bbox': bbox,
            'format': 'json',  # Start with JSON format
            'hours': str(hours_back)
        }
        
        param_str = urllib.parse.urlencode(params)
        url = f"{self.base_url}/metar?{param_str}"
        
        # For bbox queries, we may get raw text or JSON
        try:
            # Try to fetch as JSON first
            data = await self._fetch_with_timeout(url)
            
            if isinstance(data, list):
                # If we get a list, parse it as JSON METAR objects
                return [self._parse_metar_response(item) for item in data]
            elif isinstance(data, str):
                # If we get a string, parse it as raw METAR text
                lines = [line.strip() for line in data.split('\n') if line.strip()]
                results = []
                
                for line in lines:
                    if line:
                        # Extract station ID from the raw METAR
                        parts = line.split()
                        if parts:
                            # Look for 4-letter station code (typically first part)
                            station_match = [part for part in parts if len(part) == 4 and part.isalpha()]
                            if station_match:
                                results.append(MetarData(
                                    raw=line,
                                    station=station_match[0],
                                    observation_time="",
                                    clouds=[],
                                    weather=[]
                                ))
                
                return results
            else:
                return []
        except Exception:
            # If JSON fails, try text format
            try:
                timeout = aiohttp.ClientTimeout(total=self.request_timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        url,
                        headers={
                            "Accept": "text/plain, application/json",
                            "User-Agent": "aviation-weather-mcp-python/0.1.0"
                        }
                    ) as response:
                        if response.status != 200:
                            raise WeatherError(
                                code="HTTP_ERROR",
                                message=f"HTTP {response.status}: {response.reason}",
                                details={"url": url, "status_code": response.status}
                            )
                        
                        text = await response.text()
                        lines = [line.strip() for line in text.split('\n') if line.strip()]
                        results = []
                        
                        for line in lines:
                            if line:
                                parts = line.split()
                                if parts:
                                    station_match = [part for part in parts if len(part) == 4 and part.isalpha()]
                                    if station_match:
                                        results.append(MetarData(
                                            raw=line,
                                            station=station_match[0],
                                            observation_time="",
                                            clouds=[],
                                            weather=[]
                                        ))
                        
                        return results
            except Exception as e:
                raise WeatherError(
                    code="FETCH_ERROR",
                    message=str(e),
                    details={"url": url, "error": str(e)}
                )
    
    async def get_taf_by_bounds(
        self, 
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float
    ) -> List[TafData]:
        """Fetch TAF data by geographic bounds."""
        import urllib.parse
        
        # Use bbox parameter format: minLon,minLat,maxLon,maxLat
        bbox = f"{int(math.floor(min_lon))},{int(math.floor(min_lat))},{int(math.ceil(max_lon))},{int(math.ceil(max_lat))}"
        
        params = {
            'bbox': bbox,
            'format': 'json'
        }
        
        param_str = urllib.parse.urlencode(params)
        url = f"{self.base_url}/taf?{param_str}"
        
        try:
            data = await self._fetch_with_timeout(url)
            
            if isinstance(data, list):
                return [self._parse_taf_response(item) for item in data]
            elif isinstance(data, str):
                lines = [line.strip() for line in data.split('\n') if line.strip()]
                results = []
                
                current_taf = []
                for line in lines:
                    if line.strip():
                        # TAFs start with "TAF" or station code followed by time group
                        import re
                        starts_new_taf = re.search(r'^(TAF\s+)?[A-Z]{4}\s+\d{6}Z', line, re.IGNORECASE)
                        
                        if starts_new_taf:
                            # Process previous TAF if exists
                            if current_taf:
                                taf_text = ' '.join(current_taf)
                                # Extract station from TAF text
                                station_match = re.search(r'^(TAF\s+)?([A-Z]{4})', taf_text, re.IGNORECASE)
                                if station_match:
                                    results.append(TafData(
                                        raw=taf_text,
                                        station=station_match.group(2),
                                        issue_time="",
                                        valid_from="",
                                        valid_to="",
                                        forecasts=[]
                                    ))
                            
                            # Start new TAF
                            current_taf = [line.strip()]
                        else:
                            if current_taf:
                                current_taf.append(line.strip())
                
                # Process last TAF
                if current_taf:
                    taf_text = ' '.join(current_taf)
                    station_match = re.search(r'^(TAF\s+)?([A-Z]{4})', taf_text, re.IGNORECASE)
                    if station_match:
                        results.append(TafData(
                            raw=taf_text,
                            station=station_match.group(2),
                            issue_time="",
                            valid_from="",
                            valid_to="",
                            forecasts=[]
                        ))
                
                return results
            else:
                return []
        except Exception:
            # If JSON fails, fall back to text processing
            try:
                timeout = aiohttp.ClientTimeout(total=self.request_timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        url,
                        headers={
                            "Accept": "text/plain, application/json",
                            "User-Agent": "aviation-weather-mcp-python/0.1.0"
                        }
                    ) as response:
                        if response.status != 200:
                            raise WeatherError(
                                code="HTTP_ERROR",
                                message=f"HTTP {response.status}: {response.reason}",
                                details={"url": url, "status_code": response.status}
                            )
                        
                        text = await response.text()
                        lines = [line.strip() for line in text.split('\n') if line.strip()]
                        results = []
                        
                        current_taf = []
                        for line in lines:
                            if line.strip():
                                import re
                                starts_new_taf = re.search(r'^(TAF\s+)?[A-Z]{4}\s+\d{6}Z', line, re.IGNORECASE)
                                
                                if starts_new_taf:
                                    if current_taf:
                                        taf_text = ' '.join(current_taf)
                                        station_match = re.search(r'^(TAF\s+)?([A-Z]{4})', taf_text, re.IGNORECASE)
                                        if station_match:
                                            results.append(TafData(
                                                raw=taf_text,
                                                station=station_match.group(2),
                                                issue_time="",
                                                valid_from="",
                                                valid_to="",
                                                forecasts=[]
                                            ))
                                    
                                    current_taf = [line.strip()]
                                else:
                                    if current_taf:
                                        current_taf.append(line.strip())
                        
                        if current_taf:
                            taf_text = ' '.join(current_taf)
                            station_match = re.search(r'^(TAF\s+)?([A-Z]{4})', taf_text, re.IGNORECASE)
                            if station_match:
                                results.append(TafData(
                                    raw=taf_text,
                                    station=station_match.group(2),
                                    issue_time="",
                                    valid_from="",
                                    valid_to="",
                                    forecasts=[]
                                ))
                        
                        return results
            except Exception as e:
                raise WeatherError(
                    code="FETCH_ERROR",
                    message=str(e),
                    details={"url": url, "error": str(e)}
                )
    
    async def get_station_info(self, station: str) -> StationInfo:
        """Fetch station information."""
        clean_station = station.strip().upper()
        
        import urllib.parse
        params = {
            'ids': clean_station,
            'format': 'json',
            'hours': '1'
        }
        param_str = urllib.parse.urlencode(params)
        url = f"{self.base_url}/metar?{param_str}"
        
        data = await self._fetch_with_timeout(url)
        
        if not isinstance(data, list) or not data:
            raise WeatherError(
                code="STATION_NOT_FOUND",
                message=f"Station {clean_station} not found",
                details={"station": clean_station}
            )
        
        # Extract station info from METAR data
        station_data = data[0]
        return StationInfo(
            icao=station_data.get('icaoId', clean_station),
            name=station_data.get('name', clean_station),
            latitude=float(station_data.get('lat')) if station_data.get('lat') else None,
            longitude=float(station_data.get('lon')) if station_data.get('lon') else None,
            elevation=self._safe_int_convert(station_data.get('elev')),
        )
    
    def _parse_metar_response(self, data: dict) -> MetarData:
        """Parse METAR API response into MetarData object."""
        # Handle wind direction - 'VRB' means variable
        wind_dir = data.get('wdir')
        if wind_dir and str(wind_dir).upper() == 'VRB':
            wind_direction = 0  # Use 0 to indicate variable
        elif wind_dir and str(wind_dir).isdigit():
            wind_direction = int(wind_dir)
        else:
            wind_direction = None
            
        metar = MetarData(
            raw=data.get('rawOb', '') or data.get('raw_text', ''),
            station=data.get('icaoId', '') or data.get('station', ''),
            observation_time=data.get('obsTime', '') or data.get('observation_time', ''),
            temperature=float(data.get('temp')) if data.get('temp') else None,
            dewpoint=float(data.get('dewp')) if data.get('dewp') else None,
            wind_direction=wind_direction,
            wind_speed=self._safe_int_convert(data.get('wspd')),
            wind_gust=self._safe_int_convert(data.get('wgst')),
            visibility=self._parse_visibility(data.get('visib')),
            altimeter=float(data.get('altim')) if data.get('altim') else None,
            clouds=self._parse_clouds(data.get('clouds', []) or data.get('skyCondition', [])),
            weather=[data['wxString']] if data.get('wxString') else [],
            flight_category=self._determine_flight_category(data)
        )
        return metar

    def _parse_taf_response(self, data: dict) -> TafData:
        """Parse TAF API response into TafData object."""
        taf = TafData(
            raw=data.get('rawTaf', '') or data.get('raw_text', ''),
            station=data.get('icaoId', '') or data.get('station', ''),
            issue_time=data.get('issueTime', ''),
            valid_from=data.get('validTimeFrom', ''),
            valid_to=data.get('validTimeTo', ''),
            forecasts=[]
        )

        forecasts_data = data.get('forecast') or data.get('fcsts', [])
        for fc in forecasts_data:
            # Handle wind direction - 'VRB' means variable
            wind_dir = fc.get('wdir')
            if wind_dir and str(wind_dir).upper() == 'VRB':
                wind_direction = 0  # Use 0 to indicate variable
            elif wind_dir and str(wind_dir).isdigit():
                wind_direction = int(wind_dir)
            else:
                wind_direction = None

            forecast = TafForecast(
                from_time=fc.get('timeFrom', '') or fc.get('fcstTimeFrom', ''),
                to_time=fc.get('timeTo', '') or fc.get('fcstTimeTo', ''),
                change_type=fc.get('changeIndicator'),
                wind_direction=wind_direction,
                wind_speed=self._safe_int_convert(fc.get('wspd')),
                wind_gust=self._safe_int_convert(fc.get('wgst')),
                visibility=self._parse_visibility(fc.get('visib')),
                weather=[fc['wxString']] if fc.get('wxString') else [],
                clouds=self._parse_clouds(fc.get('clouds', []) or fc.get('skyCondition', []))
            )
            taf.forecasts.append(forecast)

        return taf

    def _parse_pirep_response(self, data: dict) -> PirepData:
        """Parse PIREP API response into PirepData object."""
        pirep = PirepData(
            raw=data.get('rawOb', '') or data.get('raw_text', ''),
            observation_time=data.get('obsTime', '') or data.get('observation_time', ''),
            report_type='URGENT' if data.get('urgency') == 'URGENT' else 'ROUTINE',
            aircraft=data.get('acType'),
            location=data.get('location', ''),
            altitude=self._safe_int_convert(data.get('altitude')),
            remarks=data.get('remarks')
        )

        # Parse turbulence if present
        if data.get('turbulence'):
            pirep.turbulence = TurbulenceReport(
                intensity=self._parse_turbulence_intensity(data['turbulence'])
            )

        # Parse icing if present
        if data.get('icing'):
            pirep.icing = IcingReport(
                intensity=self._parse_icing_intensity(data['icing'])
            )

        return pirep

    def _parse_airmet_response(self, data: dict) -> AirmetData:
        """Parse AIRMET API response into AirmetData object."""
        return AirmetData(
            raw=data.get('rawAirmet', '') or data.get('raw_text', ''),
            hazard_type=self._parse_hazard_type(data.get('hazard', '') or data.get('hazardType', '')),
            valid_from=data.get('validTimeFrom', ''),
            valid_to=data.get('validTimeTo', ''),
            area=data.get('region', ''),
            description=data.get('text', '')
        )

    def _parse_visibility(self, value: Optional[Union[str, float, int]]) -> Optional[float]:
        """Parse visibility value handling special cases."""
        if not value:
            return None

        if isinstance(value, str):
            # Handle "10+" format
            if value.endswith('+'):
                return float(value.replace('+', ''))
            # Handle "P6SM" format
            if value.startswith('P') and value.endswith('SM'):
                return float(value.replace('P', '').replace('SM', ''))

        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _parse_clouds(self, clouds: List[dict]) -> List[CloudLayer]:
        """Parse cloud layers from API response."""
        if not isinstance(clouds, list):
            return []

        result = []
        for cloud in clouds:
            altitude = None
            try:
                if cloud.get('base'):
                    altitude = int(cloud['base'])
            except (ValueError, TypeError):
                pass

            layer = CloudLayer(
                type=cloud.get('cover', '') or cloud.get('skyCover', 'CLR'),
                altitude=altitude
            )
            result.append(layer)

        return result

    def _determine_flight_category(self, data: dict) -> Optional[FlightCategory]:
        """Determine flight category based on ceiling and visibility."""
        visibility = self._parse_visibility(data.get('visib'))
        clouds = self._parse_clouds(data.get('clouds', []) or [])

        # Find lowest ceiling (BKN or OVC)
        ceiling = None
        for cloud in clouds:
            if cloud.type in ['BKN', 'OVC'] and cloud.altitude:
                if ceiling is None or cloud.altitude < ceiling:
                    ceiling = cloud.altitude

        # LIFR: Ceiling < 500ft OR Visibility < 1SM
        if (ceiling and ceiling < 500) or (visibility and visibility < 1):
            return FlightCategory.LIFR

        # IFR: Ceiling < 1000ft OR Visibility < 3SM
        if (ceiling and ceiling < 1000) or (visibility and visibility < 3):
            return FlightCategory.IFR

        # MVFR: Ceiling < 3000ft OR Visibility < 5SM
        if (ceiling and ceiling < 3000) or (visibility and visibility < 5):
            return FlightCategory.MVFR

        # VFR: Everything else
        return FlightCategory.VFR

    def _parse_turbulence_intensity(self, value: str) -> str:
        """Parse turbulence intensity."""
        upper = value.upper()
        if 'EXTREME' in upper:
            return 'EXTREME'
        if 'SEVERE' in upper:
            return 'SEVERE'
        if 'MODERATE' in upper:
            return 'MODERATE'
        return 'LIGHT'

    def _parse_icing_intensity(self, value: str) -> str:
        """Parse icing intensity."""
        upper = value.upper()
        if 'SEVERE' in upper:
            return 'SEVERE'
        if 'MODERATE' in upper:
            return 'MODERATE'
        if 'TRACE' in upper:
            return 'TRACE'
        return 'LIGHT'

    def _safe_int_convert(self, value):
        """Safely convert a value to int, returning None if conversion fails."""
        if value is None:
            return None
        try:
            # Check if it's a string representation of a number
            if isinstance(value, str) and value.isdigit():
                return int(value)
            # Check if it's already an int
            elif isinstance(value, int):
                return value
            # Try to convert to int directly
            else:
                return int(value)
        except (ValueError, TypeError):
            return None

    def _parse_hazard_type(self, value: str) -> AirmetHazardType:
        """Parse AIRMET hazard type."""
        upper = value.upper()
        if 'IFR' in upper:
            return AirmetHazardType.IFR
        if 'MOUNTAIN' in upper or 'MTN' in upper:
            return AirmetHazardType.MOUNTAIN_OBSCURATION
        if 'TURB' in upper:
            return AirmetHazardType.TURBULENCE
        if 'ICE' in upper or 'ICING' in upper:
            return AirmetHazardType.ICING
        if 'WIND' in upper and 'SHEAR' in upper:
            return AirmetHazardType.LOW_LEVEL_WIND_SHEAR
        if 'WIND' in upper:
            return AirmetHazardType.STRONG_SURFACE_WINDS
        return AirmetHazardType.IFR  # Default
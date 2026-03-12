"""
Flight route and analysis tools for aviation weather data
"""

from fastmcp import FastMCP
from typing import Optional
from ..service import AviationWeatherService


# Global weather service instance for tools
weather_service = AviationWeatherService()


def register(mcp: FastMCP):
    """Register all flight route tools with the FastMCP server."""
    
    # Register weather along route tool
    _register_get_weather_along_route(mcp)
    
    # Register weather by radius tool
    _register_get_weather_by_radius(mcp)


def _register_get_weather_along_route(mcp: FastMCP):
    """Register the get-weather-along-route tool."""

    @mcp.tool(
        description="Get weather conditions along a flight route",
    )
    async def get_weather_along_route(
        departure: str,
        destination: str,
        alternates: Optional[str] = None
    ) -> str:
        """
        Get weather conditions along a flight route.
        
        Args:
            departure: Departure airport ICAO code
            destination: Destination airport ICAO code
            alternates: Alternate airports (comma-separated ICAO codes) (optional)
        
        Returns:
            JSON string of route weather data
        """
        try:
            # Collect all airports
            airports = [departure, destination]
            if alternates:
                airports.extend([a.strip() for a in alternates.split(',')])
            
            # Fetch METAR and TAF for all airports
            metar_data = await weather_service.get_metar(airports)
            taf_data = await weather_service.get_taf(airports)
            
            # Organize by airport (ensure uppercase for comparison)
            dep_upper = departure.upper()
            dest_upper = destination.upper()
            
            route_weather = {
                "departure": {
                    "metar": None,
                    "taf": None
                },
                "destination": {
                    "metar": None,
                    "taf": None
                },
                "alternates": []
            }
            
            # Find departure weather
            for metar in metar_data:
                if metar.station == dep_upper:
                    route_weather["departure"]["metar"] = {
                        "raw": metar.raw,
                        "station": metar.station,
                        "observation_time": metar.observation_time,
                        "temperature": metar.temperature,
                        "dewpoint": metar.dewpoint,
                        "wind_direction": metar.wind_direction,
                        "wind_speed": metar.wind_speed,
                        "visibility": metar.visibility,
                        "flight_category": metar.flight_category.value if metar.flight_category else None
                    }
                    break
            
            for taf in taf_data:
                if taf.station == dep_upper:
                    route_weather["departure"]["taf"] = {
                        "raw": taf.raw,
                        "station": taf.station,
                        "issue_time": taf.issue_time,
                        "valid_from": taf.valid_from,
                        "valid_to": taf.valid_to
                    }
                    break
            
            # Find destination weather
            for metar in metar_data:
                if metar.station == dest_upper:
                    route_weather["destination"]["metar"] = {
                        "raw": metar.raw,
                        "station": metar.station,
                        "observation_time": metar.observation_time,
                        "temperature": metar.temperature,
                        "dewpoint": metar.dewpoint,
                        "wind_direction": metar.wind_direction,
                        "wind_speed": metar.wind_speed,
                        "visibility": metar.visibility,
                        "flight_category": metar.flight_category.value if metar.flight_category else None
                    }
                    break
            
            for taf in taf_data:
                if taf.station == dest_upper:
                    route_weather["destination"]["taf"] = {
                        "raw": taf.raw,
                        "station": taf.station,
                        "issue_time": taf.issue_time,
                        "valid_from": taf.valid_from,
                        "valid_to": taf.valid_to
                    }
                    break
            
            # Find alternate weather
            if alternates:
                alt_codes = [a.strip().upper() for a in alternates.split(',')]
                for alt_code in alt_codes:
                    alt_weather = {
                        "station": alt_code,
                        "metar": None,
                        "taf": None
                    }
                    
                    for metar in metar_data:
                        if metar.station == alt_code:
                            alt_weather["metar"] = {
                                "raw": metar.raw,
                                "station": metar.station,
                                "observation_time": metar.observation_time,
                                "temperature": metar.temperature,
                                "dewpoint": metar.dewpoint,
                                "wind_direction": metar.wind_direction,
                                "wind_speed": metar.wind_speed,
                                "visibility": metar.visibility,
                                "flight_category": metar.flight_category.value if metar.flight_category else None
                            }
                            break
                    
                    for taf in taf_data:
                        if taf.station == alt_code:
                            alt_weather["taf"] = {
                                "raw": taf.raw,
                                "station": taf.station,
                                "issue_time": taf.issue_time,
                                "valid_from": taf.valid_from,
                                "valid_to": taf.valid_to
                            }
                            break
                    
                    route_weather["alternates"].append(alt_weather)
            
            import json
            return json.dumps(route_weather, indent=2)
        
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": {}})


def _register_get_weather_by_radius(mcp: FastMCP):
    """Register the get-weather-by-radius tool."""

    @mcp.tool(
        description="Get weather conditions within a radius of an airport",
    )
    async def get_weather_by_radius(
        center_airport: str,
        radius_nm: float,
        include_metar: bool = True,
        include_taf: bool = False,
        include_pireps: bool = False
    ) -> str:
        """
        Get weather conditions within a radius of an airport.
        
        Args:
            center_airport: ICAO code of the center airport
            radius_nm: Radius in nautical miles (5-200)
            include_metar: Include METAR observations (default: true)
            include_taf: Include TAF forecasts (default: false)
            include_pireps: Include pilot reports (default: false)
        
        Returns:
            JSON string of weather data within radius
        """
        try:
            # First get the center airport's coordinates
            station_info = await weather_service.get_station_info(center_airport)
            
            if not station_info.latitude or not station_info.longitude:
                raise Exception(f"Unable to find coordinates for airport {center_airport}")
            
            # Calculate bounding box from radius
            # 1 degree of latitude = ~60 nautical miles
            # 1 degree of longitude varies by latitude
            lat_deg_per_nm = 1 / 60
            lon_deg_per_nm = 1 / (60 * abs(__import__('math').cos(station_info.latitude * __import__('math').pi / 180)))
            
            lat_offset = radius_nm * lat_deg_per_nm
            lon_offset = radius_nm * lon_deg_per_nm
            
            bounds = {
                "min_lat": station_info.latitude - lat_offset,
                "max_lat": station_info.latitude + lat_offset,
                "min_lon": station_info.longitude - lon_offset,
                "max_lon": station_info.longitude + lon_offset,
            }
            
            results = {
                "center": {
                    "airport": center_airport,
                    "coordinates": {
                        "latitude": station_info.latitude,
                        "longitude": station_info.longitude,
                    },
                    "radius_nm": radius_nm,
                },
                "bounds": bounds,
                "weather": {},
            }
            
            # Fetch requested weather types
            import asyncio
            
            tasks = []
            
            if include_metar:
                tasks.append(weather_service.get_metar_by_bounds(
                    bounds["min_lat"], bounds["max_lat"], 
                    bounds["min_lon"], bounds["max_lon"]
                ))
            else:
                tasks.append(None)
            
            if include_taf:
                tasks.append(weather_service.get_taf_by_bounds(
                    bounds["min_lat"], bounds["max_lat"], 
                    bounds["min_lon"], bounds["max_lon"]
                ))
            else:
                tasks.append(None)
            
            if include_pireps:
                tasks.append(weather_service.get_pireps(
                    bounds["min_lat"], bounds["max_lat"], 
                    bounds["min_lon"], bounds["max_lon"]
                ))
            else:
                tasks.append(None)
            
            # Execute tasks concurrently
            metar_data, taf_data, pirep_data = None, None, None

            task_list = []
            if tasks[0] is not None:
                task_list.append(tasks[0])
            if tasks[1] is not None:
                task_list.append(tasks[1])
            if tasks[2] is not None:
                task_list.append(tasks[2])

            if task_list:
                gathered_results = await asyncio.gather(*task_list, return_exceptions=True)
                idx = 0
                if tasks[0] is not None:
                    if not isinstance(gathered_results[idx], Exception):
                        metar_data = gathered_results[idx]
                    idx += 1
                if tasks[1] is not None:
                    if not isinstance(gathered_results[idx], Exception):
                        taf_data = gathered_results[idx]
                    idx += 1
                if tasks[2] is not None:
                    if not isinstance(gathered_results[idx], Exception):
                        pirep_data = gathered_results[idx]
        
            if include_metar and metar_data:
                results["weather"]["metar"] = []
                for metar in metar_data:
                    results["weather"]["metar"].append({
                        "raw": metar.raw,
                        "station": metar.station,
                        "observation_time": metar.observation_time,
                        "temperature": metar.temperature,
                        "visibility": metar.visibility,
                        "flight_category": metar.flight_category.value if metar.flight_category else None
                    })
            
            if include_taf and taf_data:
                results["weather"]["taf"] = []
                for taf in taf_data:
                    results["weather"]["taf"].append({
                        "raw": taf.raw,
                        "station": taf.station,
                        "issue_time": taf.issue_time,
                        "valid_from": taf.valid_from,
                        "valid_to": taf.valid_to
                    })
            
            if include_pireps and pirep_data:
                results["weather"]["pireps"] = []
                for pirep in pirep_data:
                    pirep_dict = {
                        "raw": pirep.raw,
                        "observation_time": pirep.observation_time,
                        "report_type": pirep.report_type,
                        "location": pirep.location,
                        "altitude": pirep.altitude,
                        "weather": pirep.weather
                    }
                    results["weather"]["pireps"].append(pirep_dict)
            
            import json
            return json.dumps(results, indent=2)
        
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": {}})
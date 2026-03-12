"""
Weather-related MCP tools for aviation weather data
"""

from fastmcp import FastMCP
from typing import List, Optional, Union
from ..service import AviationWeatherService, MetarData, TafData, PirepData, AirmetData

# Global weather service instance for tools
weather_service = AviationWeatherService()


def register(mcp: FastMCP):
    """Register all weather tools with the FastMCP server."""
    
    # Register METAR tool
    _register_get_metar(mcp)
    
    # Register TAF tool
    _register_get_taf(mcp)
    
    # Register PIREP tool
    _register_get_pireps(mcp)
    
    # Register AIRMET tool
    _register_get_airmets(mcp)


def _register_get_metar(mcp: FastMCP):
    """Register the get-metar tool."""

    @mcp.tool(
        description="Fetch current METAR weather observations for one or more airports",
    )
    async def get_metar(
        stations: str,
        hours_back: int = 2
    ) -> str:
        """
        Fetch current METAR weather observations for one or more airports.

        Args:
            stations: ICAO airport code(s). Can be a single code or comma-separated list
            hours_back: Number of hours of historical data to retrieve (default: 2). Must be between 1-24.

        Returns:
            JSON string of METAR data
        """
        try:
            metar_data = await weather_service.get_metar(stations, hours_back)
            
            # Convert to dictionary format for JSON serialization
            result = []
            for metar in metar_data:
                result.append({
                    "raw": metar.raw,
                    "station": metar.station,
                    "observation_time": metar.observation_time,
                    "latitude": metar.latitude,
                    "longitude": metar.longitude,
                    "temperature": metar.temperature,
                    "dewpoint": metar.dewpoint,
                    "wind_direction": metar.wind_direction,
                    "wind_speed": metar.wind_speed,
                    "wind_gust": metar.wind_gust,
                    "visibility": metar.visibility,
                    "altimeter": metar.altimeter,
                    "clouds": [{"type": c.type, "altitude": c.altitude} for c in metar.clouds],
                    "weather": metar.weather,
                    "remarks": metar.remarks,
                    "flight_category": metar.flight_category.value if metar.flight_category else None
                })
            
            import json
            return json.dumps(result, indent=2)
        
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": []})


def _register_get_taf(mcp: FastMCP):
    """Register the get-taf tool."""

    @mcp.tool(
        description="Fetch TAF (Terminal Aerodrome Forecast) for one or more airports",
    )
    async def get_taf(stations: str) -> str:
        """
        Fetch TAF (Terminal Aerodrome Forecast) for one or more airports.
        
        Args:
            stations: ICAO airport code(s). Can be a single code or comma-separated list
        
        Returns:
            JSON string of TAF data
        """
        try:
            taf_data = await weather_service.get_taf(stations)
            
            # Convert to dictionary format for JSON serialization
            result = []
            for taf in taf_data:
                result.append({
                    "raw": taf.raw,
                    "station": taf.station,
                    "issue_time": taf.issue_time,
                    "valid_from": taf.valid_from,
                    "valid_to": taf.valid_to,
                    "forecasts": [{
                        "from_time": f.from_time,
                        "to_time": f.to_time,
                        "change_type": f.change_type,
                        "probability": f.probability,
                        "wind_direction": f.wind_direction,
                        "wind_speed": f.wind_speed,
                        "wind_gust": f.wind_gust,
                        "visibility": f.visibility,
                        "weather": f.weather,
                        "clouds": [{"type": c.type, "altitude": c.altitude} for c in f.clouds]
                    } for f in taf.forecasts]
                })
            
            import json
            return json.dumps(result, indent=2)
        
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": []})


def _register_get_pireps(mcp: FastMCP):
    """Register the get-pireps tool."""

    @mcp.tool(
        description="Fetch pilot reports (PIREPs) for a geographic area",
    )
    async def get_pireps(
        min_lat: Optional[float] = None,
        max_lat: Optional[float] = None,
        min_lon: Optional[float] = None,
        max_lon: Optional[float] = None,
        hours_back: Optional[int] = 3
    ) -> str:
        """
        Fetch pilot reports (PIREPs) for a geographic area.
        
        Args:
            min_lat: Minimum latitude for search area
            max_lat: Maximum latitude for search area
            min_lon: Minimum longitude for search area
            max_lon: Maximum longitude for search area
            hours_back: Number of hours of historical data (default: 3)
        
        Returns:
            JSON string of PIREP data
        """
        try:
            pirep_data = await weather_service.get_pireps(
                min_lat, max_lat, min_lon, max_lon, hours_back
            )
            
            # Convert to dictionary format for JSON serialization
            result = []
            for pirep in pirep_data:
                pirep_dict = {
                    "raw": pirep.raw,
                    "observation_time": pirep.observation_time,
                    "report_type": pirep.report_type,
                    "aircraft": pirep.aircraft,
                    "location": pirep.location,
                    "altitude": pirep.altitude,
                    "weather": pirep.weather,
                    "remarks": pirep.remarks
                }
                
                if pirep.turbulence:
                    pirep_dict["turbulence"] = {
                        "intensity": pirep.turbulence.intensity,
                        "type": pirep.turbulence.type
                    }
                
                if pirep.icing:
                    pirep_dict["icing"] = {
                        "intensity": pirep.icing.intensity,
                        "type": pirep.icing.type
                    }
                
                result.append(pirep_dict)
            
            import json
            return json.dumps(result, indent=2)
        
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": []})


def _register_get_airmets(mcp: FastMCP):
    """Register the get-airmets tool."""

    @mcp.tool(
        description="Fetch current AIRMETs (Airmen's Meteorological Information)",
    )
    async def get_airmets(region: Optional[str] = None) -> str:
        """
        Fetch current AIRMETs (Airmen's Meteorological Information).
        
        Args:
            region: Region filter (optional)
        
        Returns:
            JSON string of AIRMET data
        """
        try:
            airmet_data = await weather_service.get_airmets(region)
            
            # Convert to dictionary format for JSON serialization
            result = []
            for airmet in airmet_data:
                result.append({
                    "raw": airmet.raw,
                    "hazard_type": airmet.hazard_type.value,
                    "valid_from": airmet.valid_from,
                    "valid_to": airmet.valid_to,
                    "area": airmet.area,
                    "description": airmet.description
                })
            
            import json
            return json.dumps(result, indent=2)
        
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": []})
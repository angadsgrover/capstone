"""
Analysis tools for aviation weather data
"""

from fastmcp import FastMCP
from typing import Optional
import re
from ..service import AviationWeatherService, FlightCategory

weather_service = AviationWeatherService()

def register(mcp: FastMCP):
    """Register all analysis tools with the FastMCP server."""
    _register_determine_flight_category(mcp)
    _register_check_vfr_minimums(mcp)
    _register_decode_metar(mcp)

def _register_determine_flight_category(mcp: FastMCP):
    @mcp.tool(
        description="Determine the flight category (VFR/MVFR/IFR/LIFR) for given weather conditions",
    )
    async def determine_flight_category(
        station: Optional[str] = None,
        ceiling: Optional[float] = None,
        visibility: Optional[float] = None
    ) -> str:
        try:
            category = None
            if station:
                metar_data = await weather_service.get_metar(station, hours_back=1)
                if not metar_data:
                    raise Exception(f"No METAR data available for {station}")
                if metar_data[0].flight_category:
                    category = metar_data[0].flight_category.value
                else:
                    ceiling = _find_ceiling(metar_data[0])
                    visibility = metar_data[0].visibility
                    category = _determine_flight_category_from_values(ceiling, visibility)
            elif ceiling is not None or visibility is not None:
                category = _determine_flight_category_from_values(ceiling, visibility)
            else:
                raise Exception('Either station or ceiling/visibility must be provided')
            explanation = _get_flight_category_explanation(category)
            minimums = _get_flight_category_minimums(category)
            result = {
                "category": category,
                "explanation": explanation,
                "minimums": minimums
            }
            import json
            return json.dumps(result, indent=2)
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": {}})

def _register_check_vfr_minimums(mcp: FastMCP):
    @mcp.tool(
        description="Check if weather conditions meet VFR minimums",
    )
    async def check_vfr_minimums(
        stations: str,
        min_ceiling: float = 3000,
        min_visibility: float = 5
    ) -> str:
        try:
            metar_data = await weather_service.get_metar(stations, hours_back=1)
            results = []
            for metar in metar_data:
                meets_minimums = _check_vfr_minimums(metar, min_ceiling, min_visibility)
                result = {
                    "station": metar.station,
                    "meets_vfr_minimums": meets_minimums["meets"],
                    "current_conditions": {
                        "ceiling": meets_minimums["ceiling"],
                        "visibility": metar.visibility,
                        "flight_category": metar.flight_category.value if metar.flight_category else None
                    },
                    "required_minimums": {
                        "ceiling": min_ceiling,
                        "visibility": min_visibility
                    },
                    "issues": meets_minimums["issues"]
                }
                results.append(result)
            import json
            return json.dumps(results, indent=2)
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": {}})

def _register_decode_metar(mcp: FastMCP):
    @mcp.tool(
        description="Decode a raw METAR string into human-readable format",
    )
    async def decode_metar(
        metar: str
    ) -> str:
        try:
            decoded = _decode_metar_string(metar)
            return decoded
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": {}})

def _determine_flight_category_from_values(ceiling: Optional[float], visibility: Optional[float]) -> str:
    if (ceiling is not None and ceiling < 500) or (visibility is not None and visibility < 1):
        return FlightCategory.LIFR.value
    if (ceiling is not None and ceiling < 1000) or (visibility is not None and visibility < 3):
        return FlightCategory.IFR.value
    if (ceiling is not None and ceiling < 3000) or (visibility is not None and visibility < 5):
        return FlightCategory.MVFR.value
    return FlightCategory.VFR.value

def _get_flight_category_explanation(category: str) -> str:
    explanations = {
        FlightCategory.VFR.value: 'Visual Flight Rules - Good weather conditions for visual flight',
        FlightCategory.MVFR.value: 'Marginal Visual Flight Rules - Marginal conditions for visual flight',
        FlightCategory.IFR.value: 'Instrument Flight Rules - Instrument flight required',
        FlightCategory.LIFR.value: 'Low Instrument Flight Rules - Very poor conditions, approach minimums may be a factor'
    }
    return explanations.get(category, 'Unknown flight category')

def _get_flight_category_minimums(category: str):
    minimums = {
        FlightCategory.VFR.value: {"ceiling": ">= 3000 ft", "visibility": ">= 5 SM"},
        FlightCategory.MVFR.value: {"ceiling": "1000-2999 ft", "visibility": "3-4 SM"},
        FlightCategory.IFR.value: {"ceiling": "500-999 ft", "visibility": "1-2 SM"},
        FlightCategory.LIFR.value: {"ceiling": "< 500 ft", "visibility": "< 1 SM"}
    }
    return minimums.get(category, {"ceiling": "Unknown", "visibility": "Unknown"})

def _find_ceiling(metar_data) -> Optional[float]:
    ceiling = None
    for cloud in metar_data.clouds:
        if cloud.type in ['BKN', 'OVC'] and cloud.altitude:
            if ceiling is None or cloud.altitude < ceiling:
                ceiling = cloud.altitude
    return ceiling

def _check_vfr_minimums(metar, min_ceiling: float, min_visibility: float):
    issues = []
    ceiling = _find_ceiling(metar)
    if ceiling and ceiling < min_ceiling:
        issues.append(f"Ceiling {ceiling} ft is below minimum {min_ceiling} ft")
    if metar.visibility and metar.visibility < min_visibility:
        issues.append(f"Visibility {metar.visibility} SM is below minimum {min_visibility} SM")
    return {
        "meets": len(issues) == 0,
        "ceiling": ceiling,
        "issues": issues
    }

def _decode_metar_string(raw: str) -> str:
    parts = raw.strip().split()
    decoded = "Decoded METAR:\n\n"
    index = 0
    if index < len(parts) and parts[index] in ['METAR', 'SPECI']:
        decoded += f"Type: {parts[index]}\n"
        index += 1
    if index < len(parts) and re.match(r'^[A-Z]{4}$', parts[index]):
        decoded += f"Station: {parts[index]}\n"
        index += 1
    if index < len(parts) and re.match(r'\d{6}Z', parts[index]):
        time = parts[index]
        day = time[0:2]
        hour = time[2:4]
        minute = time[4:6]
        decoded += f"Observation Time: Day {day}, {hour}:{minute} UTC\n"
        index += 1
    if index < len(parts) and re.match(r'\d{3}\d{2}(G\d{2})?KT', parts[index]):
        wind = parts[index]
        dir = wind[0:3]
        speed = wind[3:5]
        gust_match = re.search(r'G(\d{2})', wind)
        decoded += f"Wind: {dir if dir == 'VRB' else dir + '°'} at {int(speed)} knots"
        if gust_match:
            decoded += f" gusting to {int(gust_match.group(1))} knots"
        decoded += "\n"
        index += 1
    while index < len(parts):
        part = parts[index]
        if re.match(r'^\d+SM$', part) or re.match(r'^M?\d+/\d+SM$', part) or part == 'CAVOK':
            if part == 'CAVOK':
                decoded += "Visibility: Ceiling and Visibility OK (>10SM, no clouds below 5000ft)\n"
            else:
                decoded += f"Visibility: {part}\n"
            index += 1
            break
        index += 1
    weather_codes = {
        'RA': 'Rain',
        'SN': 'Snow',
        'BR': 'Mist',
        'FG': 'Fog',
        'HZ': 'Haze',
        'TS': 'Thunderstorm',
        'SH': 'Showers',
        'FZ': 'Freezing',
        'DZ': 'Drizzle',
    }
    weather = []
    while index < len(parts):
        part = parts[index]
        if re.match(r'^(\+|-)?(VC)?[A-Z]{2,6}$', part):
            description = ''
            if part.startswith('+'):
                description += 'Heavy '
            elif part.startswith('-'):
                description += 'Light '
            if 'VC' in part:
                description += 'In vicinity '
            code = re.sub(r'^(\+|-)?VC?', '', part)
            for key, value in weather_codes.items():
                if key in code:
                    description += value + ' '
            if description.strip():
                weather.append(description.strip())
            index += 1
        else:
            break
    if weather:
        decoded += f"Weather: {', '.join(weather)}\n"
    clouds = []
    while index < len(parts):
        part = parts[index]
        if re.match(r'^(CLR|SKC|FEW|SCT|BKN|OVC)\d{3}(CB|TCU)?$', part):
            cloud_type = part[0:3]
            height = int(part[3:6]) * 10
            cb = ' Cumulonimbus' if 'CB' in part else ' Towering Cumulus' if 'TCU' in part else ''
            type_map = {
                'CLR': 'Clear',
                'SKC': 'Sky Clear',
                'FEW': 'Few',
                'SCT': 'Scattered',
                'BKN': 'Broken',
                'OVC': 'Overcast',
            }
            clouds.append(f"{type_map[cloud_type]} at {height} ft{cb}")
            index += 1
        elif part in ['CLR', 'SKC']:
            clouds.append('Clear skies')
            index += 1
        else:
            break
    if clouds:
        decoded += f"Clouds: {', '.join(clouds)}\n"
    if index < len(parts) and re.match(r'^M?\d{2}/M?\d{2}$', parts[index]):
        temps = parts[index].split('/')
        temp = temps[0].replace('M', '-')
        dewpoint = temps[1].replace('M', '-')
        decoded += f"Temperature: {temp}°C, Dewpoint: {dewpoint}°C\n"
        index += 1
    if index < len(parts) and (re.match(r'^A\d{4}$', parts[index]) or re.match(r'^Q\d{4}$', parts[index])):
        alt = parts[index]
        if alt.startswith('A'):
            value = int(alt[1:]) / 100
            decoded += f"Altimeter: {value:.2f} inHg\n"
        else:
            value = int(alt[1:])
            decoded += f"QNH: {value} hPa\n"
        index += 1
    rmk_index = -1
    for i, part in enumerate(parts):
        if part == 'RMK':
            rmk_index = i
            break
    if rmk_index != -1:
        decoded += f"Remarks: {' '.join(parts[rmk_index + 1:])}\n"
    return decoded

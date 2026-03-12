"""
Prompt tools for aviation weather MCP server
"""

from fastmcp import FastMCP

def register(mcp: FastMCP):
    """Register all prompt tools with the FastMCP server."""
    _register_vfr_flight_analysis(mcp)
    _register_weather_briefing(mcp)
    _register_ifr_alternate_requirements(mcp)
    _register_route_weather_analysis(mcp)
    _register_severe_weather_check(mcp)

def _register_vfr_flight_analysis(mcp: FastMCP):
    @mcp.prompt(
        description="Analyze weather conditions for VFR flight planning",
    )
    async def vfr_flight_analysis(
        departure: str,
        destination: str,
        alternates: str = "",
        departure_time: str = ""
    ) -> dict:
        prompt = _generate_vfr_analysis_prompt(departure, destination, alternates, departure_time)
        return {
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": prompt,
                    },
                }
            ]
        }

def _register_weather_briefing(mcp: FastMCP):
    @mcp.prompt(
        description="Generate a comprehensive weather briefing",
    )
    async def weather_briefing(
        airports: str,
        include_area: bool = False
    ) -> dict:
        prompt = _generate_weather_briefing_prompt(airports, include_area)
        return {
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": prompt,
                    },
                }
            ]
        }

def _register_ifr_alternate_requirements(mcp: FastMCP):
    @mcp.prompt(
        description="Check IFR alternate airport requirements",
    )
    async def ifr_alternate_requirements(
        destination: str,
        alternates: str,
        eta: str = ""
    ) -> dict:
        prompt = _generate_ifr_alternate_prompt(destination, alternates, eta)
        return {
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": prompt,
                    },
                }
            ]
        }

def _register_route_weather_analysis(mcp: FastMCP):
    @mcp.prompt(
        description="Analyze weather conditions along a flight route",
    )
    async def route_weather_analysis(
        departure: str,
        destination: str,
        route: str = "",
        altitude: int = 10000
    ) -> dict:
        prompt = _generate_route_analysis_prompt(departure, destination, route, altitude)
        return {
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": prompt,
                    },
                }
            ]
        }

def _register_severe_weather_check(mcp: FastMCP):
    @mcp.prompt(
        description="Check for severe weather conditions that may affect flight operations",
    )
    async def severe_weather_check(
        region: str = "",
        include_turbulence: bool = True,
        include_icing: bool = True,
        include_convection: bool = True
    ) -> dict:
        prompt = _generate_severe_weather_prompt(region, include_turbulence, include_icing, include_convection)
        return {
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": prompt,
                    },
                }
            ]
        }

def _generate_vfr_analysis_prompt(departure, destination, alternates, departure_time):
    prompt = f"Please analyze the weather conditions for a VFR flight:\n\n"
    prompt += f"- Departure: {departure}\n"
    prompt += f"- Destination: {destination}\n"
    if alternates:
        prompt += f"- Alternates: {alternates}\n"
    if departure_time:
        prompt += f"- Planned departure: {departure_time}\n"
    prompt += "\nPlease use the available weather tools to:\n"
    prompt += "1. Get current METAR for all airports\n"
    prompt += "2. Get TAF forecasts for all airports\n"
    prompt += "3. Determine flight categories for each airport\n"
    prompt += "4. Check for any AIRMETs or SIGMETs along the route\n"
    prompt += "5. Provide a go/no-go recommendation based on VFR minimums\n"
    prompt += "6. Highlight any weather trends or concerns\n"
    prompt += "\nFormat the analysis in a clear, pilot-friendly manner with:\n"
    prompt += "- Current conditions summary\n"
    prompt += "- Forecast conditions\n"
    prompt += "- Flight category assessment\n"
    prompt += "- Route considerations\n"
    prompt += "- Safety recommendations\n"
    return prompt

def _generate_weather_briefing_prompt(airports, include_area):
    prompt = f"Generate a comprehensive weather briefing for the following airports: {airports}\n\n"
    prompt += "Please provide:\n"
    prompt += "1. Current conditions (METAR) for each airport\n"
    prompt += "2. Forecast conditions (TAF) for each airport\n"
    prompt += "3. Flight category determination\n"
    prompt += "4. Any significant weather phenomena\n"
    if include_area:
        prompt += "5. Area weather including AIRMETs and SIGMETs\n"
        prompt += "6. PIREPs in the area\n"
    prompt += "\nFormat the briefing in a clear, pilot-friendly manner with:\n"
    prompt += "- Executive summary at the top\n"
    prompt += "- Detailed conditions for each airport\n"
    prompt += "- Any warnings or cautions\n"
    prompt += "- Trends and outlook\n"
    prompt += "- Operational impacts\n"
    return prompt

def _generate_ifr_alternate_prompt(destination, alternates, eta):
    prompt = f"Check IFR alternate airport requirements:\n\n"
    prompt += f"- Destination: {destination}\n"
    prompt += f"- Potential alternates: {alternates}\n"
    if eta:
        prompt += f"- ETA: {eta}\n"
    prompt += "\nPlease:\n"
    prompt += "1. Get TAF for destination to check if alternate is required (1-2-3 rule)\n"
    prompt += "2. Get TAF for all potential alternates\n"
    prompt += "3. Verify each alternate meets minimum weather requirements at ETA\n"
    prompt += "4. Consider approach capabilities and weather minimums\n"
    prompt += "5. Recommend suitable alternates with reasoning\n"
    prompt += "\nFormat the analysis with:\n"
    prompt += "- Destination weather assessment\n"
    prompt += "- Alternate requirements check\n"
    prompt += "- Recommended alternates\n"
    prompt += "- Justification for recommendations\n"
    return prompt

def _generate_route_analysis_prompt(departure, destination, route, altitude):
    prompt = f"Analyze weather conditions along the flight route from {departure} to {destination} at {altitude} feet.\n\n"
    if route:
        prompt += f"Route: {route}\n"
    prompt += f"Altitude: {altitude} feet\n\n"
    prompt += "Please use the available weather tools to:\n"
    prompt += "1. Get METAR for departure and destination airports\n"
    prompt += "2. Get TAF for departure and destination airports\n"
    prompt += "3. Check for AIRMETs/SIGMETs along the route\n"
    prompt += "4. Retrieve PIREPs for the route area and altitude\n"
    prompt += "5. Assess turbulence and icing potential\n"
    prompt += "6. Identify any weather-related hazards\n"
    prompt += "\nFormat the route analysis with:\n"
    prompt += "- Departure and destination conditions\n"
    prompt += "- Route weather overview\n"
    prompt += "- Hazard identification\n"
    prompt += "- Altitude considerations\n"
    prompt += "- Recommended actions or route modifications\n"
    return prompt

def _generate_severe_weather_prompt(region, include_turbulence, include_icing, include_convection):
    prompt = f"Check for severe weather conditions"
    if region:
        prompt += f" in {region}"
    prompt += ".\n\n"
    prompt += "Please use the available weather tools to:\n"
    if include_turbulence:
        prompt += "1. Identify areas of reported or forecasted turbulence\n"
    if include_icing:
        prompt += "2. Identify areas of reported or forecasted icing conditions\n"
    if include_convection:
        prompt += "3. Identify areas of convective activity (thunderstorms, CB clouds)\n"
    prompt += "4. Check for AIRMETs/SIGMETs related to severe weather\n"
    prompt += "5. Review PIREPs for severe weather reports\n"
    prompt += "6. Assess the severity and potential impact on flight operations\n"
    prompt += "\nFormat the severe weather check with:\n"
    prompt += "- Current severe weather conditions\n"
    prompt += "- Forecasted severe weather\n"
    prompt += "- Geographic extent\n"
    prompt += "- Severity levels\n"
    prompt += "- Potential impacts on aviation\n"
    prompt += "- Recommended actions\n"
    return prompt
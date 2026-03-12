"""
Simplified weather agent using pydantic-ai and MCP tools.
"""
import asyncio
import csv
from typing import Dict, Any, List
from rich.markdown import Markdown
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.status import Status
from dotenv import load_dotenv
import pathlib
import os
import json
# from langgraph import Graph, Node
# from langgraph.cache import InMemoryCache
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
import mcp_client
# Get the directory where the current script is located
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
# Define the path to the config file relative to the script directory
CONFIG_FILE = SCRIPT_DIR / "mcp_config.json"
ICAO_MAPPING_FILE = SCRIPT_DIR / "icao_mapping.csv"

load_dotenv()

def get_model() -> OpenAIChatModel:
    """Initialize the LLM model based on environment variables."""
    model_choice = os.getenv('MODEL_CHOICE')
    base_url = os.getenv('BASE_URL')
    api_key = os.getenv('LLM_API_KEY')

    # Create provider with custom base URL for OpenRouter compatibility
    provider = OpenAIProvider(
        base_url=base_url,
        api_key=api_key
    )
    
    return OpenAIChatModel(
        model_name=model_choice,
        provider=provider
    )

def search_airport_by_location(
    location: str,
    max_results: int = 10,
    icao: str = None
) -> List[Dict[str, str]]:
    """
    Search for airports by location name, airport name, or ICAO code.
    
    Args:
        location: Location/airport name/ICAO code to search for (e.g., "Hong Kong", "VHHH", "London")
        max_results: Maximum number of results to return (default: 10)
        icao: Optional ICAO code to filter results (if location is a name)
        
    Returns:
        List of dictionaries containing matching airport information
    """
    try:
        results = []
        search_input = location.upper().strip()
        location_lower = location.lower().strip()
        
        with open(ICAO_MAPPING_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get('icao'):
                    continue
                    
                # Check if matches ICAO code parameter
                if icao and row.get('icao', '').upper() == icao.upper():
                    results.append({
                        'icao': row['icao'],
                        'iata': row.get('iata', ''),
                        'airport': row.get('airport', ''),
                        'region': row.get('region_name', ''),
                        'country': row.get('country_code', ''),
                        'latitude': row.get('latitude', ''),
                        'longitude': row.get('longitude', '')
                    })
                # Check if matches location string (as ICAO, airport name, location, etc.)
                elif location_lower in row.get('icao', '').lower() or \
                     location_lower in row.get('airport', '').lower() or \
                     location_lower in row.get('region_name', '').lower() or \
                     location_lower in row.get('country_code', '').lower() or \
                     location_lower in row.get('iata', '').lower():
                    results.append({
                        'icao': row['icao'],
                        'iata': row.get('iata', ''),
                        'airport': row.get('airport', ''),
                        'region': row.get('region_name', ''),
                        'country': row.get('country_code', ''),
                        'latitude': row.get('latitude', ''),
                        'longitude': row.get('longitude', '')
                    })
                
                if len(results) >= max_results:
                    break
        
        return results if results else [{"error": f"No airport found matching: {location}"}]
    except Exception as e:
        return [{"error": f"Error searching airports: {str(e)}"}]

async def get_weather_agent() -> tuple[mcp_client.MCPClient, Agent]:
    """Initialize the MCP client and create the agent with its tools."""
    client = mcp_client.MCPClient()
    client.load_servers(str(CONFIG_FILE))
    mcp_tools = await client.start()
    
    # Add the airport lookup tool
    def lookup_airport_codes(location: str, max_results: int = 10) -> str:
        """
        Look up airport information by location name, airport name, or ICAO code.
        Use this tool when you need to find airport codes and details.
        
        Args:
            location: Location, airport name, or ICAO code (e.g., "Hong Kong", "VHHH", "London Heathrow")
            max_results: Maximum number of results to return (default: 10)
            
        Returns:
            JSON string with list of matching airports with their ICAO codes, names, and locations
        """
        results = search_airport_by_location(location, max_results)
        return json.dumps(results, indent=2)
    
    # Combine MCP tools with the airport lookup tool
    all_tools = mcp_tools + [lookup_airport_codes]
    
    # Create the agent with all tools
    agent = Agent(
        model=get_model(),
        tools=all_tools,
        system_prompt="""You are a helpful assistant specializing in weather information. You have access to tools to:

1. **Look up airport codes**: Use the 'lookup_airport_codes' tool to find ICAO codes from location names (cities, countries, regions, airport names)
2. **Fetch aviation weather**: Get METAR, TAF, AIRMETs, and other aviation weather data using ICAO codes
3. **Fetch Hong Kong weather**: Get current conditions, forecasts, and warnings for Hong Kong

**Important workflow**:
- When a user mentions a location without providing an ICAO code, FIRST use 'lookup_airport_codes' to find the correct ICAO code(s)
- If multiple airports are found, select the most relevant one(s) based on context (e.g., major international airports for general queries)
- Then use the ICAO codes to fetch weather data from the appropriate tools

Provide clear, concise, and relevant information based on the data retrieved by the tools."""
    )
    return client, agent

async def main():
    
    mcp_client_instance, weather_agent = await get_weather_agent()
    console = Console()
    messages = []
    
    try:
        while True:
            # Get user input
            user_input = input("\n[You] ")
            
            # Check if user wants to exit
            if user_input.lower() in ['exit', 'quit', 'bye', 'goodbye']:
                print("Goodbye!")
                break
            
            try:
                # Process the user input and output the response
                console.print("\n[bold blue][Assistant][/bold blue]")
                
                # Optional: Show a status indicator while the agent is running
                with Status("[bold green]Processing your request and calling tools if needed...[/bold green]", spinner="clock") as status:
                    async with weather_agent.run_stream(
                        user_input, message_history=messages
                    ) as result:
                        # Update status once tool calls are finished
                        status.update("[bold yellow]Formatting response...[/bold yellow]")
                        
                        # Stream the final response from the LLM
                        full_response_text = ""
                        async for message in result.stream_text(delta=True):
                            full_response_text += message
                            # Update the live display with the current text
                            # Using Panel for better visual separation
                            live_content = Panel(Markdown(full_response_text), border_style="bright_blue", title="Weather Report")
                            # Note: Live updates might flicker with complex content.
                            # Consider printing chunks directly if Panel causes issues.
                            console.clear_live() # Clear previous live display if any
                            console.print(live_content) 
                
                # Add the new messages (including tool calls and final LLM response) to the chat history
                messages.extend(result.all_messages())
                
            except Exception as e:
                console.print(f"\n[bold red][Error][/bold red] An error occurred: {str(e)}")

    except KeyboardInterrupt:
        print("\nInterrupted by user. Goodbye!")
        
    finally:
        # Ensure proper cleanup of MCP client resources when exiting
        if mcp_client_instance:
            await mcp_client_instance.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
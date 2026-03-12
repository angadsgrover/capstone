from setuptools import setup, find_packages

setup(
    name="aviation_weather_mcp_server",
    version="0.1.0",
    description="Model Context Protocol server for aviation weather data",
    packages=find_packages(),
    install_requires=[
        "fastmcp>=2.10.2",
        "aiohttp>=3.8.0",
        "requests>=2.31.0",
    ],
    entry_points={
        "console_scripts": [
            "aviation-weather-mcp=aviation_weather_mcp_server.__main__:main",
        ],
    },
)
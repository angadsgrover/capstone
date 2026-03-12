# Unified Pydantic AI & LangGraph Weather Orchestration

This project demonstrates a comprehensive integration of Pydantic AI, LangGraph, knowledge graphs, and Model Context Protocol (MCP) servers for advanced weather data orchestration. The system combines aviation weather and Hong Kong climate data with intelligent orchestration and knowledge-enhanced reasoning.

## Overview

The Unified Weather Orchestration System is designed to:
- **Primary Workflow Engine**: Use Pydantic AI as the main workflow engine 
- **Intelligent Orchestration**: Use LangGraph for multi-agent coordination when complex workflows are needed
- **Knowledge Graph Integration**: Enhance responses with contextual relationships and entities
- **MCP Server Integration**: Connect to aviation weather and Hong Kong climate MCP servers
- **Prompt Engineering**: Implement sophisticated prompts for all components
- **Backward Compatibility**: Maintain integration with existing pydantic-ai-mcp projects

## Architecture

The system consists of:

### 1. Core Components
- **Pydantic AI Agent**: Primary workflow engine with intelligent routing
- **LangGraph Orchestrator**: Multi-agent coordination for complex requests
- **Knowledge Graph**: Contextual understanding of weather entities and relationships
- **MCP Client**: Universal connector for multiple MCP servers

### 2. Specialized Agents
- **Aviation Weather Specialist**: Handles METAR, TAF, PIREP, AIRMET data
- **HK Weather Specialist**: Processes Hong Kong Observatory data
- **Comparison Analyst**: Analyzes relationships between different data sources

### 3. Integration Layer
- **Unified Assistant**: Intelligent routing between all components
- **Legacy Compatibility Wrapper**: Maintains compatibility with original projects
- **Knowledge Graph Orchestrator**: Integrates knowledge context with real-time data

## Features

### Pydantic AI as Primary Engine
- Uses Pydantic AI for all primary workflow management
- Intelligent query routing based on complexity and requirements
- Direct integration with MCP server tools
- Structured response formatting

### LangGraph Multi-Agent Orchestration
- Activated for complex multi-domain queries
- Specialized agents for different weather domains
- Coordinated processing for comprehensive analysis
- Dynamic routing based on query requirements

### Knowledge Graph Capabilities
- Built-in weather entity relationships
- Contextual understanding of weather concepts
- Enhanced reasoning through entity connections
- Comprehensive weather domain knowledge base

### MCP Server Integration
- Connects to both aviation and HK weather MCP servers
- Real-time data access via standardized tools
- Fallback mechanisms for robust operation
- Configurable server management

### Advanced Prompt Engineering
- System prompts for each specialized agent
- Context-aware query processing
- Knowledge graph enhanced responses
- Multi-step reasoning prompts

## Setup

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure both MCP servers are available:
   - Aviation Weather MCP Server: `/path/to/aviation-weather-mcp-python`
   - HK Climate MCP Server: `/path/to/hk-climate-mcp-server-python`

3. Set up your environment variables in a `.env` file:
```env
LLM_API_KEY=your_api_key_here
MODEL_CHOICE=gpt-4o-mini
BASE_URL=https://api.openai.com/v1
```

4. Update the `mcp_config.json` file with the correct paths to your MCP server modules if needed.

## Usage

### 1. Run the Unified Assistant (Recommended)
```bash
python main.py
```
This provides the complete integrated experience with all components working together.

### 2. Component-Specific Modes
- **Knowledge Graph Analysis**: `python knowledge_graph.py`
- **Multi-Agent Orchestration**: `python multi_agent_orchestrator.py` 
- **Basic Orchestration**: `python advanced_orchestrator.py`
- **Integration Demo**: `python integration.py`

### 3. Examples of Supported Queries
- "What's the current weather at Hong Kong International Airport?"
- "Compare aviation weather with general HK weather conditions"
- "How do METAR and TAF reports relate to each other?"
- "Explain flight conditions at VHHH airport"
- "What weather warnings are active in Hong Kong?"

## Project Structure

```
langgraph-weather-orchestration/
├── main.py                     # Unified entry point with all components
├── integration.py              # Integration with existing pydantic-ai-mcp projects
├── advanced_orchestrator.py    # Pydantic AI primary workflow + optional LangGraph
├── multi_agent_orchestrator.py # LangGraph-based multi-agent system
├── knowledge_graph.py          # Knowledge graph with weather entities and relationships
├── mcp_client.py               # Enhanced MCP client for multiple servers
├── mcp_config.json             # Configuration for MCP servers
├── requirements.txt            # Python dependencies
├── README.md                   # This file
└── .env.example               # Environment variables template
```

## Key Components

### Knowledge Graph (`knowledge_graph.py`)
- Predefined weather entities (airports, weather stations, conditions)
- Relationships between weather concepts
- Context-aware querying capabilities
- Integration with Pydantic AI for enhanced responses

### Multi-Agent Orchestration (`multi_agent_orchestrator.py`)
- Specialized agents for aviation and HK weather
- Comparison analyst for multi-domain queries
- Dynamic agent routing based on query complexity
- Coordinated response synthesis

### Unified Integration (`integration.py`)
- Backward compatibility with original pydantic-ai-mcp projects
- Intelligent component selection
- Comprehensive error handling
- Legacy interface preservation

### Main System (`main.py`)
- Unified interface for all components
- Interactive and demonstration modes
- Intelligent query routing
- Rich text output formatting

## Advanced Features

### Intelligent Query Routing
The system analyzes each query and automatically determines:
- Simple queries → Direct Pydantic AI processing
- Complex multi-domain queries → Multi-agent orchestration
- Knowledge/relationship queries → Knowledge graph enhancement
- Real-time data needs → MCP server integration

### Prompts and Reasoning
The system includes sophisticated prompts for:
- System-level instructions for overall behavior
- Agent-specific instructions for specialized tasks
- Context-aware query enhancement
- Multi-step reasoning for complex analysis

### Extensibility
To add new capabilities:
1. Create new knowledge graph entities in `knowledge_graph.py`
2. Add new specialized agents in the multi-agent system
3. Update the intelligent routing logic if needed
4. Add new MCP server configurations to `mcp_config.json`

## Configuration

The `mcp_config.json` file defines which MCP servers to connect to:

```json
{
  "mcpServers": {
    "aviation-weather": {
      "command": "python",
      "args": [
        "-m",
        "aviation_weather_mcp_server"
      ]
    },
    "hk-climate": {
      "command": "python", 
      "args": [
        "-m",
        "hk_climate_mcp_server"
      ]
    }
  }
}
```

## Troubleshooting

1. **If MCP servers don't connect**: Verify that the aviation and HK climate MCP server packages are properly installed and accessible.

2. **If knowledge graph seems limited**: The default knowledge graph includes common weather entities; you can extend it by adding new nodes and relationships.

3. **If multi-agent orchestration seems slow**: Complex queries trigger multi-agent coordination, which may take longer but provides more comprehensive results.
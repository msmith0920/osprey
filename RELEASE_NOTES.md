# Osprey Framework - Latest Release (v0.9.9)

🎉 **Middle Layer Pipeline for Channel Finder** - Complete MML Database Support with React Agent Navigation

## What's New in v0.9.9

### 🚀 Major New Features

#### Channel Finder: Middle Layer Pipeline
- **Complete React Agent-Based Pipeline**: New channel finder pipeline for MATLAB Middle Layer (MML) databases
  - System→Family→Field hierarchical navigation
  - LangGraph-based React agent with structured output
  - 5 specialized database query tools:
    - `list_systems` - Discover available control systems
    - `list_families` - Explore device families within systems
    - `inspect_fields` - View available fields and signals
    - `list_channel_names` - Get EPICS channel names
    - `get_common_names` - Retrieve common device names
  - MiddleLayerDatabase class with O(1) validation and device/sector filtering
  - Optional `_description` fields at all hierarchy levels for enhanced LLM guidance
  - MMLConverter utility for Python MML exports to JSON

- **Sample Database & Benchmarks**: Production-ready testing infrastructure
  - 2,033-channel sample database covering 3 systems (SR, BR, BTS)
  - 20 device families with full metadata
  - 35-query benchmark dataset (20% coverage ratio - best of all pipelines)
  - Realistic accelerator physics context

- **Comprehensive Documentation**: Full Sphinx documentation
  - Complete tutorial with architecture comparison
  - Usage examples and CLI integration
  - End-to-end benchmark validation

#### AI Workflow System
- **New `osprey workflows` CLI Command**: Export AI workflow files to your projects
  - `osprey workflows export` - Export workflows to local directory (default: ./osprey-workflows/)
  - `osprey workflows list` - List all available workflow files
  - Interactive menu integration for easy access

- **Package-Bundled Workflows**: Moved from `docs/workflows/` to `src/osprey/workflows/`
  - Workflows distributed with installed package
  - Version-locked workflow documentation
  - AI-assisted development guides for channel finder
  - Pipeline selection guide and database builder guide with AI prompts

- **Enhanced Documentation**: Channel Finder workflow guides
  - AI-assisted workflow dropdowns in tutorial sections
  - Code reference sections for evidence-based recommendations
  - Integration with AI-assisted development guide

### 🔧 Infrastructure Improvements

#### Channel Finder Tools
- **CLI Tool Enhancements**: Middle layer support across all tools
  - Database preview tool with tree visualization for functional hierarchy
  - CLI query interface with middle_layer pipeline support
  - Benchmark runner with middle_layer dataset support

#### Templates
- **Enhanced Project Generation**: Middle layer configuration support
  - Conditional config generation for middle_layer pipeline
  - Dynamic AVAILABLE_PIPELINES list based on enabled pipelines
  - Database and benchmark paths auto-configured
  - Updated CLI project initialization with middle_layer option

#### Registry System
- **Silent Initialization Mode**: Clean CLI output support
  - Suppress INFO/DEBUG logging when `silent=True`
  - Useful for CLI tools requiring clean output

### 🧪 Testing

#### Comprehensive Test Coverage
- **480+ Lines of New Tests**: Complete middle layer testing
  - All database query tools tested
  - Prompt loader with middle_layer support
  - MML converter utility enhancements
  - End-to-end benchmark validation

### 🐛 Bug Fixes

#### Channel Finder Improvements
- **Navigation Fixes**: Multiple improvements to hierarchical navigation
  - Fixed leaf node detection for multiple direct signals (e.g., "status and heartbeat")
  - Enhanced LLM awareness for optional levels
  - Fixed separator overrides in `build_channels_from_selections()`
  - Fixed navigation through expanded instances at optional levels

#### Testing
- **Benchmark Test Fix**: Corrected middle layer benchmark test assertion
  - Now uses `queries_evaluated` instead of `total_queries`
  - Properly validates query_selection limiting

#### Build & Configuration
- **Code Quality**: Removed trailing whitespace from configuration and script files

### 🔄 Breaking Changes

#### Channel Finder
- **Middle Layer Pipeline Migration**: Migrated from Pydantic-AI to LangGraph
  - Now uses LangGraph's `create_react_agent` for improved behavior
  - Tools converted from Pydantic-AI format to LangChain StructuredTool
  - Enhanced structured output with ChannelSearchResult model
  - Better error handling and agent state management

### 📚 Documentation Updates

- **Workflow References**: Updated to use `@osprey-workflows/` path
- **AI Development Guide**: Added workflow export instructions
- **Tutorial Improvements**: AI-assisted workflow dropdowns for all three pipelines
- **Removed Obsolete Content**: Migrated markdown tutorials to Sphinx docs

---

## Installation

```bash
pip install --upgrade osprey-framework
```

Or install with all optional dependencies:

```bash
pip install --upgrade "osprey-framework[all]"
```

## Quick Start with Middle Layer Pipeline

```bash
# Create a new project with middle layer pipeline
osprey init my-project --template control_assistant --pipelines middle_layer

# Export AI workflow guides
osprey workflows export

# Preview the database structure
osprey channel-finder preview-database --pipeline middle_layer

# Run benchmark tests
osprey channel-finder benchmark --pipeline middle_layer
```

## Migration Guide

### For Existing Users

If you're upgrading from v0.9.8:

1. **Middle Layer Pipeline** is now available as a third channel finder option
   - Ideal for facilities with MATLAB Middle Layer databases
   - Complements existing in_context and hierarchical pipelines

2. **AI Workflows** are now bundled with the package
   - Run `osprey workflows export` to get the latest guides
   - Update your AI assistant references to use `@osprey-workflows/`

3. **No Breaking Changes** for existing projects
   - in_context and hierarchical pipelines unchanged
   - All existing functionality preserved

---

## What's Next?

Check out our [documentation](https://als-apg.github.io/osprey) for:
- Complete Middle Layer Pipeline tutorial
- AI-assisted development workflows
- Channel Finder architecture comparison
- Best practices for database design

## Contributors

Thank you to everyone who contributed to this release!

---

**Full Changelog**: https://github.com/als-apg/osprey/blob/main/CHANGELOG.md

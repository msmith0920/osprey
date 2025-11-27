# Osprey Framework - Latest Release (v0.9.3)

🎉 **LLM API Call Logging & End-to-End Testing** - Enhanced Developer Experience & Quality Assurance

## What's New in v0.9.3

### 🚀 Major New Features

#### LLM API Call Logging
- **Complete transparency** into all LLM API interactions for debugging and optimization
- **Rich metadata capture**: caller function, module, class, line number, model config, timestamps
- **Context variable propagation** through async/thread boundaries using Python's `contextvars`
- **Intelligent caller detection** that skips thread pool and asyncio internals to find actual business logic
- **Capability-aware logging**: Classifier logs include capability name for parallel classification tasks
- **Configurable options**:
  - `save_all`: Save all API calls or just latest
  - `latest_only`: Keep only most recent call per endpoint
  - `include_stack_trace`: Add full stack trace for detailed debugging
- **Organized output**: Files saved to `_agent_data/api_calls/` with descriptive naming
- **Integration helpers**: `set_api_call_context()` function for classifier and orchestrator nodes
- **Documentation**: Complete guide in prompt customization and configuration reference

#### End-to-End Test Infrastructure
- **LLM Judge System** - AI-powered test evaluation with structured scoring
  - Evaluates workflows against plain-text expectations for flexible validation
  - Provides confidence scores (0.0-1.0) and detailed reasoning
  - Identifies warnings and concerns even in passing tests
- **E2E Project Factory** - Automated test project creation and execution
  - Creates isolated test projects from templates in temporary directories
  - Full framework initialization with registry, graph, and gateway setup
  - Query execution with complete state management and artifact collection
  - Working directory management for correct `_agent_data/` placement
  - Root logger capture for comprehensive execution trace logging
- **Tutorial Tests** - Validates complete user workflows
  - `test_bpm_timeseries_and_correlation_tutorial`: Full control assistant workflow
  - `test_simple_query_smoke_test`: Quick infrastructure validation
- **CLI Test Options**:
  - `--e2e-verbose`: Real-time progress updates during test execution
  - `--judge-verbose`: Detailed LLM judge reasoning and evaluation
  - `--judge-provider` and `--judge-model`: Configurable judge AI model
- **Belt and Suspenders Validation**: LLM judge + hard assertions for reliable testing
- **Comprehensive Documentation**: Complete testing guide at `tests/e2e/README.md`

#### Unified Logging with Automatic Streaming
- **Single API**: `BaseCapability.get_logger()` provides unified logging and streaming
- **Enhanced ComponentLogger** with automatic LangGraph streaming support
- **New `status()` method** for high-level progress updates
- **Configurable streaming**: Per-method control with `stream` parameter
- **Smart defaults**:
  - `status()`, `error()`, `success()`, `warning()` stream automatically to web UI
  - `info()`, `debug()` remain CLI-only by default
- **Lazy stream writer initialization** with graceful degradation
- **Custom metadata support** via `**kwargs` on all logging methods
- **Automatic step tracking** integrated with TASK_PREPARATION_STEPS
- **Framework-wide migration**: All infrastructure nodes, capabilities, and templates updated
- **26 comprehensive tests** in `tests/utils/test_logger.py`
- **Backward compatible**: Existing patterns continue to work

#### CLI Provider/Model Configuration
- **New flags for `osprey init`**: `--provider` and `--model` options
- **Streamlined setup**: Configure AI provider during project creation
- **Better developer experience**: Skip manual configuration file editing

### 📈 Enhanced Features

- **Capability Base Class**: Moved exception handling for classifier/orchestrator guide creation to base class with warning logs
- **Capability Templates**: Cleaned up unused imports and logger usage in all templates

### 📦 Installation

```bash
pip install osprey-framework==0.9.3
```

Or upgrade from previous version:

```bash
pip install --upgrade osprey-framework
```

### 🎯 Quick Example: LLM API Call Logging

Enable comprehensive API call logging in your `config.yml`:

```yaml
development:
  api_calls:
    save_all: true           # Save all API calls
    latest_only: false       # Keep historical logs
    include_stack_trace: true  # Include full stack trace
```

API call logs will be saved to `_agent_data/api_calls/` with files like:
- `classification_node_CapabilityClassifier__perform_classification_channel_finding_latest.txt`
- `orchestration_node_Orchestrator_create_execution_plan_latest.txt`
- `respond_node_ResponseCapability_execute_latest.txt`

Each log includes:
- Complete request (system prompt, user message, model config)
- Complete response (raw LLM output)
- Metadata (caller info, timestamps, token counts)
- Optional stack trace for deep debugging

### 🧪 Quick Example: Running E2E Tests

```bash
# Run all e2e tests with progress updates
pytest tests/e2e/ -v -s --e2e-verbose

# Run with detailed LLM judge reasoning
pytest tests/e2e/ -v -s --e2e-verbose --judge-verbose

# Use specific model for judge
pytest tests/e2e/ -v -s --e2e-verbose --judge-provider anthropic --judge-model claude-3-5-haiku-latest
```

### 📊 Testing

- **336 Total Tests** (2 new e2e tests added)
  - 334 unit/integration tests
  - 2 end-to-end workflow tests
- **All tests passing** ✅
- **E2E test coverage**:
  - Complete control assistant workflow (channel finding → archiver → plotting)
  - Basic infrastructure smoke test
  - ~2-5 minutes total runtime
  - ~$0.10-$0.25 in API costs

### 🔗 Links

- **Documentation**: https://als-apg.github.io/osprey
- **GitHub**: https://github.com/als-apg/osprey
- **PyPI**: https://pypi.org/project/osprey-framework/0.9.3/
- **Changelog**: See CHANGELOG.md for complete details

### 🙏 Contributors

Special thanks to everyone who reported issues and provided feedback for this release!

---

## Previous Releases

For previous release notes, see [CHANGELOG.md](CHANGELOG.md).

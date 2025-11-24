# Testing Guide - Unified Logging Feature

**Branch**: `feat/unified-logging`  
**Requirements**: Python 3.11+

## Overview

This branch introduces unified logging with automatic streaming support, eliminating the dual logger/streamer pattern throughout the framework.

## Quick Setup

```bash
# 1. Checkout the branch
git checkout feat/unified-logging

# 2. Create virtual environment (if not already created)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install Osprey in development mode
pip install -e "."

# 4. Run the test suite
pytest tests/utils/test_logger.py -v
```

## What Changed

### Core Implementation
- Added `BaseCapability.get_logger()` method for unified logging and streaming
- Enhanced `ComponentLogger` with automatic LangGraph streaming support
- New `status()` method for high-level progress updates
- Lazy stream writer initialization with graceful degradation

### Migration Scope
- All infrastructure nodes (orchestration, classification, task_extraction, respond)
- All framework capabilities (time_range_parsing, memory, python)
- All Python executor service nodes (generator, executor, approval, analyzer)
- All templates and code generators
- Documentation and examples

## Testing Focus Areas

### 1. Automated Tests
```bash
# Run unified logging tests
pytest tests/utils/test_logger.py -v

# Run all tests to verify no regressions
pytest tests/ -v
```

### 2. Manual Testing - New Pattern

Test that the new unified logging pattern works in a capability:

```python
@capability_node
class TestCapability(BaseCapability):
    name = "test_capability"
    description = "Testing unified logging"
    
    async def execute(self) -> dict[str, Any]:
        # Single logger provides both logging and streaming
        logger = self.get_logger()
        
        logger.status("Processing...")  # Streams to web UI
        logger.info("Detailed info")    # CLI only
        logger.success("Complete!")     # Streams to web UI
        
        return self.store_output_context(result)
```

### 3. Backward Compatibility

Verify old code still works:

```python
# Old pattern should still work
logger = get_logger("component_name")
streamer = get_streamer("component_name", state)

logger.info("Still works")
streamer.status("Still works")
```

### 4. Documentation

Verify documentation builds correctly:

```bash
cd docs
python launch_docs.py
# Visit: http://localhost:8082
```

Check that:
- API reference shows new `ComponentLogger` methods
- Developer guides show unified logging pattern
- Examples use `self.get_logger()` pattern
- No outdated dual logger/streamer examples remain

## Expected Behavior

### Streaming Defaults
- **Always stream**: `status()`, `error()`
- **Stream by default**: `success()`, `warning()`, `approval()`, `resume()`
- **CLI-only by default**: `info()`, `debug()`, `key_info()`, `timing()`
- **Override**: Use `stream=True/False` parameter

### Graceful Degradation
Logger should work correctly in all contexts:
- In LangGraph execution (with streaming)
- In tests (without streaming)
- In CLI-only mode (without streaming)
- In utilities (without streaming)

## Reporting Issues

Found a bug or have suggestions? https://github.com/als-apg/osprey/issues


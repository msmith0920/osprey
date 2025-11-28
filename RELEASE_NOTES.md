# Osprey Framework - Latest Release (v0.9.4)

🎉 **Flexible Hierarchical Database Schema & E2E Benchmarks** - Advanced Control System Organization & Testing

## What's New in v0.9.4

### 🚀 Major New Features

#### Flexible Hierarchical Database Schema
- **Clean, flexible schema** for defining arbitrary control system hierarchies
- **Single `hierarchy` section** combines level definitions and naming pattern with built-in validation
- **Arbitrary mixing** of tree navigation (semantic categories) and instance expansion (numbered/patterned devices) at any level
- **Advanced hierarchy patterns**:
  - Multiple consecutive instance levels (e.g., SECTOR→DEVICE, FLOOR→ROOM)
  - Instance-first hierarchies (instances at root level)
  - Any tree/instance pattern combination
- **Automatic validation** ensures level names and naming patterns stay in sync (catches errors at load time, not runtime)
- **Level type specification**: Each level declares `name` and `type` (`tree` for semantic categories, `instances` for numbered expansions)
- **Cleaner schema**: Removed redundant/confusing fields (eliminated `_structure` documentation field, consolidated three separate config fields into one)
- **Comprehensive test suite**: 33 unit tests including 6 new naming pattern validation tests (all passing)
- **Real-world example databases**:
  - `hierarchical.json`: Accelerator control (1,048 channels) - SYSTEM[tree]→FAMILY[tree]→DEVICE[instances]→FIELD[tree]→SUBFIELD[tree]
  - `mixed_hierarchy.json`: Building management (1,720 channels) - SECTOR[instances]→BUILDING[tree]→FLOOR[instances]→ROOM[instances]→EQUIPMENT[tree]
  - `instance_first.json`: Manufacturing (85 channels) - LINE[instances]→STATION[tree]→PARAMETER[tree]
  - `consecutive_instances.json`: Accelerator naming (4,996 channels) - SYSTEM[tree]→FAMILY[tree]→SECTOR[instances]→DEVICE[instances]→PROPERTY[tree]
- **Backward compatibility**: Legacy databases with implicit configuration automatically converted with deprecation warnings
- **Scalability**: Support hierarchies from 1 to 15+ levels with any combination of types
- **Complete documentation**: Updated with clean schema examples and comprehensive guides

#### Channel Finder E2E Benchmarks
- **New benchmark test suite** for hierarchical channel finder pipeline
- **Comprehensive testing** across all hierarchy complexity levels
- **Performance metrics**: navigation depth, branching factor, channel count
- **Validation** of correct channel finding across diverse hierarchy patterns
- **Example queries** testing system understanding and multi-level navigation
- **Quality assurance** for production control system deployments

#### Hello World Weather E2E Test
- **Complete tutorial validation** - Tests entire Hello World workflow end-to-end
- **Weather capability execution** - Validates mock API integration and capability framework
- **Registry initialization** - Ensures clean framework setup for new users
- **LLM judge evaluation** - Confirms beginner-friendly experience
- **Template validation** - Verifies project generation and framework setup

### 📈 Enhanced Features

#### Test Infrastructure Improvements
- **Fixed test isolation** between unit tests and e2e tests using `reset_registry()`
- **Updated e2e tests** to use Claude Haiku (faster, more cost-effective)
- **Separated test execution** to prevent registry mock contamination
- **Updated channel finder tests** to use new unified database schema (`"type"` instead of `"structure"`)
- **Enhanced documentation**: Updated `RELEASE_WORKFLOW.md` with clear instructions for running unit tests (`pytest tests/ --ignore=tests/e2e`) and e2e tests (`pytest tests/e2e/`) separately

### 📦 Installation

```bash
pip install osprey-framework==0.9.4
```

Or upgrade from previous version:

```bash
pip install --upgrade osprey-framework
```

### 🎯 Quick Example: Hierarchical Database Schema

Define a flexible control system hierarchy in your channel database JSON:

```json
{
  "hierarchy": [
    {
      "name": "SYSTEM",
      "type": "tree",
      "categories": ["DIAG", "VAC", "RF"]
    },
    {
      "name": "DEVICE",
      "type": "instances",
      "expansion": {
        "type": "range",
        "start": 1,
        "end": 10,
        "format": "{:02d}"
      }
    },
    {
      "name": "FIELD",
      "type": "tree",
      "categories": ["POSITION", "CURRENT", "VOLTAGE"]
    }
  ],
  "naming_pattern": "{SYSTEM}:{DEVICE}:{FIELD}",
  "description": "Accelerator diagnostics with mixed tree/instance levels"
}
```

This creates channels like: `DIAG:01:POSITION`, `VAC:05:CURRENT`, etc.

### 🧪 Quick Example: Running E2E Tests

```bash
# Run unit tests (fast, ~3 seconds)
pytest tests/ --ignore=tests/e2e -v

# Run e2e tests with progress updates (~2 minutes)
pytest tests/e2e/ -v -s --e2e-verbose

# Run with detailed LLM judge reasoning
pytest tests/e2e/ -v -s --e2e-verbose --judge-verbose
```

### 📊 Testing

- **379 Total Tests** (5 new e2e tests, 38 new unit tests)
  - 374 unit/integration tests
  - 5 end-to-end workflow tests
- **All tests passing** ✅
- **E2E test coverage**:
  - Complete control assistant workflow (channel finding → archiver → plotting)
  - Hello World weather tutorial validation
  - Channel finder benchmarks (in-context and hierarchical pipelines)
  - Basic infrastructure smoke test
  - ~2-3 minutes total runtime
  - ~$0.10-$0.25 in API costs

### 🔗 Links

- **Documentation**: https://als-apg.github.io/osprey
- **GitHub**: https://github.com/als-apg/osprey
- **PyPI**: https://pypi.org/project/osprey-framework/0.9.4/
- **Changelog**: See CHANGELOG.md for complete details

### 🙏 Contributors

Special thanks to everyone who reported issues and provided feedback for this release!

---

## Previous Releases

For previous release notes, see [CHANGELOG.md](CHANGELOG.md).

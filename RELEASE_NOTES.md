# Osprey Framework - Latest Release (v0.9.2)

🎉 **Instance Method Pattern Release** - Major Ergonomic Improvements & Critical Bug Fixes

## What's New in v0.9.2

### 🚀 Major New Features

#### Instance Method Pattern for Capabilities
- **~60% Less Boilerplate**: New instance method pattern dramatically simplifies capability development
- **Helper Methods Available via `self`**:
  - `get_required_contexts()` - Extract required contexts with automatic validation and tuple unpacking
  - `get_task_objective()` - Get current task description
  - `get_parameters()` - Get step parameters
  - `store_output_context()` / `store_output_contexts()` - Store output contexts
- **Full Backward Compatibility**: Static method pattern still works
- **Runtime State Injection**: `@capability_node` decorator injects `_state` and `_step` automatically
- **Migration Guide**: Comprehensive documentation at `docs/source/developer-guides/migration-guide-instance-methods.rst`

#### Infrastructure Node Instance Method Migration ✅ COMPLETE
- **All 7 infrastructure nodes** migrated to instance method pattern
- **Enhanced Decorators**: Automatic `_state` injection for all nodes, selective `_step` injection for clarify/respond
- **15 New Tests**: Validates decorator injection logic and backward compatibility
- Aligns infrastructure with capability implementation patterns

#### Argo AI Provider (ANL Institutional Service)
- **New provider** for Argonne National Laboratory's Argo proxy service
- **8 models supported**: Claude (4 models), Gemini (3 models), GPT-5, GPT-5 Mini
- **OpenAI-compatible interface** with structured output support
- Uses `$USER` environment variable for ANL authentication

#### Cardinality Constraints
- **Declare requirements with cardinality**: `requires = [("DATA", "single")]`
- **Automatic validation**: Framework raises clear errors if violated
- **Eliminates manual checks**: No more `isinstance(context, list)` in your code
- **9 new tests** for cardinality validation

### 🐛 Critical Bug Fixes

**Context Manager Data Loss** - CRITICAL
- Fixed bug where multiple contexts of same type were silently lost
- Two-phase extraction algorithm now preserves all contexts
- Returns list for multiple contexts, object for single context
- 17 comprehensive test cases added

**Interactive Menu Registry Contamination** ([#29](https://github.com/als-apg/osprey/issues/29))
- Fixed capability leakage between projects in interactive menu
- Registry properly resets when switching projects
- Prevents second project from inheriting first project's capabilities

**Template Fixes**
- Stanford API key detection added
- Weather template context extraction fixed
- Archiver retrieval template uses string literals instead of registry references

### 📊 Testing

- **312 Total Tests** (87 new tests added)
  - 15 tests for capability helper methods
  - 17 tests for context extraction with multiple contexts
  - 9 tests for cardinality validation
  - 15 tests for infrastructure decorator pattern
  - 12 tests for capability instance method pattern
  - 3 tests for registry reset/isolation
- **All tests passing** ✅

### ⚠️ Breaking Changes

These breaking changes are acceptable as the framework is in early access (0.9.x):

1. **`BaseCapabilityContext.get_summary()`** - No longer takes `key` parameter
2. **`BaseCapabilityContext.get_access_details()`** - Now requires `key` parameter (no longer optional)
3. **`ContextManager.get_summaries()`** - Returns `list` instead of `dict`

See migration guide for details on updating custom implementations.

### 📚 Documentation

- **20+ files updated** with new patterns
- **New migration guide** for instance method pattern
- **Updated templates**: All capability templates use new recommended pattern
- **API reference** updated for breaking changes

### 📦 Installation

```bash
pip install osprey-framework==0.9.2
```

Or upgrade from previous version:

```bash
pip install --upgrade osprey-framework
```

### 🎯 Quick Start with New Pattern

```python
from osprey.base.capability import BaseCapability, capability_node

class MyCapability(BaseCapability):
    """Example using new instance method pattern"""

    requires = [
        ("DATA", "single"),      # Cardinality constraint
        ("TIME_RANGE", "single")
    ]
    provides = ["ANALYSIS"]

    @capability_node
    def execute(self):
        # Use helper methods - no boilerplate!
        data, time_range = self.get_required_contexts()
        objective = self.get_task_objective()
        params = self.get_parameters()

        # Do your work
        result = analyze_data(data, time_range)

        # Store output - one line!
        self.store_output_context("ANALYSIS", result)

        return "Analysis complete"
```

### 🔗 Links

- **Documentation**: https://osprey-framework.readthedocs.io
- **GitHub**: https://github.com/als-apg/osprey
- **Migration Guide**: https://osprey-framework.readthedocs.io/en/latest/developer-guides/migration-guide-instance-methods.html
- **Changelog**: See CHANGELOG.md for complete details

### 🙏 Contributors

Special thanks to everyone who reported issues and provided feedback for this release!

---

## Previous Releases

For previous release notes, see [CHANGELOG.md](CHANGELOG.md).

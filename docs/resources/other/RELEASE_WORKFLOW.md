# Release Workflow - Documentation Version Sync Fix

This document provides the **definitive workflow** for creating releases that ensure documentation always shows the correct version.

## 🎯 Problem Solved

**Issue**: Documentation shows previous version (e.g., v0.7.1) instead of current version (v0.7.2) because:
1. Documentation builds from current commit using `git describe --tags`
2. Tag creation happens after documentation build
3. Result: Documentation gets the old tag, not the new one

**Solution**: Use GitHub's `GITHUB_REF` environment variable in GitHub Actions to get the exact tag being built.

## 📋 Correct Release Workflow

### **Step 0: Pre-Release Testing (CRITICAL)**

**⚠️ IMPORTANT**: Always run tests before starting the release process.

1. **Activate Virtual Environment**
   ```bash
   source venv/bin/activate
   ```

2. **Run Unit & Integration Tests**
   ```bash
   # Run fast tests (excludes e2e which require API keys and cost money)
   pytest -v -m "not e2e"
   ```
   - **Any failures = STOP**: Fix issues before proceeding
   - **Expected**: ~50-100 tests, completes in <2 minutes
   - **Cost**: Free (no API calls)

3. **Run End-to-End Tutorial Tests**
   ```bash
   # Run e2e tests with verbose output to see execution progress
   pytest tests/e2e/ -v -s --e2e-verbose

   # Optional: See detailed LLM judge reasoning
   # pytest tests/e2e/ -v -s --e2e-verbose --judge-verbose
   ```
   - **Any failures = STOP**: These validate the core user experience
   - **Expected**: 2-3 tests, completes in 2-5 minutes
   - **Cost**: ~$0.10-$0.25 in API calls
   - **What it tests**:
     - Complete tutorial workflows (BPM analysis, etc.)
     - Project creation from templates
     - Multi-capability orchestration
     - End-user experience

4. **Verify All Tests Pass**
   - Unit & Integration tests: ✅
   - End-to-End tests: ✅
   - **PROCEED**: Continue to Step 1

5. **Fix Any Failing Tests**
   - If tests fail, fix issues first
   - Re-run tests until all pass
   - Commit fixes before proceeding

### **Step 1: Pre-Release Version Updates (CRITICAL)**

**⚠️ IMPORTANT**: Update all version numbers BEFORE creating the GitHub release/tag.

1. **Update Version Numbers** (see checklist below)
   - Update `pyproject.toml`, `src/osprey/__init__.py`, `src/osprey/cli/main.py`
   - Update `RELEASE_NOTES.md`, `CHANGELOG.md`, `README.md`
   - Verify documentation files

2. **Run Version Consistency Check**
   ```bash
   # Check all version references
   echo "=== VERSION CONSISTENCY CHECK ==="
   echo "pyproject.toml:        $(grep 'version = ' pyproject.toml)"
   echo "osprey/__init__.py: $(grep '__version__ = ' src/osprey/__init__.py)"
   echo "cli/main.py:          $(grep '__version__ = ' src/osprey/cli/main.py)"
   echo "RELEASE_NOTES.md:     $(head -1 RELEASE_NOTES.md)"
   echo "README.md:            $(grep 'Latest Release:' README.md)"
   echo "CHANGELOG.md:         $(grep -m1 '## \[' CHANGELOG.md)"
   ```

3. **Commit Version Updates**
   ```bash
   git add pyproject.toml src/osprey/__init__.py src/osprey/cli/main.py RELEASE_NOTES.md CHANGELOG.md README.md
   git commit -m "release: Bump version to 0.7.3"
   git push origin main
   ```

### **Step 2: Create GitHub Release**

```bash
# 1. Ensure you're on the correct branch (after version updates from Step 1)
git checkout main
git pull origin main

# 2. Create and push tag (use your next version)
git tag v0.7.3
git push origin v0.7.3

# 3. Create GitHub release (optional - can use web interface)
gh release create v0.7.3 \
  --title "Alpha Berkeley Framework v0.7.3 - [Brief Description]" \
  --notes-file RELEASE_NOTES.md
```

### **Step 3: Publish to PyPI**

**⚠️ IMPORTANT**: Only publish to PyPI after GitHub release is created and documentation is verified.

#### **Option A: Using twine (Recommended)**

```bash
# 1. Clean previous builds
rm -rf dist/ build/ src/*.egg-info/

# 2. Build the package
python -m build

# 3. Check the built package
twine check dist/*

# 4. Upload to PyPI (requires PyPI credentials)
twine upload dist/*

# Optional: Upload to test PyPI first for verification
# twine upload --repository testpypi dist/*
```

#### **Option B: Using GitHub Actions (Automated)**

If you have GitHub Actions set up for PyPI publishing:

1. **Tag Creation** automatically triggers PyPI publish workflow
2. **Verify GitHub Actions** completed successfully
3. **Check PyPI** - Package should appear at: `https://pypi.org/project/osprey-framework/0.7.3/`

## 🔧 Technical Implementation

### **Documentation Version Detection (Fixed)**

The documentation now uses this logic in `docs/source/conf.py`:

```python
def get_version_from_git():
    # 1. In GitHub Actions: Use GITHUB_REF for exact tag
    github_ref = os.environ.get('GITHUB_REF', '')
    if github_ref.startswith('refs/tags/v'):
        return github_ref.replace('refs/tags/v', '')

    # 2. Local builds: Use git describe
    result = subprocess.run(['git', 'describe', '--tags', '--abbrev=0'], ...)
    return result.stdout.strip().lstrip('v')
```

### **GitHub Actions Workflow**

The workflow triggers on:
- `push` to `main` branch (for development docs)
- `tags: v*` (for release docs with correct version)

## 🧪 Testing the Fix

### **Test Locally**
```bash
# Simulate GitHub Actions environment
export GITHUB_REF="refs/tags/v0.7.3"
cd docs
make clean html

# Check that version appears correctly in build output
grep -r "0.7.3" build/html/
```

## 📚 Version Update Checklist

Before creating a release, ensure these files have the correct version. **All version numbers must be updated BEFORE creating the GitHub release/tag.**

### 🔧 Core Package Files (CRITICAL)
- [ ] **`pyproject.toml`** - Line 7: `version = "0.7.3"`
- [ ] **`src/osprey/__init__.py`** - Line 15: `__version__ = "0.7.3"`
- [ ] **`src/osprey/cli/main.py`** - Line 20: `__version__ = "0.7.3"` (fallback version)

### 📝 Documentation & Release Notes
- [ ] **`RELEASE_NOTES.md`** - Line 1: `# Alpha Berkeley Framework - Latest Release (v0.7.3)`
- [ ] **`CHANGELOG.md`** - Add new section: `## [0.7.3] - 2025-MM-DD`
- [ ] **`README.md`** - Line 12: `**🎉 Latest Release: v0.7.3**`

### 📚 Documentation Files (Auto-detected via git tags, but verify)
- [ ] **`docs/source/conf.py`** - Version auto-detected from git tags (✅ Fixed)
- [ ] **Documentation RST files** - Update any hardcoded version references:
  - `docs/source/getting-started/migration-guide.rst`
  - `docs/source/getting-started/installation.rst`
  - `docs/source/getting-started/hello-world-tutorial.rst`
  - Any files with "New in v0.x.x" admonitions

## 🧪 E2E Test Details

End-to-end tests validate complete user workflows and are **mandatory** for releases but **optional** during development.

### Test Suite Overview

```bash
# Run just e2e smoke tests (fastest e2e validation)
pytest -v -m e2e_smoke

# Run all e2e tests
pytest -v -m e2e

# Run with real-time progress (recommended for releases)
pytest tests/e2e/ -v -s --e2e-verbose --judge-verbose
```

### Current E2E Test Coverage

| Test | Duration | What It Validates |
|------|----------|-------------------|
| `test_simple_query_smoke_test` | ~10-20s | Basic framework initialization and query processing |
| `test_bpm_timeseries_and_correlation_tutorial` | ~60-90s | Complete control assistant workflow: channel finding → archiver retrieval → Python plotting |

### Why E2E Tests Matter for Releases

- **User Experience Validation**: Tests exactly what users see in tutorials
- **Multi-Component Integration**: Validates orchestration across capabilities
- **Regression Detection**: Catches issues that unit tests miss
- **LLM Judge Evaluation**: Flexible validation that adapts to reasonable variations

### Cost & Performance

- **Total runtime**: ~2-5 minutes for full e2e suite
- **API cost**: ~$0.10-$0.25 per release
- **Value**: Prevents broken tutorials and user-facing bugs

See `tests/e2e/README.md` for complete documentation.

# Commit Organization Workflow

This guide helps you organize uncommitted Git changes into atomic, logical commits with corresponding CHANGELOG entries.

## 🎯 Problem & Solution

**Problem**: After development work, you have many uncommitted changes. Committing everything at once creates monolithic, unreviewable history.

**Solution**: Analyze changes, group them logically, create a commit strategy document, then execute systematically.

## 📋 Quick Start

```bash
# 1. Understand what changed
git status
git diff --stat
git diff

# 2. Follow this workflow to create COMMIT_STRATEGY.md

# 3. Review the strategy

# 4. Execute commits one by one with CHANGELOG entries
```

**Critical Checkpoints:**
- ✅ Understood purpose of every changed file?
- ✅ Commits atomic (single logical purpose)?
- ✅ Each commit has CHANGELOG entry?
- ✅ CHANGELOG entries concise and timeless (no emojis)?
- ✅ Commit strategy reviewable and clear?

## 🎯 Core Principles

### Atomic Commits
One commit = one logical change. Each commit should:
- Have a single, clear purpose
- Be understood independently
- Be revertable without breaking other features
- Pass all tests
- Include tests and docs for the change

### CHANGELOG Synchronization
Every user-visible change needs a CHANGELOG entry that is:
- **Timeless**: No emojis, no "TODO", no "WIP"
- **Professional**: No casual language
- **Concise**: Key points only, not implementation details
- **User-focused**: What changed from user's perspective
- **Categorized**: Added/Changed/Fixed/Removed/Deprecated

## 🔄 Workflow

### Step 1: Analyze All Changes

```bash
git diff --stat              # See all files with change statistics
git diff --name-only         # See all modified files
git diff                     # See detailed changes
git diff path/to/file.py    # View one file at a time
```

For each file, identify:
1. **What changed**: Technical modification
2. **Why it changed**: Purpose/reason
3. **Category**: Feature, fix, refactor, docs, config, test
4. **Dependencies**: Related to other changes?
5. **User impact**: Will users notice?

### Step 2: Group Into Logical Commits

**Grouping Principles:**
- **Feature-based**: All files for one feature (source + tests + docs + config)
- **Fix-based**: All files to fix one bug (source + regression test)
- **Refactor**: Pure refactors with no behavior change
- **Documentation**: Doc-only changes
- **Configuration**: Config changes for same feature

**Decision Tree:**
```
For each change:
├─ Complete feature? → Group all files together (source + tests + docs)
├─ Bug fix? → Group all files needed to fix this bug
├─ Refactor (no behavior change)? → Group related refactors
├─ Documentation only? → Group related doc changes
├─ Enables other changes? → Commit FIRST (dependencies)
└─ Independent changes? → Create separate commits
```

**Anti-patterns:**
- ❌ One commit per file (typically too granular)
- ❌ All changes in one commit (too coarse)
- ❌ Mixing unrelated features
- ❌ Mixing features with unrelated fixes
- ❌ Separating tests from code they test

### Step 3: Determine Commit Order

**Ordering Principles:**
1. Dependencies first (base functionality before dependent features)
2. Infrastructure before features (config/setup before code using it)
3. Fixes before enhancements
4. Breaking changes clearly marked
5. Tests with code (never commit broken tests)

### Step 4: Write CHANGELOG Entries

**Categories:**
- `### Added` - New features/capabilities
- `### Changed` - Changes to existing functionality
- `### Fixed` - Bug fixes
- `### Removed` - Removed features
- `### Deprecated` - Features marked for removal

**Format:**
```markdown
### [Category]
- **[Component]**: [Description]
  - [Optional sub-point 1]
  - [Optional sub-point 2]
```

**Length Guidelines:**
- **1 line**: Minor fixes/changes
  ```markdown
  ### Fixed
  - Error node logging: Removed duplicate logging messages
  ```

- **2-3 lines**: Standard features/changes
  ```markdown
  ### Added
  - Channel write capability: Direct value assignment with automatic boundary validation and approval integration
  ```

- **4-5 lines**: Major features (with sub-bullets)
  ```markdown
  ### Added
  - Runtime PV boundary checking: Comprehensive safety system for validating writes
    - Automatic interception of all caput/put calls
    - Failsafe design with configurable limits
    - Complete documentation and examples
  ```

**Include:**
- User-visible changes, API changes, behavior changes
- New features, bug fixes users notice
- Breaking changes, performance improvements

**Exclude:**
- Internal refactors with no user impact
- Test-only changes, minor cleanup
- Typo fixes in comments

### Step 5: Create Commit Strategy Document

Create `COMMIT_STRATEGY.md` in project root using template below.

### Step 6: Review Strategy

**Checklist:**
- ✅ Each commit atomic (single purpose)
- ✅ Correct order (dependencies respected)
- ✅ Each has CHANGELOG entry
- ✅ CHANGELOG entries professional and concise
- ✅ No mixed unrelated changes
- ✅ Clear commit messages
- ✅ File groupings make sense
- ✅ All changes accounted for

### Step 7: Execute Commits

**Critical**: Add CHANGELOG entry for EACH commit individually, right before staging files. DO NOT batch all entries at start!

For each commit:
1. Add CHANGELOG entry for THIS commit only
2. Stage files: `git add [files]`
3. Stage CHANGELOG: `git add CHANGELOG.md`
4. Verify: `git diff --cached --name-only`
5. Commit: `git commit -m "[message]"`
6. Verify: `git log -1 --stat`

## 📋 Commit Strategy Document Template

```markdown
# Commit Strategy - [Brief Description]

**Date**: [YYYY-MM-DD]
**Total Files Changed**: [N]
**Total Commits Planned**: [N]

## Overview

[2-3 sentence summary of all changes]

**Categories:**
- Features: [N], Fixes: [N], Refactors: [N], Docs: [N], Config: [N]

## File Inventory

- `path/to/file1.py` - [Brief description]
- `path/to/file2.py` - [Brief description]
[... all changed files]

## Commit Plan

### Commit 1: [Title]

**Type**: Feature|Fix|Refactor|Docs|Config

**Files**:
- `path/to/file1.py`
- `path/to/file2.py`

**CHANGELOG Entry** (`### Added|Changed|Fixed|Removed`):
```
### [Category]
- **[Component]**: [Description]
  - [Optional sub-points]
```

**Commit Message**:
```
[type]: [Short description]

[Optional longer explanation of why, what problem it solves,
relevant context or decisions made.]
```

**Dependencies**: None | Requires Commit N | Before Commit N

**Notes**: [Special considerations]

---

### Commit 2: [Title]
[... repeat for each commit]

## Pre-Execution Checklist

- [ ] All commits atomic
- [ ] Correct order (dependencies)
- [ ] Each has CHANGELOG entry
- [ ] CHANGELOG entries concise/professional
- [ ] Clear commit messages
- [ ] All files accounted for
- [ ] Tests with features/fixes

## Execution Plan

For each commit (in order):
1. Add CHANGELOG entry for THIS commit only
2. `git add [files]`
3. `git add CHANGELOG.md`
4. `git diff --cached --name-only` (verify)
5. `git commit -m "[message]"`
6. `git log -1 --stat` (verify)

**Critical**: Add CHANGELOG entries one at a time, not all at once!

## Post-Execution

- [ ] Verify commits: `git log --oneline`
- [ ] Verify CHANGELOG: `git diff origin/main CHANGELOG.md`
- [ ] Run tests
- [ ] Delete COMMIT_STRATEGY.md
- [ ] Push: `git push origin [branch]`
```

## 🔧 Common Patterns

### New Feature
```
Commit: Feature implementation
Files: source + tests + docs + config examples
CHANGELOG: ### Added - describe feature with key capabilities
Message: "feat: Add [feature] with [capability]"
```

### Bug Fix
```
Commit: Fix with test
Files: source fix + regression test + doc update (if behavior changed)
CHANGELOG: ### Fixed - what was broken and now works
Message: "fix: Correct [issue] in [component]"
```

### Refactoring
```
Commit: Related refactors
Files: refactored sources + updated tests
CHANGELOG: ### Changed (if user-visible) or omit (if internal)
Message: "refactor: Simplify [component] by [approach]"
```

### Breaking Change
```
Commit: All changes for breaking change
Files: updated source + tests + docs + migration guide
CHANGELOG: ### Changed with migration path
Message: "refactor!: [change] BREAKING CHANGE: [description]"
```

### Multiple Independent Features
```
Commit 1: Feature A (code + tests + docs)
Commit 2: Feature B (code + tests + docs)
Commit 3: Feature C (code + tests + docs)
CHANGELOG: Each adds own entry under ### Added
```

### Mixed Fixes and Features
```
Commit 1: Bug fix 1 (fix + test)
Commit 2: Bug fix 2 (fix + test)
Commit 3: Feature 1 (code + tests + docs)
Commit 4: Feature 2 (code + tests + docs)
CHANGELOG: Fixes under ### Fixed, features under ### Added
Rationale: Fixes first allows cherry-picking without pulling features
```

## ⚠️ Edge Cases

### File Modified for Multiple Reasons
Use `git add -p [file]` to stage hunks interactively:
```bash
git add -p src/file.py     # Select hunks for Commit 1
git commit -m "feat: Feature A"
git add -p src/file.py     # Select remaining hunks for Commit 2
git commit -m "fix: Fix B"
```

### Dependent Changes
Always commit dependencies first. Document in strategy.

### Large File with Minor Changes
Include entire file, mention localization in commit message.

### CHANGELOG Has Existing Unreleased Entries
Add new entries to appropriate categories, maintain chronological order, don't modify existing.

### Uncertain About Change Purpose
1. `git diff [file]` for exact changes
2. `git log -p [file]` for history
3. Search codebase for references
4. Group with related files if still unclear

### Generated/Auto-formatted Files
- Formatting only → Separate formatting commit
- Generated from source → Commit with source
- Both → Split into formatting + feature commits

## 📚 Examples

### Example 1: Single Feature

**Changes:**
- `src/capabilities/channel_write.py` (new, implementation)
- `src/capabilities/__init__.py` (register capability)
- `tests/capabilities/test_channel_write.py` (new, tests)
- `docs/source/capabilities/channel_write.rst` (new, docs)

**Strategy: Single atomic commit**

```markdown
### Commit 1: Add channel write capability

**Files**: All 4 files above

**CHANGELOG**:
### Added
- Channel write capability: Direct value assignment to control system channels
  - Automatic boundary validation and approval workflow integration
  - Clear separation from Python capability for safety

**Message**:
feat: Add channel write capability for direct PV writes

Implements dedicated capability for writing values to control system
channels with clear separation from Python capability. Includes
automatic boundary checking and approval workflow.
```

### Example 2: Multiple Fixes

**Changes:**
- `src/core/gateway.py` + `tests/core/test_gateway.py` (approval fix)
- `src/infrastructure/error_node.py` + `tests/infrastructure/test_error_node.py` (logging fix)
- `src/cli/main.py` + `tests/cli/test_main.py` (parsing fix)

**Strategy: Three separate commits**

```markdown
### Commit 1: Fix gateway approval detection
Files: gateway.py + test_gateway.py
CHANGELOG: ### Fixed - Gateway approval detection: Enhanced pattern matching
Message: "fix: Improve gateway approval detection"

### Commit 2: Fix error node logging
Files: error_node.py + test_error_node.py
CHANGELOG: ### Fixed - Error node logging: Removed duplicate messages
Message: "fix: Remove duplicate logging in error node"

### Commit 3: Fix CLI parsing
Files: main.py + test_main.py
CHANGELOG: ### Fixed - CLI command parsing: Handle quoted arguments
Message: "fix: Handle quoted arguments in CLI"
```

### Example 3: Feature with Prerequisite Refactor

**Changes:**
- `src/core/base.py` (refactored base class)
- `src/core/feature.py` (new feature using base)
- `tests/core/test_base.py` + `tests/core/test_feature.py` (tests)
- `docs/source/api/feature.rst` (docs)

**Strategy: Two commits (refactor first, then feature)**

```markdown
### Commit 1: Refactor base class
Files: base.py + test_base.py
CHANGELOG: ### Changed - Core base class: Refactored for plugin support
Message: "refactor: Extract plugin interface from base class"
Dependencies: Must come before Commit 2

### Commit 2: Add plugin feature
Files: feature.py + test_feature.py + feature.rst
CHANGELOG: ### Added - Plugin system: Extensible architecture for custom capabilities
Message: "feat: Add plugin feature system"
Dependencies: Requires Commit 1
```

## 🎯 Golden Rules

1. **Understand first**: Analyze all changes thoroughly before planning
2. **One purpose per commit**: Single, clear logical purpose
3. **Group by function**: Related files for one feature go together
4. **Order matters**: Dependencies first, features later
5. **CHANGELOG mandatory**: Every user-visible change needs entry
6. **CHANGELOG timeless**: Professional, concise, no emojis
7. **One entry per commit**: Add right before staging for that commit
8. **Document before executing**: Create complete strategy for review
9. **Tests with code**: Never separate tests from code they test
10. **When in doubt, split**: Make separate commits if unsure

---

**Goal**: Clear, reviewable commit history where each commit is a focused, purposeful, complete chapter in your codebase's story.

=====================
Claude Code Generator
=====================

The Claude Code Generator provides advanced code generation through the Claude Code SDK with multi-turn agentic reasoning, codebase learning, and configurable quality profiles.

.. warning::

   **Optional Dependency**

   Requires Claude Agent SDK:

   .. code-block:: bash

      pip install osprey-framework[claude-agent]

   **API Configuration:**

   Choose ONE of the following based on your setup:

   **Direct Anthropic API** (default):

   .. code-block:: bash

      export ANTHROPIC_API_KEY='your-api-key-here'

   **CBORG (Lawrence Berkeley Lab)**:

   .. code-block:: bash

      export CBORG_API_KEY='your-cborg-key-here'

   Then configure API settings in ``claude_generator_config.yml`` (see Configuration section).

Overview
========

Unlike traditional single-pass LLM generators, Claude Code can:

- **Read your codebase** to learn from successful examples
- **Execute multi-phase workflows** (scan → plan → generate)
- **Iterate intelligently** with multi-turn reasoning
- **Balance quality and speed** through profiles

**Architecture:**

.. code-block:: text

   Direct Mode (Fast):
   User Request → Claude Code → Python Code

   Phased Mode (High Quality):
   Phase 1: SCAN     → Find examples, identify patterns
   Phase 2: PLAN     → Create implementation plan
   Phase 3: GENERATE → Write Python code following plan

**When to Use:**

- Complex code generation requiring multi-step reasoning
- Learning from successful code examples in your codebase
- Quality-critical scenarios (safety systems, scientific computing)
- When longer generation time is acceptable for better results

Quick Start
===========

Minimal Configuration
---------------------

Use with a profile selection:

.. code-block:: yaml

   # config.yml
   osprey:
     execution:
       code_generator: "claude_code"
       generators:
         claude_code:
           profile: "balanced"  # fast | balanced | robust

Full Configuration
------------------

For advanced usage, create ``claude_generator_config.yml``:

.. code-block:: yaml

   # API Configuration (choose one)
   # Option 1: Direct Anthropic API (default)
   api_config:
     provider: "anthropic"

   # Option 2: CBORG (Lawrence Berkeley Lab)
   # api_config:
   #   provider: "cborg"
   #   base_url: "https://api.cborg.lbl.gov"
   #   disable_non_essential_model_calls: true
   #   disable_telemetry: true
   #   max_output_tokens: 8192

   profiles:
     balanced:
       workflow_mode: "sequential"
       model: "sonnet"
       max_turns: 5
       max_budget_usd: 0.25
       allow_codebase_reading: true

   codebase_guidance:
     epics:
       directories:
         - "successful_scripts/epics/"
       guidance: |
         EPICS best practices from examples

     plotting:
       directories:
         - "successful_scripts/plotting/"
       guidance: |
         Matplotlib conventions

   workflows:
     phased:
       phases:
         scan:
           tools: ["Read", "Grep", "Glob"]
           model: "anthropic/claude-haiku"
           max_turns: 3
         plan:
           tools: ["Read"]
           model: "anthropic/claude-haiku"
           max_turns: 2
         generate:
           tools: []
           model: "anthropic/claude-haiku"
           max_turns: 2

Reference it in your main config:

.. code-block:: yaml

   osprey:
     execution:
       code_generator: "claude_code"
       generators:
         claude_code:
           profile: "balanced"
           claude_config_path: "claude_generator_config.yml"

API Configuration
=================

The Claude Code Generator supports multiple API providers through explicit configuration. This provides better control, portability, and clarity compared to relying on system environment variables.

Direct Anthropic API (Default)
-------------------------------

Use this configuration if you have direct access to Anthropic's API.

**Setup:**

1. Obtain an API key from https://console.anthropic.com/

2. Set environment variable:

   .. code-block:: bash

      export ANTHROPIC_API_KEY='your-api-key-here'

3. Configure in ``claude_generator_config.yml``:

   .. code-block:: yaml

      api_config:
        provider: "anthropic"

**Advantages:**

- Direct access to latest Anthropic models and features
- No proxy overhead
- Full control over API keys and billing

CBORG (Lawrence Berkeley Lab)
------------------------------

Use this configuration if you're at Lawrence Berkeley National Lab and want to route through CBORG's model gateway.

**Setup:**

1. Obtain a CBORG API key from Science IT

2. Set environment variable:

   .. code-block:: bash

      export CBORG_API_KEY='your-cborg-key-here'

3. Configure in ``claude_generator_config.yml``:

   .. code-block:: yaml

      api_config:
        provider: "cborg"
        base_url: "https://api.cborg.lbl.gov"

        # Recommended CBORG-specific settings
        disable_non_essential_model_calls: true
        disable_telemetry: true
        max_output_tokens: 8192  # Reduces throttling

**Advantages:**

- Centralized billing through LBL accounts
- Access to both Anthropic and LBL-hosted models
- Network routing optimized for LBL infrastructure

**Model Names:**

When using CBORG, the generator automatically uses proper model names:

- ``sonnet`` → ``claude-sonnet-4-5`` (not ``claude-sonnet-4-5-20250929``)
- ``haiku`` → ``claude-haiku-4-5`` (not ``claude-haiku-4-5-20251001``)
- ``opus`` → ``claude-opus-4``

This ensures compatibility with CBORG's routing and correct cost calculation.

**CBORG-Specific Options:**

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Option
     - Description
   * - ``disable_non_essential_model_calls``
     - Reduces API calls for minor tasks (recommended)
   * - ``disable_telemetry``
     - Disables telemetry reporting (recommended)
   * - ``max_output_tokens``
     - Maximum tokens per response (8192 recommended to reduce throttling)

Configuration Comparison
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Aspect
     - Direct Anthropic
     - CBORG
   * - **API Key**
     - ``ANTHROPIC_API_KEY``
     - ``CBORG_API_KEY``
   * - **Base URL**
     - Default (api.anthropic.com)
     - https://api.cborg.lbl.gov
   * - **Model Names**
     - Standard Claude names
     - Standard Claude names (auto-configured)
   * - **Billing**
     - Direct Anthropic billing
     - LBL project recharge
   * - **Setup Complexity**
     - Simple
     - Requires LBL account

Why Explicit Configuration?
----------------------------

The generator uses **explicit configuration** in ``claude_generator_config.yml`` rather than relying solely on environment variables for several reasons:

1. **Portability**: Configuration travels with the project
2. **Clarity**: API setup is documented in configuration file
3. **Version Control**: Team members see the required configuration
4. **Flexibility**: Easy to switch between providers
5. **Isolation**: Different projects can use different providers

The generator builds environment variables internally from the configuration, ensuring Claude Code CLI receives the correct settings regardless of your shell environment.

Quality Profiles
================

Fast Profile
------------

**Quick one-pass generation**

.. code-block:: yaml

   profile: "fast"

**Characteristics:**

- Speed: Fast
- Model: Claude Haiku
- Workflow: Direct (one-pass)
- Codebase Reading: Disabled

**Best For:** Development, simple tasks, rapid iteration

**Tradeoffs:** No codebase learning, less structured approach

Robust Profile (DEFAULT)
-------------------------

**Structured workflow with codebase learning**

.. code-block:: yaml

   profile: "robust"

**Characteristics:**

- Speed: Moderate
- Model: Claude Haiku (Standard)
- Workflow: Phased (3-phase: scan → plan → generate)
- Codebase Reading: Enabled

**Best For:** Production use, learning from examples, structured code generation

**Tradeoffs:** Slightly slower than fast profile due to 3-phase workflow

Profile Comparison Table
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 20 20 40

   * - Profile
     - Speed
     - Workflow
     - Best Use Case
   * - **Fast**
     - Fast (~5s)
     - Direct (one-pass)
     - Development, simple tasks, rapid iteration
   * - **Robust**
     - Moderate (~15s)
     - Phased (scan → plan → generate)
     - Production, learning from examples (DEFAULT)

Workflow Modes
==============

Direct Mode
-----------

**Fast, one-pass code generation**

Generates code in a single agentic conversation. Claude can still read files,
search code, and iterate, but everything happens in one pass without explicit phases.

**Configuration:**

.. code-block:: yaml

   profiles:
     custom:
       workflow_mode: "direct"
       model: "anthropic/claude-haiku"
       max_turns: 2
       max_budget_usd: 0.05

**Workflow:**

.. code-block:: text

   User Request + Context → Claude Code → Generated Python Code
   (Claude can read files and iterate during this single conversation)

**Advantages:** Fastest generation, simple, still allows codebase reading if enabled

**Disadvantages:** Less structured approach for complex tasks

**When to Use:** Simple tasks, development, fast iteration

Phased Mode
-----------

**High-quality multi-phase workflow**

Executes a 3-phase workflow for comprehensive code generation.

**Configuration:**

.. code-block:: yaml

   profiles:
     custom:
       workflow_mode: "phased"
       model: "anthropic/claude-haiku"
       max_turns: 5
       max_budget_usd: 0.25
       allow_codebase_reading: true

**Workflow:**

.. code-block:: text

   Phase 1: SCAN
   ├─ Search codebase for relevant examples
   ├─ Identify patterns and best practices
   └─ Note libraries and approaches

   Phase 2: PLAN
   ├─ Create detailed implementation plan
   ├─ Define data structures and functions
   └─ Plan error handling

   Phase 3: GENERATE
   ├─ Write Python code following plan
   ├─ Include all imports and error handling
   └─ Store results in 'results' dictionary

**Advantages:** Highest quality, learns from examples, sophisticated reasoning

**Disadvantages:** Higher API usage, slower generation

**When to Use:** Complex tasks, quality-critical scenarios, when generation time is acceptable

Codebase Reading
================

Claude Code can **read your codebase** to learn from successful examples.

Configuration
-------------

Define example libraries with directories and guidance. **ALL libraries are always
provided to Claude** - it determines what's relevant for each task.

.. code-block:: yaml

   codebase_guidance:
     epics:
       directories:
         - "successful_scripts/epics/"
       guidance: |
         EPICS channel access best practices:
         - Use pyepics library for PV operations
         - Handle timeouts and connection states
         - Use caget/caput for simple operations

     plotting:
       directories:
         - "successful_scripts/plotting/"
       guidance: |
         Matplotlib conventions:
         - Create figures with tight_layout()
         - Save with dpi=300 for quality
         - Clear axis labels and titles

     data_analysis:
       directories:
         - "successful_scripts/analysis/"
       guidance: |
         Pandas and numpy patterns:
         - Efficient data manipulation
         - Statistical best practices

**How it works:**

1. **Directories** → Claude can search these paths (via Read/Grep/Glob tools)
2. **Guidance** → Appended to system prompt, tells Claude what patterns to look for
3. **Always active** → ALL libraries are included, Claude picks what's relevant

**Security:**

Codebase reading is **read-only** by design:

- Layer 1: SDK ``allowed_tools`` only includes Read/Grep/Glob
- Layer 2: SDK ``disallowed_tools`` blocks Write/Edit/Delete/Bash/Python
- Layer 3: PreToolUse safety hook actively blocks dangerous operations

Benefits
--------

Instead of generating code from scratch, Claude Code:

1. Finds similar implementations in your codebase
2. Identifies patterns and conventions
3. Uses the same libraries and approaches
4. Matches your code style

**Result:** Generated code that fits naturally into your codebase.

**Example Workflow:**

.. code-block:: text

   User: "Retrieve EPICS PV data and create time series plot"

   SCAN:  Finds read_beam_data.py → Uses pyepics, handles timeouts
          Finds time_series.py → Uses matplotlib, saves with dpi=300

   PLAN:  Use pyepics like examples, handle timeouts, create plot

   GENERATE: Generated code follows discovered patterns!

Setting Up Examples
-------------------

Create a directory structure:

.. code-block:: bash

   mkdir -p successful_scripts/{epics,plotting,analysis}

Add well-documented examples:

.. code-block:: python

   # successful_scripts/epics/read_pv_example.py
   """
   Example: Reading EPICS PV values with error handling.
   Standard pattern for EPICS operations.
   """
   from epics import caget

   def read_pv_with_timeout(pv_name, timeout=5.0):
       """Read PV value with timeout handling."""
       try:
           value = caget(pv_name, timeout=timeout)
           if value is None:
               raise ValueError(f"Failed to read PV: {pv_name}")
           return value
       except Exception as e:
           print(f"Error reading {pv_name}: {e}")
           return None

   beam_current = read_pv_with_timeout('BEAM:CURRENT')
   results = {'beam_current': beam_current}

Claude Code will find and learn from this!

Complete Configuration Template
================================

.. code-block:: yaml

   # claude_generator_config.yml

   # API Configuration
   api_config:
     provider: "cborg"  # or "anthropic" for direct access
     base_url: "https://api.cborg.lbl.gov"

   profiles:
     fast:
       workflow_mode: "direct"
       model: "anthropic/claude-haiku"
       max_turns: 2
       max_budget_usd: 0.05
       allow_codebase_reading: false

     robust:
       workflow_mode: "phased"
       model: "anthropic/claude-haiku"
       max_turns: 5
       max_budget_usd: 0.25
       allow_codebase_reading: true

   codebase_guidance:
     epics:
       directories:
         - "successful_scripts/epics/"
       guidance: |
         EPICS best practices:
         - Use pyepics library
         - Handle timeouts properly

     plotting:
       directories:
         - "successful_scripts/plotting/"
       guidance: |
         Matplotlib conventions:
         - tight_layout(), dpi=300

   workflows:
     phased:
       phases:
         scan:
           prompt: |
             Search codebase for relevant examples.
             Identify libraries, functions, and best practices.
           tools: ["Read", "Grep", "Glob"]
           model: "anthropic/claude-haiku"
           max_turns: 3

         plan:
           prompt: |
             Create detailed implementation plan:
             - Imports, approach, data structures
             - Key functions, results structure
             - Error handling
           tools: ["Read"]
           model: "anthropic/claude-haiku"
           max_turns: 2

         generate:
           prompt: |
             Generate Python code following the plan.
             - Include ALL imports
             - Store results in 'results' dictionary
             - Add comments, handle errors
           tools: []
           model: "anthropic/claude-haiku"
           max_turns: 2

   cost_controls:
     max_budget_per_session: 5.00
     warn_threshold: 0.50

   safety:
     blocked_tools: [Write, Edit, Delete, Bash, Python]
     max_code_size: 50000

Configuration Options
---------------------

**Profile Settings:**

- ``workflow_mode``: "direct" or "phased"
- ``model``: Model name (e.g., "anthropic/claude-haiku" for CBORG)
- ``max_turns``: Maximum multi-turn iterations
- ``max_budget_usd``: Per-generation cost limit
- ``allow_codebase_reading``: Enable/disable codebase access

**Phase Settings:**

- ``tools``: Available tools (Read/Grep/Glob or empty)
- ``model``: Model to use
- ``max_turns``: Maximum turns
- ``prompt``: Instructions for phase

Usage Examples
==============

Basic Usage
-----------

.. code-block:: python

   from osprey.services.python_executor.generation import ClaudeCodeGenerator
   from osprey.services.python_executor.models import PythonExecutionRequest

   generator = ClaudeCodeGenerator()

   request = PythonExecutionRequest(
       user_query="Calculate mean and standard deviation",
       task_objective="Compute basic statistics",
       execution_folder_name="stats",
       expected_results={"mean": "float", "std": "float"}
   )

   code = await generator.generate_code(request, [])

With Custom Profile
-------------------

.. code-block:: python

   # Fast profile for development
   generator = ClaudeCodeGenerator({"profile": "fast"})

   # Robust profile for critical tasks
   generator = ClaudeCodeGenerator({"profile": "robust"})

With Context and Guidance
--------------------------

.. code-block:: python

   request = PythonExecutionRequest(
       user_query="Process EPICS PV data and create time series plot",
       task_objective="Visualize accelerator data",
       execution_folder_name="epics_viz",

       capability_context_data={
           "pv_names": ["BEAM:CURRENT", "BEAM:ENERGY"],
           "time_range": "last 1 hour"
       },

       capability_prompts=[
           "Use pyepics for channel access",
           "Handle connection timeouts gracefully",
           "Create matplotlib plot with labels",
           "Save plot to execution folder"
       ],

       expected_results={
           "plot_path": "str",
           "statistics": "dict",
           "pv_values": "list"
       }
   )

   code = await generator.generate_code(request, [])

With Error Feedback
-------------------

.. code-block:: python

   # First attempt
   code_v1 = await generator.generate_code(request, [])

   # Retry with error feedback
   error_chain = ["NameError: name 'pd' is not defined"]
   code_v2 = await generator.generate_code(request, error_chain)
   # Should now include 'import pandas as pd'

Performance Characteristics
============================

.. list-table::
   :header-rows: 1
   :widths: 25 25 25 25

   * - Metric
     - Fast
     - Balanced
     - Robust
   * - **Generation Time**
     - Fast
     - Moderate
     - Slower
   * - **API Usage**
     - Low
     - Medium
     - High
   * - **Token Usage**
     - Lower
     - Medium
     - Higher

Optimization Strategies
-----------------------------

1. **Use Fast Profile for Development**

   .. code-block:: yaml

      generators:
        claude_code:
          profile: "fast"

2. **Limit Example Libraries**

   Only include the most relevant libraries for your use case:

   .. code-block:: yaml

      codebase_guidance:
        plotting:
          directories: ["successful_scripts/plotting/"]
          guidance: "Matplotlib patterns"

3. **Use Conditional Selection**

   .. code-block:: python

      generator = "basic" if simple_task else "claude_code"

4. **Profile by Use Case**

   - Development/Testing: Fast
   - Production: Robust (default)

Safety Model
============

Claude Code is **read-only** with multiple protection layers:

**Layer 1: SDK Configuration**

.. code-block:: python

   ClaudeAgentOptions(
       allowed_tools=["Read", "Grep", "Glob"],
       disallowed_tools=["Write", "Edit", "Delete", "Bash", "Python"]
   )

**Layer 2: PreToolUse Safety Hook**

Active runtime protection that blocks dangerous operations:

.. code-block:: python

   if tool_name in ["Write", "Edit", "Delete", "Bash", "Python"]:
       logger.warning(f"BLOCKED {tool_name}")
       return {"permissionDecision": "deny"}

**Layer 3: Existing Pipeline Security**

All code still goes through:

1. Static analysis
2. Approval system
3. Container isolation

**Defense in Depth**: Multiple independent layers ensure safety.

Best Practices
==============

Development
-----------

1. **Start with Fast Profile**
2. **Iterate Quickly** - Use direct mode for iteration, phased for final quality
3. **Build Example Library Gradually**

Production
----------

1. **Use Robust Profile** (default) - Structured workflow with codebase learning
2. **Monitor API Usage** - Track generation patterns
3. **Maintain Example Library** - Improve generation quality over time
4. **Enable Approval** - Require human review for critical code

Troubleshooting
===============

Installation
------------

**ImportError:**

.. code-block:: bash

   pip install osprey-framework[claude-agent]

**API key not found:**

.. code-block:: bash

   export ANTHROPIC_API_KEY='your-key'

Configuration
-------------

**Profile not found:**

Check profile name matches exactly in ``claude_generator_config.yml``.

**Phased workflow not working:**

Add workflow definition with all three phases (scan, plan, generate).

Generation Issues
-----------------

**Timeout:** Increase timeout, use faster profile, limit codebase directories

**High API usage:** Use fast profile, use legacy for simple tasks

**Code doesn't follow examples:** Verify directories exist, check ``allow_codebase_reading: true``

Quality Issues
--------------

**Low quality:** Use balanced/robust profile, enable sequential workflow, add better examples

**Missing imports:** Add examples with imports, include guidance in capability_prompts

Performance Issues
------------------

**Too slow:** Use fast profile, direct mode, disable codebase reading

**Too many API calls:** Reduce max_turns, use direct mode, set stricter budgets

See Also
========

:doc:`service-overview`
    Complete service documentation

:doc:`generator-basic`
    Basic LLM generator for simple setups

:doc:`generator-mock`
    Testing with mock generator

:doc:`index`
    Python Execution Service documentation

`Claude Agent SDK <https://github.com/anthropics/claude-agent-sdk>`_
    Official SDK documentation


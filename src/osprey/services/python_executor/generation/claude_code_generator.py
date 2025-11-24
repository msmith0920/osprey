"""Claude Code SDK-based code generator with advanced capabilities.

This module implements a sophisticated code generator that leverages the Claude Code SDK
to provide multi-turn agentic reasoning for complex code generation tasks. Unlike simpler
LLM-based generators, Claude Code can:

- **Read the codebase** to learn from successful examples
- **Execute multi-phase workflows** (scan → plan → generate)
- **Iterate intelligently** with reasoning and self-correction
- **Balance quality and speed** through configurable profiles

The generator integrates seamlessly into Osprey's Python executor pipeline, providing
enhanced code generation while maintaining all existing security and approval workflows.

Architecture:
    The generator supports two workflow modes:

    1. **Direct Mode** (fast):
       User Request → Claude Code → Python Code

    2. **Phased Mode** (high quality):
       Phase 1: SCAN (find relevant examples, identify patterns)
       Phase 2: PLAN (create implementation plan)
       Phase 3: GENERATE (write Python code following plan)

Configuration:
    The generator can be configured via config.yml or a separate configuration file:

    Minimal (config.yml)::

        osprey:
          execution:
            code_generator: "claude_code"
            generators:
              claude_code:
                profile: "balanced"  # fast | balanced | robust

    Full (claude_generator_config.yml)::

        profiles:
          fast:
            workflow_mode: "direct"
            model: "anthropic/claude-haiku"
            max_turns: 2
            max_budget_usd: 0.05
          balanced:
            workflow_mode: "phased"
            model: "anthropic/claude-haiku"
            max_turns: 5
            max_budget_usd: 0.25

Safety:
    The generator is read-only by design with multiple security layers:

    - **Layer 0: Directory Isolation (CRITICAL)**
      Claude Code runs in an isolated temporary directory with example scripts copied in.
      The `cwd` is set to /tmp/osprey_claude_code_restricted/ (which contains only
      examples, no project files). This prevents Claude from accessing your project
      workspace, config files, secrets, or source code.

    - **Layer 1: Tool Restrictions**
      allowed_tools only includes Read/Grep/Glob (no Write/Edit/Delete/Bash/Python)

    - **Layer 2: Runtime Hooks**
      PreToolUse hooks actively block any dangerous operations that bypass Layer 1

    - **Layer 3: Pipeline Security**
      All existing executor security analysis and approval workflows remain unchanged

.. note::
   Requires claude-agent-sdk package. Install with:
   pip install osprey-framework[claude-agent]

.. seealso::
   :class:`osprey.services.python_executor.generation.interface.CodeGenerator`
   :class:`osprey.services.python_executor.generation.basic_generator.BasicLLMCodeGenerator`

Examples:
    Using Claude Code generator with default profile::

        >>> generator = ClaudeCodeGenerator()
        >>> request = PythonExecutionRequest(
        ...     user_query="Calculate mean of data",
        ...     task_objective="Statistical calculation",
        ...     execution_folder_name="analysis"
        ... )
        >>> code = await generator.generate_code(request, [])

    Using fast profile for development::

        >>> generator = ClaudeCodeGenerator({"profile": "fast"})
        >>> code = await generator.generate_code(request, [])

    Using balanced profile (default)::

        >>> generator = ClaudeCodeGenerator({"profile": "balanced"})
        >>> code = await generator.generate_code(request, [])
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from osprey.utils.logger import get_logger

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ClaudeSDKError,
        CLIConnectionError,
        HookContext,
        HookInput,
        HookJSONOutput,
        HookMatcher,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
        query,
    )

    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    # Stub out imports for when SDK is not available
    ClaudeAgentOptions = dict  # type: ignore
    ClaudeSDKClient = object  # type: ignore
    HookInput = dict  # type: ignore
    HookJSONOutput = dict  # type: ignore
    HookContext = dict  # type: ignore
    AssistantMessage = object  # type: ignore
    ResultMessage = object  # type: ignore
    SystemMessage = object  # type: ignore
    TextBlock = object  # type: ignore
    ThinkingBlock = object  # type: ignore
    ToolResultBlock = object  # type: ignore
    ToolUseBlock = object  # type: ignore
    UserMessage = object  # type: ignore
    HookMatcher = object  # type: ignore
    ClaudeSDKError = Exception  # type: ignore
    CLIConnectionError = Exception  # type: ignore
    query = None  # type: ignore

from ..exceptions import CodeGenerationError
from ..models import ExecutionError, PythonExecutionRequest

logger = get_logger("claude_code_generator")

# Try to import LangGraph's stream writer (optional - graceful degradation)
try:
    from langgraph.config import get_stream_writer

    LANGGRAPH_STREAMING_AVAILABLE = True
except ImportError:
    LANGGRAPH_STREAMING_AVAILABLE = False
    get_stream_writer = None  # type: ignore


class ClaudeCodeGenerator:
    """Claude Code SDK-based code generator.

    Provides advanced code generation capabilities through the Claude Code SDK,
    supporting multiple workflow modes and quality profiles.

    Workflow Modes:
        - direct: Fast, one-pass code generation
        - phased: 3-phase workflow (scan → plan → generate)

    Quality Profiles:
        - fast: Quick generation for development (Haiku 4.5, ~5s)
        - balanced: DEFAULT - Good quality with reasonable latency (Sonnet 4.5, ~15s)

    Configuration:
        The generator reads configuration from either inline model_config or
        an external YAML file. See module docstring for configuration examples.

    Safety:
        Read-only by design with multiple protection layers:
        - allowed_tools limited to Read/Grep/Glob
        - disallowed_tools includes Write/Edit/Delete/Bash/Python
        - PreToolUse safety hook for runtime protection

    Args:
        model_config: Configuration dictionary with profile and settings

    Raises:
        ImportError: If claude-agent-sdk is not installed

    .. note::
       The generator only generates code. All security analysis, approval
       workflows, and execution remain unchanged in the executor pipeline.

    .. seealso::
       :class:`osprey.services.python_executor.generation.interface.CodeGenerator`
       :class:`osprey.services.python_executor.models.PythonExecutionRequest`

    Examples:
        Creating generator with default settings::

            >>> generator = ClaudeCodeGenerator()
            >>> # Uses balanced profile from config or defaults

        Creating generator with inline configuration::

            >>> config = {
            ...     "profile": "fast",
            ...     "workflow_mode": "direct",
            ...     "max_budget_usd": 0.10
            ... }
            >>> generator = ClaudeCodeGenerator(model_config=config)

        Creating generator with external config file::

            >>> config = {
            ...     "claude_config_path": "claude_generator_config.yml",
            ...     "profile": "robust"
            ... }
            >>> generator = ClaudeCodeGenerator(model_config=config)
    """

    def __init__(self, model_config: dict[str, Any] | None = None):
        """Initialize Claude Code generator with configuration.

        Args:
            model_config: Optional configuration dictionary. If None, uses defaults.

        Raises:
            ImportError: If Claude Agent SDK is not installed

        .. note::
           Configuration is loaded from either an external YAML file (if specified
           via claude_config_path) or from inline model_config values.
        """
        if not CLAUDE_SDK_AVAILABLE:
            raise ImportError(
                "Claude Agent SDK not installed. "
                "Install with: pip install osprey-framework[claude-agent]"
            )

        self.model_config = model_config or {}

        # Load Claude-specific configuration
        self.config = self._load_claude_config()

        # Track generation metadata for LangGraph state
        self.generation_metadata: dict[str, Any] = {
            "thinking_blocks": [],
            "tool_uses": [],
            "total_thinking_tokens": 0,
        }

        # Stream writer (set during generation if available)
        self._stream_writer = None

        # Save prompts: save all prompts and responses for transparency
        self._save_prompts = self.config.get("save_prompts", False)
        self._prompt_data: dict[str, Any] = {}  # Stores prompts/responses for inspection
        self._execution_folder: Path | None = None  # Set during generation

        # Compact initialization logging
        save_prompts_indicator = " [SAVE_PROMPTS]" if self._save_prompts else ""
        logger.info(
            f"Claude Code: {self.config.get('profile', 'balanced')} profile, "
            f"{self.config.get('workflow_mode', 'sequential')} mode{save_prompts_indicator}"
        )

    def _load_claude_config(self) -> dict[str, Any]:
        """Load Claude configuration from YAML file or model_config.

        Supports two configuration approaches:
        1. External YAML file (specified via claude_config_path)
        2. Inline configuration (directly in model_config)

        External configuration enables sophisticated multi-profile setups,
        while inline configuration is simpler for basic use cases.

        Returns:
            Configuration dictionary with all required settings

        .. note::
           External YAML config takes precedence if specified. Falls back
           to inline configuration if file doesn't exist or isn't specified.
        """
        # Check for separate config file
        config_path = self.model_config.get("claude_config_path", "claude_generator_config.yml")

        if Path(config_path).exists():
            import yaml

            logger.info(f"Loading Claude config from {config_path}")

            with open(config_path) as f:
                full_config = yaml.safe_load(f)

            # Get profile
            profile_name = self.model_config.get("profile", "balanced")
            if profile_name not in full_config.get("profiles", {}):
                logger.warning(f"Profile '{profile_name}' not found, using 'balanced'")
                profile_name = "balanced"

            profile = full_config["profiles"][profile_name]

            # Merge profile with full config
            # Get base phases and apply profile-specific model overrides
            phases = full_config.get("phases", {})
            phases = self._apply_profile_model_overrides(phases, profile)

            return {
                "profile": profile_name,
                "workflow_mode": profile.get("workflow_mode", "phased"),
                "planning_mode": profile.get("planning_mode", "generator_driven"),
                "model": profile.get("model", "sonnet"),
                "max_turns": profile.get("max_turns", 5),
                "max_budget_usd": profile.get("max_budget_usd", 0.50),
                "save_prompts": profile.get("save_prompts", True),  # Default to True for transparency
                "codebase_dirs": self._get_codebase_dirs(full_config, profile),
                "codebase_guidance": full_config.get("codebase_guidance", {}),
                "phases": phases,
                "planning_modes": full_config.get("planning_modes", {}),
                "workflows": full_config.get("workflows", {}),
                "api_config": full_config.get("api_config", {}),
            }
        else:
            # Inline configuration
            logger.info("Using inline configuration (no separate config file)")
            return {
                "profile": self.model_config.get("profile", "balanced"),
                "workflow_mode": self.model_config.get("workflow_mode", "direct"),
                "model": self.model_config.get("model", "sonnet"),
                "max_turns": self.model_config.get("max_turns", 5),
                "max_budget_usd": self.model_config.get("max_budget_usd", 0.50),
                "save_prompts": self.model_config.get("save_prompts", True),  # Default to True for transparency
                "codebase_dirs": [],
                "codebase_guidance": {},
                "workflows": {},
                "api_config": self.model_config.get("api_config", {}),
            }

    def _apply_profile_model_overrides(self, phases: dict, profile: dict) -> dict:
        """Apply profile-specific model overrides to phase definitions.

        Profiles can specify phase-specific models (scan_model, plan_model, generate_model)
        that override the models defined in the base phase definitions.

        Args:
            phases: Base phase definitions from YAML
            profile: Profile configuration with optional model overrides

        Returns:
            Updated phases dictionary with profile model overrides applied

        .. note::
           This allows profiles to control which models are used for each phase
           without duplicating the entire phase configuration.

        Examples:
            Profile with model overrides::

                balanced:
                  scan_model: "claude-haiku-4-5-20251001"
                  plan_model: "claude-haiku-4-5-20251001"
                  generate_model: "claude-sonnet-4-5-20250929"
        """
        # Deep copy to avoid modifying the original
        import copy

        phases = copy.deepcopy(phases)

        # Map profile model keys to phase names
        model_overrides = {
            "scan": profile.get("scan_model"),
            "plan": profile.get("plan_model"),
            "generate": profile.get("generate_model"),
        }

        # Apply overrides where specified
        for phase_name, model in model_overrides.items():
            if model and phase_name in phases:
                phases[phase_name]["model"] = model
                logger.debug(f"Applied profile model override: {phase_name} -> {model}")

        return phases

    def _get_workflow_model(self, phase_defs: dict) -> str:
        """Select the best model for a multi-phase workflow.

        Since ClaudeSDKClient maintains conversation context across phases,
        we must use a single model for the entire workflow. This method
        selects the most appropriate model based on phase priorities.

        Priority order:
        1. generate phase model (most critical for code quality)
        2. plan phase model (important for structure)
        3. scan phase model (least critical)
        4. Global config model (fallback)

        Args:
            phase_defs: Phase definitions with model specifications

        Returns:
            Model name/ID to use for the workflow

        .. note::
           This is necessary because ClaudeSDKClient doesn't support
           changing models mid-conversation. The profile's model
           overrides are already applied to phase_defs at this point.
        """
        # Priority: generate > plan > scan > global
        for phase_name in ["generate", "plan", "scan"]:
            if phase_name in phase_defs:
                model = phase_defs[phase_name].get("model")
                if model:
                    logger.info(f"Using {phase_name} phase model for workflow: {model}")
                    return model

        # Fallback to global config model
        fallback = self.config.get("model", "claude-sonnet-4-5-20250929")
        logger.info(f"Using fallback model for workflow: {fallback}")
        return fallback

    def _get_codebase_dirs(self, full_config: dict, profile: dict) -> list[str]:
        """Extract ALL codebase directories from configuration.

        Collects directories from all example libraries defined in codebase_guidance.
        ALL libraries are always included - Claude determines what's relevant.

        IMPORTANT: Converts relative paths to absolute paths so they work correctly
        when cwd is set to a restricted directory like /tmp.

        Args:
            full_config: Full configuration from YAML file
            profile: Selected profile configuration

        Returns:
            List of ALL directories that Claude Code is allowed to read (absolute paths)

        .. note::
           If allow_codebase_reading is False in the profile, returns empty list
           to prevent any codebase access.
        """
        if not profile.get("allow_codebase_reading", True):
            return []

        codebase_config = full_config.get("codebase_guidance", {})

        # Collect ALL directories from all libraries
        all_dirs = []
        for _library_name, library_config in codebase_config.items():
            dirs = library_config.get("directories", [])
            all_dirs.extend(dirs)

        # CRITICAL: Convert relative paths to absolute paths
        # When cwd=/tmp, relative paths would resolve from /tmp, not project root!
        # We need absolute paths so Claude can access the actual example directories.
        import os

        absolute_dirs = []
        for dir_path in all_dirs:
            if not os.path.isabs(dir_path):
                # Relative path - make it absolute from current working directory
                # (the actual project directory where the process is running)
                abs_path = os.path.abspath(dir_path)
                absolute_dirs.append(abs_path)
                logger.debug(f"📁 Converted relative path '{dir_path}' → '{abs_path}'")
            else:
                # Already absolute
                absolute_dirs.append(dir_path)

        # Validate that directories exist and warn if not
        validated_dirs = []
        for dir_path in absolute_dirs:
            if Path(dir_path).exists():
                validated_dirs.append(dir_path)
            else:
                logger.warning(
                    f"Codebase directory does not exist (will be inaccessible to Claude): {dir_path}"
                )
                # Still include it - maybe it will be created later

        return absolute_dirs  # Return all dirs, even if some don't exist yet

    def _get_restricted_cwd(self) -> str:
        """Get restricted working directory for Claude Code with example scripts copied in.

        SECURITY CRITICAL: This method creates an isolated directory that Claude Code
        can access. We copy example scripts INTO this directory so Claude can read them
        without needing access to the project workspace.

        Strategy:
        1. Create isolated temp directory
        2. Copy example scripts from project into temp directory
        3. Set this as cwd - Claude can only access this tree
        4. No need for add_dirs - everything is in the cwd tree

        Returns:
            Path to restricted directory with example scripts copied in

        .. warning::
           If cwd is not set, Claude Code defaults to the process's current working
           directory, which would give it access to your ENTIRE project workspace!

        .. note::
           We copy examples instead of using add_dirs because:
           - add_dirs appears to not grant actual file access in Claude Code CLI
           - Copying ensures examples are definitely accessible
           - Still maintains security isolation (project workspace not accessible)
           - Simple relative paths work (no absolute path complexity)
        """
        import os
        import shutil
        import tempfile

        # Create dedicated restricted directory for Claude Code isolation
        system_tmp = tempfile.gettempdir()
        restricted_dir = os.path.join(system_tmp, "osprey_claude_code_restricted")

        # Clean or create the directory
        if Path(restricted_dir).exists():
            try:
                shutil.rmtree(restricted_dir)
                logger.debug(f"Cleaned existing restricted directory: {restricted_dir}")
            except Exception as e:
                logger.warning(f"Could not clean restricted directory: {e}")

        try:
            Path(restricted_dir).mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created restricted directory: {restricted_dir}")
        except Exception as e:
            logger.error(f"Could not create restricted directory: {e}")
            logger.warning("Falling back to system temp directory")
            return system_tmp

        # Copy example scripts into the restricted directory
        # This makes them accessible to Claude without needing add_dirs
        codebase_dirs = self.config.get("codebase_dirs", [])
        if codebase_dirs:
            for source_dir in codebase_dirs:
                if not Path(source_dir).exists():
                    logger.warning(f"Example directory does not exist, skipping: {source_dir}")
                    continue

                # Determine relative path structure to preserve
                # e.g., /full/path/my-control-assistant/_agent_data/example_scripts/plotting
                # -> Copy to restricted_dir/example_scripts/plotting
                source_path = Path(source_dir)

                # Find "example_scripts" or similar in the path
                parts = source_path.parts
                try:
                    # Look for example_scripts in path
                    idx = parts.index("example_scripts")
                    relative_structure = Path(*parts[idx:])
                except ValueError:
                    # Fallback: use last 2 parts of path
                    relative_structure = Path(*parts[-2:]) if len(parts) >= 2 else source_path.name

                dest_dir = Path(restricted_dir) / relative_structure

                try:
                    # Copy the entire directory tree
                    shutil.copytree(source_dir, dest_dir, dirs_exist_ok=True)
                    file_count = len(list(dest_dir.glob("**/*.py")))
                    logger.debug(f"📋 Copied {file_count} example files to restricted directory")
                except Exception as e:
                    logger.error(f"Failed to copy examples: {e}")

        return str(restricted_dir)

    def _build_api_environment(self) -> dict[str, str]:
        """Build environment variables for API access from configuration.

        Returns:
            Dictionary of environment variables to pass to Claude Code CLI

        .. note::
           This provides explicit API configuration instead of relying on
           system environment variables, making the setup more portable and
           explicit. Supports both direct Anthropic API and proxy services
           like CBORG.

        Configuration Examples::

            # Direct Anthropic (default)
            api_config:
              provider: "anthropic"

            # CBORG (LBL proxy)
            api_config:
              provider: "cborg"
              base_url: "https://api.cborg.lbl.gov"
              disable_non_essential_model_calls: true
              disable_telemetry: true
              max_output_tokens: 8192
        """
        import os

        api_config = self.config.get("api_config", {})
        provider = api_config.get("provider", "anthropic")
        env = {}

        if provider == "cborg":
            # CBORG configuration (Lawrence Berkeley Lab model routing)
            logger.info("Claude_Code_Generator: Using CBORG API configuration")

            base_url = api_config.get("base_url", "https://api.cborg.lbl.gov")
            env["ANTHROPIC_BASE_URL"] = base_url

            # Use CBORG_API_KEY if available, otherwise fall back to ANTHROPIC_API_KEY
            cborg_key = os.environ.get("CBORG_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            if cborg_key:
                env["ANTHROPIC_AUTH_TOKEN"] = cborg_key

            # Set model names for CBORG (uses anthropic/model-name format)
            env["ANTHROPIC_MODEL"] = "anthropic/claude-sonnet"
            env["ANTHROPIC_SMALL_FAST_MODEL"] = "anthropic/claude-haiku"

            # Optional CBORG-specific settings
            if api_config.get("disable_non_essential_model_calls", False):
                env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"

            if api_config.get("disable_telemetry", False):
                env["DISABLE_TELEMETRY"] = "1"

            max_tokens = api_config.get("max_output_tokens")
            if max_tokens:
                env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)

        else:
            # Direct Anthropic API (default)
            logger.info("Claude_Code_Generator: Using direct Anthropic API")

            # Use ANTHROPIC_API_KEY from environment
            # No need to set base_url - SDK will use default Anthropic endpoint

        return env

    def _save_prompt_data(self) -> None:
        """Save all prompts and responses to execution folder for transparency.

        Creates a prompts/ subdirectory containing:
        - system_prompt.txt: The base system instructions
        - phase_prompts/: Individual prompts sent to each phase
        - responses/: Claude's responses from each phase
        - conversation_full.json: Complete conversation history
        - example_scripts/: Content of available example scripts
        - metadata.json: Generation metadata (thinking, tools, costs)
        """
        if not self._save_prompts or not self._execution_folder:
            return

        try:
            import json
            prompts_dir = self._execution_folder / "prompts"
            prompts_dir.mkdir(exist_ok=True)

            # Save system prompt
            if "system_prompt" in self._prompt_data:
                (prompts_dir / "system_prompt.txt").write_text(
                    self._prompt_data["system_prompt"], encoding="utf-8"
                )

            # Save phase prompts
            if "phase_prompts" in self._prompt_data:
                phase_prompts_dir = prompts_dir / "phase_prompts"
                phase_prompts_dir.mkdir(exist_ok=True)
                for phase_name, prompt in self._prompt_data["phase_prompts"].items():
                    (phase_prompts_dir / f"{phase_name}.txt").write_text(prompt, encoding="utf-8")

            # Save phase responses
            if "phase_responses" in self._prompt_data:
                responses_dir = prompts_dir / "responses"
                responses_dir.mkdir(exist_ok=True)
                for phase_name, response in self._prompt_data["phase_responses"].items():
                    (responses_dir / f"{phase_name}.txt").write_text(response, encoding="utf-8")

            # Save complete conversation history
            if "conversation_history" in self._prompt_data:
                (prompts_dir / "conversation_full.json").write_text(
                    json.dumps(self._prompt_data["conversation_history"], indent=2),
                    encoding="utf-8"
                )

            # Save example scripts content
            if "example_scripts" in self._prompt_data:
                scripts_dir = prompts_dir / "example_scripts"
                scripts_dir.mkdir(exist_ok=True)
                for script_name, content in self._prompt_data["example_scripts"].items():
                    (scripts_dir / script_name).write_text(content, encoding="utf-8")

            # Save metadata (thinking blocks, tool uses, costs)
            metadata = {
                "generation_metadata": self.generation_metadata,
                "config": {
                    "profile": self.config.get("profile"),
                    "workflow_mode": self.config.get("workflow_mode"),
                    "planning_mode": self.config.get("planning_mode"),
                    "model": self.config.get("model"),
                },
            }
            (prompts_dir / "metadata.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )

            logger.info(f"💾 Prompts saved to: {prompts_dir}")

        except Exception as e:
            logger.warning(f"Failed to save prompts: {e}")

    async def generate_code(
        self, request: PythonExecutionRequest, error_chain: list[ExecutionError]
    ) -> str:
        """Generate code using request's planning mode.

        This is the main entry point that implements the CodeGenerator protocol.
        It dispatches to the appropriate generation method based on the planning mode
        specified in the request:
        - GENERATOR_DRIVEN: Generator scans, plans, and implements
        - CAPABILITY_DRIVEN: Implement capability's pre-built plan

        Supports LangGraph streaming if running within a LangGraph context.
        Will gracefully degrade if streaming is not available.

        Args:
            request: Execution request with task details, context, and planning mode
            error_chain: List of previous errors from failed attempts

        Returns:
            Generated Python code as string

        Raises:
            CodeGenerationError: If generation fails or produces invalid output

        .. seealso::
           :meth:`_generate_with_planning_mode` : Mode-aware generation dispatcher
           :meth:`_generate_phased` : Multi-phase workflow generation
           :meth:`get_generation_metadata` : Access thinking blocks and tool usage
        """
        # Reset metadata for new generation
        self.generation_metadata = {
            "thinking_blocks": [],
            "tool_uses": [],
            "total_thinking_tokens": 0,
        }

        # Set execution folder for saving prompts
        logger.info(f"🔍 save_prompts check: _save_prompts={self._save_prompts}, has_attr={hasattr(request, 'execution_folder_path')}, path={getattr(request, 'execution_folder_path', None)}")
        if self._save_prompts and hasattr(request, 'execution_folder_path') and request.execution_folder_path:
            self._execution_folder = Path(request.execution_folder_path)
            # Initialize prompt data structure
            self._prompt_data = {
                "phase_prompts": {},
                "phase_responses": {},
                "conversation_history": [],
                "example_scripts": {},
            }
            logger.info(f"📝 Will save prompts to: {self._execution_folder / 'prompts'}")
        elif self._save_prompts:
            logger.warning(f"⚠️  save_prompts=True but cannot save: has_execution_folder_path={hasattr(request, 'execution_folder_path')}, path={getattr(request, 'execution_folder_path', None)}")

        # Try to get LangGraph stream writer (graceful degradation if not available)
        self._stream_writer = self._get_stream_writer()
        if self._stream_writer:
            logger.debug("LangGraph streaming enabled for this generation")

        # Use planning mode from request (falls back to config if not set)
        planning_mode = (
            request.planning_mode.value
            if hasattr(request, "planning_mode")
            else self.config.get("planning_mode", "generator_driven")
        )

        logger.info(f"Using planning mode: {planning_mode}")

        try:
            code = await self._generate_with_planning_mode(request, error_chain, planning_mode)
            return code
        finally:
            # Save prompts if enabled
            if self._save_prompts:
                self._save_prompt_data()

    async def _generate_with_planning_mode(
        self, request: PythonExecutionRequest, error_chain: list[ExecutionError], planning_mode: str
    ) -> str:
        """Generate code based on planning mode.

        Dispatcher method that routes to the appropriate generation workflow based on
        the planning mode. Handles both generator-driven and capability-driven modes.

        Args:
            request: Execution request with task details and optional structured plan
            error_chain: List of previous errors from failed attempts
            planning_mode: Planning mode string ("generator_driven" or "capability_driven")

        Returns:
            Generated Python code as string

        Raises:
            CodeGenerationError: If generation fails or planning mode is invalid

        .. note::
           Generator-driven mode runs configured phases (scan → plan → generate).
           Capability-driven mode only runs generate phase with capability's plan.
        """
        # Get planning mode configuration
        planning_modes_config = self.config.get("planning_modes", {})
        mode_config = planning_modes_config.get(planning_mode, {})

        if not mode_config:
            logger.warning(
                f"Planning mode '{planning_mode}' not found in config, falling back to generator_driven"
            )
            planning_mode = "generator_driven"
            mode_config = planning_modes_config.get(planning_mode, {})

        # Get phases to run for this mode
        phases_to_run = mode_config.get("phases", ["scan", "plan", "generate"])

        # OPTIMIZATION: On retries, skip scan and plan - go directly to generate with error feedback
        # The scan and plan from the first attempt are already done, we just need to fix the code
        if error_chain:
            logger.info(
                f"Retry detected ({len(error_chain)} previous errors) - skipping to generate phase"
            )
            phases_to_run = ["generate"]
        else:
            logger.info(f"First attempt - running full workflow: {phases_to_run}")

        # For capability-driven mode, validate structured plan is provided
        if planning_mode == "capability_driven":
            if not hasattr(request, "structured_plan") or request.structured_plan is None:
                raise CodeGenerationError(
                    "Capability-driven mode requires structured_plan in request",
                    generation_attempt=len(error_chain) + 1,
                    error_chain=error_chain,
                )
            logger.info("Using capability-provided structured plan")

        # Execute the workflow with configured phases
        return await self._generate_phased_with_modes(
            request, error_chain, phases_to_run, mode_config
        )

    def _get_stream_writer(self):
        """Get LangGraph stream writer if available.

        Attempts to get the stream writer from LangGraph context.
        Returns None if LangGraph streaming is not available or if
        we're not running in a streaming context.

        Returns:
            Stream writer function or None
        """
        if not LANGGRAPH_STREAMING_AVAILABLE:
            return None

        try:
            writer = get_stream_writer()
            return writer
        except Exception:
            # Not in a LangGraph streaming context
            return None

    def _stream(self, data: dict[str, Any]) -> None:
        """Stream data to LangGraph if streaming is available.

        Safely streams data through LangGraph's custom streaming mechanism.
        Fails silently if streaming is not available.

        Args:
            data: Dictionary to stream to LangGraph consumers
        """
        if self._stream_writer:
            try:
                self._stream_writer(data)
            except Exception as e:
                # Don't let streaming errors break generation
                logger.debug(f"Streaming failed (non-fatal): {e}")

    def get_generation_metadata(self) -> dict[str, Any]:
        """Get metadata from the last generation for LangGraph state integration.

        Returns metadata that can be added to LangGraph state to track:
        - Thinking blocks: Extended reasoning from Claude's thought process
        - Tool usage: Which tools Claude used during generation
        - Cost information: API cost for the generation

        This metadata is valuable for:
        - **Debugging**: Understanding Claude's reasoning process
        - **Audit trails**: Recording decision-making for compliance
        - **Transparency**: Showing users how code was generated
        - **Notebooks**: Including thinking in execution notebooks

        Returns:
            Dictionary containing:
            - thinking_blocks: List of thinking entries with content and signatures
            - tool_uses: List of tools used with names and inputs
            - total_thinking_tokens: Approximate token count for thinking
            - cost_usd: API cost for this generation (if available)

        Examples:
            Including metadata in LangGraph state::

                >>> generator = ClaudeCodeGenerator()
                >>> code = await generator.generate_code(request, [])
                >>> metadata = generator.get_generation_metadata()
                >>>
                >>> # Add to LangGraph state
                >>> state['generation_metadata'] = metadata
                >>> state['thinking_summary'] = f"{len(metadata['thinking_blocks'])} thinking blocks"
                >>>
                >>> # Log for debugging
                >>> for thinking in metadata['thinking_blocks']:
                >>>     logger.debug(f"Thinking: {thinking['content'][:100]}...")
        """
        return self.generation_metadata.copy()

    async def _generate_direct(
        self, request: PythonExecutionRequest, error_chain: list[ExecutionError]
    ) -> str:
        """Direct code generation (one-pass mode).

        Generates code in a single agentic conversation. Claude can still read
        files, search code, and iterate, but everything happens in one pass
        without explicit scan/plan/generate phases.

        Args:
            request: Execution request
            error_chain: Previous errors for retry feedback

        Returns:
            Generated Python code

        Raises:
            CodeGenerationError: If generation fails

        .. note::
           This mode is faster but may produce lower quality code for complex
           tasks compared to phased mode. Good for development and simple tasks.
        """
        # SECURITY: Get restricted working directory (with examples copied in)
        restricted_cwd = self._get_restricted_cwd()

        options = ClaudeAgentOptions(
            system_prompt=self._build_system_prompt(request),
            allowed_tools=["Read", "Grep", "Glob"] if self.config["codebase_dirs"] else [],
            disallowed_tools=["Write", "Edit", "MultiEdit", "Delete", "Bash", "Python"],
            cwd=restricted_cwd,  # 🔒 Examples copied into cwd, no add_dirs needed
            model=self.config["model"],
            max_turns=self.config["max_turns"],
            max_budget_usd=self.config["max_budget_usd"],
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[self._safety_hook])]},
            env=self._build_api_environment(),
        )

        prompt = self._build_generation_prompt(request, error_chain)

        return await self._execute_query(prompt, options, error_chain, extract_code=True)

    async def _generate_phased_with_modes(
        self,
        request: PythonExecutionRequest,
        error_chain: list[ExecutionError],
        phases_to_run: list[str],
        mode_config: dict[str, Any],
    ) -> str:
        """Flexible phased code generation supporting planning modes.

        Executes a configurable workflow where different phases can be enabled/disabled
        based on the planning mode. Supports both generator-driven and capability-driven modes.

        Args:
            request: Execution request with optional structured plan
            error_chain: Previous errors for retry feedback
            phases_to_run: List of phase names to execute (e.g., ["scan", "plan", "generate"])
            mode_config: Planning mode configuration from config file

        Returns:
            Generated Python code

        Raises:
            CodeGenerationError: If any phase fails

        .. note::
           For capability-driven mode, the generate phase uses the structured plan
           provided by the capability instead of creating its own plan.
        """
        # Get phase definitions
        phase_defs = self.config.get("phases", {})

        if not phase_defs:
            logger.warning("No phase definitions found, falling back to direct mode")
            return await self._generate_direct(request, error_chain)

        # Use ClaudeSDKClient for stateful multi-turn conversation
        # Since ClaudeSDKClient maintains context, we use a single model for all phases.
        # We prefer the generate phase's model since that's the most critical phase.
        workflow_model = self._get_workflow_model(phase_defs)

        # SECURITY: Set up restricted working directory
        # Claude Code's cwd parameter controls the base workspace directory.
        # If not set, Claude has access to the ENTIRE current working directory.
        # We MUST explicitly restrict access to ONLY the example directories.
        restricted_cwd = self._get_restricted_cwd()

        # Compact workflow configuration logging
        config_parts = [workflow_model, ' → '.join(phases_to_run), f"${self.config['max_budget_usd']}"]
        logger.info(f"🔧 Workflow: {', '.join(config_parts)}")

        options = ClaudeAgentOptions(
            system_prompt=self._build_system_prompt(request),
            allowed_tools=["Read", "Grep", "Glob"] if self.config["codebase_dirs"] else [],
            disallowed_tools=["Write", "Edit", "MultiEdit", "Delete", "Bash", "Python"],
            cwd=restricted_cwd,  # 🔒 Examples copied into cwd, no add_dirs needed
            model=workflow_model,
            max_budget_usd=self.config["max_budget_usd"],
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[self._safety_hook])]},
            env=self._build_api_environment(),
        )

        try:
            # Track overall workflow timing
            import time
            workflow_start_time = time.time()

            async with ClaudeSDKClient(options=options) as client:
                # Track which phases have been executed for context chaining
                executed_phases = []

                # Execute phases dynamically based on configuration
                for phase_name in phases_to_run:
                    phase_def = phase_defs.get(phase_name, {})

                    if not phase_def:
                        logger.warning(f"Phase '{phase_name}' not found in configuration, skipping")
                        continue

                    # Timing: Track phase duration
                    import time
                    phase_start_time = time.time()

                    logger.info(f"⚡ {phase_name.upper()}")
                    self._stream(
                        {"type": "claude_code", "event": "phase_start", "phase": phase_name}
                    )

                    # Build prompt for this phase with explicit references to previous phases
                    if phase_name == "scan":
                        prompt = self._build_scan_prompt(request, phase_def, executed_phases)
                    elif phase_name == "plan":
                        prompt = self._build_plan_prompt_for_client(
                            request, phase_def, executed_phases
                        )
                    elif phase_name == "generate":
                        # For capability-driven mode, inject structured plan
                        if (
                            hasattr(request, "structured_plan")
                            and request.structured_plan is not None
                        ):
                            prompt = self._build_generate_prompt_with_capability_plan(
                                request, error_chain, phase_def
                            )
                        else:
                            prompt = self._build_generate_prompt_for_client(
                                request, error_chain, phase_def, executed_phases
                            )
                    else:
                        # Generic phase
                        prompt = self._build_generic_phase_prompt(
                            request, phase_def, executed_phases
                        )

                    # Log what examples are available for scan phase
                    if phase_name == "scan":
                        example_scripts_dir = Path(restricted_cwd) / "example_scripts"
                        if example_scripts_dir.exists():
                            file_count = len(list(example_scripts_dir.glob("**/*.py")))
                            logger.info(f"📂 {file_count} example files available: {example_scripts_dir}")

                            # Capture example script content if saving prompts
                            if self._save_prompts:
                                for script_file in example_scripts_dir.glob("**/*.py"):
                                    rel_path = str(script_file.relative_to(example_scripts_dir))
                                    self._prompt_data["example_scripts"][rel_path] = script_file.read_text(encoding="utf-8")
                        else:
                            logger.info("📂 No example scripts available")

                    # Save phase prompt if enabled
                    if self._save_prompts:
                        self._prompt_data["phase_prompts"][phase_name] = prompt

                    # Execute phase
                    await client.query(prompt)
                    response = await self._collect_response(client, phase_name)

                    # Save phase response if enabled
                    if self._save_prompts:
                        self._prompt_data["phase_responses"][phase_name] = response

                    # Timing: Calculate and log phase duration
                    phase_duration = time.time() - phase_start_time
                    logger.info(f"✅ {phase_name.upper()}: {len(response)} chars in {phase_duration:.1f}s")

                    # Track this phase as executed for context chaining
                    executed_phases.append(phase_name)

                    # For generate phase, extract and return code
                    if phase_name == "generate":
                        code = self._extract_code_from_text(response)
                        if not code:
                            # Debug: log what we actually got
                            logger.warning(
                                f"Failed to extract code from response. First 500 chars: {response[:500]}"
                            )

                            # Try alternative extraction: if response looks like Python code, use it directly
                            if self._looks_like_python_code(response):
                                logger.info(
                                    "Response appears to be Python code without markdown - using directly"
                                )
                                code = response.strip()
                            else:
                                raise CodeGenerationError(
                                    f"No code found in {phase_name} phase response (got {len(response)} chars)",
                                    generation_attempt=len(error_chain) + 1,
                                    error_chain=error_chain,
                                )

                        # Calculate total workflow time
                        workflow_duration = time.time() - workflow_start_time

                        # Compact summary logging
                        summary_parts = [
                            f"{len(code)} chars",
                            f"{workflow_duration:.1f}s",
                            ' → '.join(executed_phases)
                        ]
                        if self.generation_metadata.get("cost_usd"):
                            summary_parts.append(f"${self.generation_metadata['cost_usd']:.4f}")

                        logger.success(f"🎉 Generated: {', '.join(summary_parts)}")

                        return self._clean_generated_code(code)

                # If we get here without returning, no generate phase was run
                raise CodeGenerationError(
                    "No generate phase in workflow - cannot produce code",
                    generation_attempt=len(error_chain) + 1,
                    error_chain=error_chain,
                )

        except ClaudeSDKError as e:
            logger.error(f"Claude SDK error during phased generation: {e}")
            raise CodeGenerationError(
                f"Phased generation failed: {str(e)}",
                generation_attempt=len(error_chain) + 1,
                error_chain=error_chain,
            ) from e

    async def _generate_phased(
        self, request: PythonExecutionRequest, error_chain: list[ExecutionError]
    ) -> str:
        """Phased 3-phase code generation (structured workflow mode).

        Executes a multi-phase workflow using ClaudeSDKClient for context retention:
        1. SCAN: Search codebase for relevant examples and patterns
        2. PLAN: Create detailed implementation plan (builds on scan context)
        3. GENERATE: Generate code following the plan (builds on scan + plan context)

        Using ClaudeSDKClient enables Claude to retain conversation context across
        phases, producing higher quality output than separate queries.

        Args:
            request: Execution request
            error_chain: Previous errors for retry feedback

        Returns:
            Generated Python code

        Raises:
            CodeGenerationError: If any phase fails

        .. note::
           Falls back to direct mode if workflow configuration is missing.
           This mode is slower but produces higher quality code for complex tasks.
        """
        workflow = self.config["workflows"].get("phased", {})
        phases = workflow.get("phases", {})

        if not phases:
            logger.warning("Phased workflow not configured, falling back to direct mode")
            return await self._generate_direct(request, error_chain)

        # SECURITY: Get restricted working directory
        restricted_cwd = self._get_restricted_cwd()

        # Use ClaudeSDKClient for stateful multi-turn conversation
        options = ClaudeAgentOptions(
            system_prompt=self._build_system_prompt(request),
            allowed_tools=["Read", "Grep", "Glob"] if self.config["codebase_dirs"] else [],
            disallowed_tools=["Write", "Edit", "MultiEdit", "Delete", "Bash", "Python"],
            cwd=restricted_cwd,  # 🔒 Examples copied into cwd, no add_dirs needed
            model=self.config["model"],
            max_budget_usd=self.config["max_budget_usd"],
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[self._safety_hook])]},
            env=self._build_api_environment(),
        )

        try:
            async with ClaudeSDKClient(options=options) as client:
                executed_phases = []

                # Phase 1: SCAN
                logger.info("Phase 1: Scanning codebase for relevant examples")
                self._stream({"type": "claude_code", "event": "phase_start", "phase": "scan"})

                scan_phase = phases.get("scan", {})
                scan_prompt = self._build_scan_prompt(request, scan_phase, executed_phases)
                await client.query(scan_prompt)

                analysis = await self._collect_response(client, "scan")
                logger.info(f"Scan complete: {len(analysis)} characters of analysis")
                executed_phases.append("scan")

                # Phase 2: PLAN (builds on scan context - now with explicit instructions!)
                logger.info("Phase 2: Creating implementation plan")
                self._stream({"type": "claude_code", "event": "phase_start", "phase": "plan"})

                plan_phase = phases.get("plan", {})
                # Use the new builder that explicitly references scan results
                plan_prompt = self._build_plan_prompt_for_client(
                    request, plan_phase, executed_phases
                )
                await client.query(plan_prompt)

                plan = await self._collect_response(client, "plan")
                logger.info(f"Plan complete: {len(plan)} characters")
                executed_phases.append("plan")

                # Phase 3: GENERATE (builds on scan + plan context - now with explicit instructions!)
                logger.info("Phase 3: Generating Python code")
                self._stream({"type": "claude_code", "event": "phase_start", "phase": "generate"})

                gen_phase = phases.get("generate", {})
                gen_prompt = self._build_generate_prompt_for_client(
                    request, error_chain, gen_phase, executed_phases
                )
                await client.query(gen_prompt)

                code_text = await self._collect_response(client, "generate")

                # Extract code from the response
                code = self._extract_code_from_text(code_text)
                if not code:
                    raise CodeGenerationError(
                        "No code found in phased generation response",
                        generation_attempt=len(error_chain) + 1,
                        error_chain=error_chain,
                    )

                logger.success(f"Phased generation complete: {len(code)} characters")
                return self._clean_generated_code(code)

        except ClaudeSDKError as e:
            logger.error(f"Claude SDK error during phased generation: {e}")
            raise CodeGenerationError(
                f"Phased generation failed: {str(e)}",
                generation_attempt=len(error_chain) + 1,
                error_chain=error_chain,
            ) from e

    def _build_phase_options(self, phase_config: dict) -> ClaudeAgentOptions:
        """Build SDK options for a specific workflow phase.

        Args:
            phase_config: Phase configuration from workflow definition

        Returns:
            ClaudeAgentOptions configured for the phase

        .. note::
           Each phase can have its own model, tools, and turn limits while
           sharing the global budget limit for cost control.
        """
        tools = phase_config.get("tools", [])

        # SECURITY: Get restricted working directory
        restricted_cwd = self._get_restricted_cwd()

        return ClaudeAgentOptions(
            system_prompt=phase_config.get("prompt", ""),
            allowed_tools=tools,
            disallowed_tools=["Write", "Edit", "MultiEdit", "Delete", "Bash", "Python"],
            cwd=restricted_cwd,  # 🔒 Examples copied into cwd, no add_dirs needed
            model=phase_config.get("model", self.config["model"]),
            max_turns=phase_config.get("max_turns", 3),
            max_budget_usd=self.config["max_budget_usd"],
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[self._safety_hook])]},
            env=self._build_api_environment(),
        )

    async def _execute_query(
        self,
        prompt: str,
        options: ClaudeAgentOptions,
        error_chain: list[ExecutionError],
        extract_code: bool = False,
    ) -> str:
        """Execute a Claude Code query with comprehensive error handling and metadata tracking.

        Args:
            prompt: User prompt for Claude
            options: SDK configuration options
            error_chain: Error chain for error reporting
            extract_code: Whether to extract code blocks from response

        Returns:
            Response text (or extracted code if extract_code=True)

        Raises:
            CodeGenerationError: If query fails or produces invalid output

        .. note::
           This method:
           - Handles all SDK message types (Text, Thinking, ToolUse)
           - Tracks generation metadata for LangGraph state
           - Checks for SDK-specific errors
           - Validates budget limits
           - Streams progress to LangGraph if available
        """
        try:
            result_text = ""
            total_cost = None
            tool_uses = []
            thinking_content = []

            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            result_text += block.text + "\n"

                            # Stream text chunks for real-time progress (but don't log)
                            self._stream(
                                {
                                    "type": "claude_code",
                                    "event": "text",
                                    "content": block.text[:200],  # Preview
                                    "length": len(block.text),
                                }
                            )

                        elif isinstance(block, ThinkingBlock):
                            # Track thinking for LangGraph state and debugging
                            thinking_entry = {
                                "content": block.thinking,
                                "signature": block.signature,
                                "length": len(block.thinking),
                            }
                            thinking_content.append(thinking_entry)

                            # Stream Claude's reasoning process (but don't log each one)
                            self._stream(
                                {
                                    "type": "claude_code",
                                    "event": "thinking",
                                    "preview": block.thinking[
                                        :300
                                    ],  # Give users insight into reasoning
                                    "length": len(block.thinking),
                                    "signature": block.signature,
                                }
                            )

                        elif isinstance(block, ToolUseBlock):
                            # Track tool usage for debugging and security audit
                            tool_entry = {"name": block.name, "id": block.id, "input": block.input}
                            tool_uses.append(tool_entry)

                            # Stream tool usage for transparency (but don't log each one)
                            self._stream(
                                {
                                    "type": "claude_code",
                                    "event": "tool_use",
                                    "tool": block.name,
                                    "input": self._sanitize_tool_input(block.input),
                                }
                            )

                elif isinstance(message, ResultMessage):
                    # Check for errors first
                    if message.is_error:
                        error_msg = f"Claude Code error ({message.subtype})"
                        if message.result:
                            error_msg += f": {message.result}"
                        raise CodeGenerationError(
                            error_msg,
                            generation_attempt=len(error_chain) + 1,
                            error_chain=error_chain,
                            technical_details={
                                "subtype": message.subtype,
                                "turns": message.num_turns,
                                "cost": message.total_cost_usd,
                                "is_error": True,
                            },
                        )

                    # Check for budget exceeded
                    if message.subtype == "error_max_budget_usd":
                        raise CodeGenerationError(
                            f"Budget exceeded: ${message.total_cost_usd:.4f}",
                            generation_attempt=len(error_chain) + 1,
                            error_chain=error_chain,
                            technical_details={
                                "subtype": "budget_exceeded",
                                "cost": message.total_cost_usd,
                                "budget_limit": self.config.get("max_budget_usd"),
                            },
                        )

                    total_cost = message.total_cost_usd

                    # Compact summary logging
                    summary_parts = [f"{message.num_turns} turns", f"{message.duration_ms/1000:.1f}s"]
                    if total_cost:
                        summary_parts.append(f"${total_cost:.4f}")
                    if tool_uses:
                        summary_parts.append(f"{len(tool_uses)} tools")

                    logger.info(f"✅ Complete: {', '.join(summary_parts)}")

                    # Stream completion metrics
                    self._stream(
                        {
                            "type": "claude_code",
                            "event": "complete",
                            "cost_usd": total_cost,
                            "duration_ms": message.duration_ms,
                            "turns": message.num_turns,
                            "thinking_blocks": len(thinking_content),
                            "tools_used": len(tool_uses),
                        }
                    )

            # Store metadata for LangGraph state integration
            self.generation_metadata = {
                "thinking_blocks": thinking_content,
                "tool_uses": tool_uses,
                "total_thinking_tokens": sum(t["length"] for t in thinking_content),
                "cost_usd": total_cost,
            }

            if not result_text:
                raise CodeGenerationError(
                    "Claude Code did not generate valid response",
                    generation_attempt=len(error_chain) + 1,
                    error_chain=error_chain,
                    technical_details={
                        "had_thinking": len(thinking_content) > 0,
                        "had_tools": len(tool_uses) > 0,
                    },
                )

            if extract_code:
                code = self._extract_code_from_text(result_text)
                if not code:
                    raise CodeGenerationError(
                        "No code found in Claude Code response",
                        generation_attempt=len(error_chain) + 1,
                        error_chain=error_chain,
                        technical_details={
                            "response_length": len(result_text),
                            "had_thinking": len(thinking_content) > 0,
                        },
                    )
                return self._clean_generated_code(code)

            return result_text.strip()

        except CodeGenerationError:
            raise
        except CLIConnectionError as e:
            logger.error(f"Claude Code CLI connection failed: {e}")
            raise CodeGenerationError(
                "Failed to connect to Claude Code CLI. Ensure it is installed and accessible.",
                generation_attempt=len(error_chain) + 1,
                error_chain=error_chain,
                technical_details={
                    "error_type": "CLIConnectionError",
                    "details": str(e),
                    "cli_path": getattr(options, "cli_path", "default"),
                },
            ) from e
        except ClaudeSDKError as e:
            logger.error(f"Claude SDK error: {e}")
            raise CodeGenerationError(
                f"Claude SDK error: {str(e)}",
                generation_attempt=len(error_chain) + 1,
                error_chain=error_chain,
                technical_details={"error_type": type(e).__name__, "details": str(e)},
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error during code generation: {e}")
            raise CodeGenerationError(
                f"Unexpected error: {str(e)}",
                generation_attempt=len(error_chain) + 1,
                error_chain=error_chain,
                technical_details={"error_type": type(e).__name__, "details": str(e)},
            ) from e

    async def _safety_hook(
        self, input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        """Safety hook to prevent dangerous operations.

        This PreToolUse hook provides runtime protection against dangerous
        operations, serving as a second layer of defense after SDK configuration.

        Args:
            input_data: Hook input with tool information
            tool_use_id: Tool use identifier
            context: Hook context

        Returns:
            Hook output with permission decision

        .. note::
           This hook denies any attempt to use Write/Edit/Delete/Bash/Python
           tools, even if they somehow bypass the allowed_tools configuration.
        """
        tool_name = input_data.get("tool_name", "")

        dangerous_tools = ["Write", "Edit", "MultiEdit", "Delete", "Bash", "Python", "Execute"]

        if tool_name in dangerous_tools:
            logger.warning(f"BLOCKED {tool_name} during code generation")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"{tool_name} not allowed during code generation. "
                        f"Generator may only read code for context."
                    ),
                }
            }

        return {}

    def _build_system_prompt(self, request: PythonExecutionRequest) -> str:
        """Build system prompt for code generation.

        Includes base instructions plus ALL guidance from codebase libraries.
        Claude sees all available patterns and determines what's relevant.

        Args:
            request: Execution request with context

        Returns:
            System prompt string with base instructions + all library guidance
        """
        prompt = """You are an expert Python code generator for scientific computing and control systems.

Generate high-quality, executable Python code based on user requirements.

RULES:
1. Generate ONLY executable Python code
2. Include all necessary imports at the top
3. Store results in a dictionary variable named 'results'
4. Use clear variable names and add comments
5. Focus on the specific task
6. Output code in ```python ... ``` blocks

Your generated code will be analyzed for security, reviewed by humans (if needed),
and executed in a secure environment."""

        # Append ALL guidance from codebase libraries
        codebase_guidance = self.config.get("codebase_guidance", {})
        if codebase_guidance:
            prompt += "\n\nAVAILABLE EXAMPLE LIBRARIES:\n"
            prompt += "You have access to example code in the following areas.\n"
            prompt += "Search these directories when relevant to learn established patterns.\n\n"

            for library_name, library_config in codebase_guidance.items():
                guidance = library_config.get("guidance", "")
                if guidance:
                    prompt += f"{library_name.upper()}:\n{guidance}\n\n"

        # Save system prompt if enabled
        if self._save_prompts:
            self._prompt_data["system_prompt"] = prompt

        return prompt

    def _build_generation_prompt(
        self, request: PythonExecutionRequest, error_chain: list[ExecutionError]
    ) -> str:
        """Build prompt for single-shot generation with structured error feedback.

        Args:
            request: Execution request
            error_chain: Previous ExecutionError objects for retry feedback

        Returns:
            Complete prompt for code generation with rich error context
        """
        parts = [
            f"**Task:** {request.task_objective}",
            f"**User Query:** {request.user_query}",
        ]

        if request.expected_results:
            parts.append(f"**Expected Results:** {request.expected_results}")

        if request.capability_context_data:
            parts.append("\n**Available Context:** A 'context' object will be provided at runtime.")

        if request.capability_prompts:
            parts.append("\n**Additional Guidance:**")
            parts.extend(request.capability_prompts)

        if error_chain:
            parts.append("\n**PREVIOUS ATTEMPT(S) FAILED - LEARN FROM THESE ERRORS:**")
            parts.append("\nAnalyze what went wrong and address the root cause, not just symptoms.")

            # Show last 2 attempts with full structured context
            for error in error_chain[-2:]:
                parts.append(f"\n{'=' * 60}")
                parts.append(error.to_prompt_text())

            parts.append(f"\n{'=' * 60}")
            parts.append("\n**Your Task:** Generate IMPROVED code that fixes these issues.")

        parts.append("\nGenerate complete Python code for this task.")

        return "\n\n".join(parts)

    def _build_scan_prompt(
        self, request: PythonExecutionRequest, phase: dict, executed_phases: list[str]
    ) -> str:
        """Build prompt for scan phase.

        Args:
            request: Execution request
            phase: Scan phase configuration
            executed_phases: List of phases already executed (for context chaining)

        Returns:
            Scan prompt
        """
        parts = [phase.get("prompt", "")]

        if request.task_objective:
            parts.append(f"\n**Task Objective:** {request.task_objective}")

        if request.user_query:
            parts.append(f"\n**User Query:** {request.user_query}")

        if request.expected_results:
            parts.append(f"\n**Expected Results:** {request.expected_results}")

        # Tell Claude about available example directories (now copied into cwd)
        codebase_guidance = self.config.get("codebase_guidance", {})

        if codebase_guidance:
            parts.append("\n**Available Example Code Libraries:**")
            parts.append("Example code has been provided in your working directory:")

            for library_name, library_config in codebase_guidance.items():
                guidance = library_config.get("guidance", "")

                parts.append(f"\n**{library_name.upper()} Examples:**")
                parts.append("**Directory:** `example_scripts/plotting/`")
                if guidance:
                    parts.append(f"\n**Use when:** {guidance}")

            parts.append(
                "\n**Scanning Strategy:**"
                "\n1. Use Glob/Read/Grep to search example_scripts/ directory"
                "\n2. Example: `Glob(pattern='example_scripts/**/*.py')`"
                "\n3. Read relevant examples and explain patterns to follow"
                "\n4. If no relevant examples exist, use standard best practices"
            )

        # Explicit output instruction for next phase
        parts.append(
            "\n**Important:** Provide a clear, structured analysis that can be used in the next phase for planning."
        )

        return "\n".join(parts)

    def _build_plan_prompt(
        self, request: PythonExecutionRequest, analysis: str, phase: dict
    ) -> str:
        """Build prompt for plan phase (legacy - not used with ClaudeSDKClient).

        Args:
            request: Execution request
            analysis: Analysis from scan phase
            phase: Plan phase configuration

        Returns:
            Plan prompt
        """
        return f"{phase.get('prompt', '')}\n\nAnalysis:\n{analysis}\n\nTask: {request.user_query}"

    def _build_plan_prompt_for_client(
        self, request: PythonExecutionRequest, phase: dict, executed_phases: list[str]
    ) -> str:
        """Build prompt for plan phase when using ClaudeSDKClient.

        Since ClaudeSDKClient retains conversation context, we don't need
        to repeat the scan results - Claude already has them!

        Args:
            request: Execution request
            phase: Plan phase configuration
            executed_phases: List of phases already executed (for context chaining)

        Returns:
            Plan prompt with full request context
        """
        parts = [phase.get("prompt", "")]

        # Explicitly reference previous phases if they were executed
        if "scan" in executed_phases:
            parts.append("\n**Context from Scan Phase:**")
            parts.append(
                "Based on the codebase analysis you just performed above, create a detailed implementation plan."
            )

        if request.task_objective:
            parts.append(f"\n**Task Objective:** {request.task_objective}")

        if request.user_query:
            parts.append(f"\n**User Query:** {request.user_query}")

        if request.expected_results:
            parts.append(f"\n**Expected Results:** {request.expected_results}")

        # Explicit output instruction for next phase
        parts.append(
            "\n**Important:** Provide a clear, actionable implementation plan that will guide the code generation in the next phase."
        )

        return "\n".join(parts)

    def _build_generic_phase_prompt(
        self, request: PythonExecutionRequest, phase: dict, executed_phases: list[str]
    ) -> str:
        """Build prompt for generic phase with full request context.

        Args:
            request: Execution request
            phase: Phase configuration
            executed_phases: List of phases already executed (for context chaining)

        Returns:
            Generic phase prompt
        """
        parts = [phase.get("prompt", "")]

        # Reference previous phases if any
        if executed_phases:
            parts.append(
                f"\n**Context:** Building on the results from previous phases: {', '.join(executed_phases)}"
            )

        if request.task_objective:
            parts.append(f"\n**Task Objective:** {request.task_objective}")

        if request.user_query:
            parts.append(f"\n**User Query:** {request.user_query}")

        if request.expected_results:
            parts.append(f"\n**Expected Results:** {request.expected_results}")

        return "\n".join(parts)

    def _build_generate_prompt(
        self,
        request: PythonExecutionRequest,
        plan: str,
        error_chain: list[ExecutionError],
        phase: dict,
    ) -> str:
        """Build prompt for generate phase (used in non-client mode).

        Args:
            request: Execution request
            plan: Implementation plan from plan phase
            error_chain: Previous ExecutionError objects for retry feedback
            phase: Generate phase configuration

        Returns:
            Generate prompt
        """
        parts = [
            phase.get("prompt", ""),
            f"\n**Implementation Plan:**\n{plan}",
            f"\n**User Query:** {request.user_query}",
        ]

        if error_chain:
            parts.append("\n**Previous Errors:**")
            for error in error_chain[-2:]:
                parts.append(error.to_prompt_text())

        parts.append("\nGenerate the complete Python code following this plan.")

        return "\n".join(parts)

    def _build_generate_prompt_for_client(
        self,
        request: PythonExecutionRequest,
        error_chain: list[ExecutionError],
        phase: dict,
        executed_phases: list[str],
    ) -> str:
        """Build prompt for generate phase when using ClaudeSDKClient.

        Since ClaudeSDKClient retains conversation context, we don't need
        to repeat the scan results or plan - Claude already has them!

        Args:
            request: Execution request
            error_chain: Previous ExecutionError objects for retry feedback
            phase: Generate phase configuration
            executed_phases: List of phases already executed (for context chaining)

        Returns:
            Generate prompt
        """
        parts = [phase.get("prompt", "")]

        # EXPLICIT INSTRUCTION: Reference the workflow so far
        if "scan" in executed_phases and "plan" in executed_phases:
            parts.append("\n**Context from Previous Phases:**")
            parts.append("You have already:")
            parts.append("1. Scanned the codebase and identified relevant patterns and examples")
            parts.append("2. Created a detailed implementation plan")
            parts.append(
                "\nNow use BOTH the codebase insights AND your implementation plan to generate high-quality code."
            )
        elif "plan" in executed_phases:
            parts.append("\n**Context from Plan Phase:**")
            parts.append(
                "You created an implementation plan above. Now implement it with high-quality Python code."
            )
        elif "scan" in executed_phases:
            parts.append("\n**Context from Scan Phase:**")
            parts.append(
                "You analyzed the codebase above. Now use those insights to generate high-quality code."
            )

        if request.task_objective:
            parts.append(f"\n**Task Objective:** {request.task_objective}")

        if request.user_query:
            parts.append(f"\n**User Query:** {request.user_query}")

        if request.expected_results:
            parts.append(f"\n**Expected Results:** {request.expected_results}")

        if request.capability_prompts:
            parts.append("\n**Additional Guidance:**")
            parts.extend(request.capability_prompts)

        if error_chain:
            parts.append("\n**Previous Errors - Learn and Fix:**")
            for error in error_chain[-2:]:
                parts.append(error.to_prompt_text())
            parts.append(
                "\nGenerate IMPROVED code that fixes these errors AND follows the plan you created earlier."
            )
        else:
            parts.append("\n**Final Step:** Generate the complete, executable Python code.")

        return "\n".join(parts)

    def _build_generate_prompt_with_capability_plan(
        self, request: PythonExecutionRequest, error_chain: list[ExecutionError], phase: dict
    ) -> str:
        """Build prompt for generate phase with capability-provided structured plan.

        For capability-driven mode, injects the structured plan from the capability
        to guide code generation with precise analysis structure and result schema.

        Args:
            request: Execution request with structured_plan field
            error_chain: Previous ExecutionError objects for retry feedback
            phase: Generate phase configuration

        Returns:
            Generate prompt with injected structured plan
        """
        import json

        plan = request.structured_plan

        # Format the structured plan for Claude
        plan_text = []
        if plan.domain_guidance:
            plan_text.append(
                f"\n**IMPLEMENTATION PLAN (from capability):**\n{plan.domain_guidance}"
            )

        # Format phases
        if plan.phases:
            plan_text.append("\n**EXECUTION PHASES:**")
            for i, phase_obj in enumerate(plan.phases, 1):
                plan_text.append(f"\nPhase {i}: {phase_obj.phase}")
                if phase_obj.subtasks:
                    for subtask in phase_obj.subtasks:
                        plan_text.append(f"  • {subtask}")
                if phase_obj.output_state:
                    plan_text.append(f"  → Output: {phase_obj.output_state}")

        # Format required result structure
        if plan.result_schema:
            plan_text.append("\n**REQUIRED RESULT STRUCTURE:**")
            plan_text.append("```python")
            plan_text.append(f"results = {json.dumps(plan.result_schema, indent=2)}")
            plan_text.append("```")
            plan_text.append(
                "\nIMPORTANT: Your code MUST produce a 'results' dictionary matching this exact structure."
            )
            plan_text.append(
                "Replace placeholder values (like '<float>', '<string>') with actual computed values."
            )

        parts = [
            phase.get("prompt", ""),
            f"\n**User Query:** {request.user_query}",
            "".join(plan_text),
        ]

        if error_chain:
            parts.append("\n**Previous Errors - Learn and Fix:**")
            for error in error_chain[-2:]:
                parts.append(error.to_prompt_text())
            parts.append(
                "\nGenerate IMPROVED code that fixes these errors AND follows the plan above."
            )
        else:
            parts.append(
                "\nGenerate the complete Python code following the structured plan provided above."
            )

        return "\n".join(parts)

    async def _collect_response(self, client: ClaudeSDKClient, phase: str) -> str:
        """Collect and stream response from ClaudeSDKClient.

        Args:
            client: Connected ClaudeSDKClient
            phase: Current phase name (for streaming)

        Returns:
            Complete response text
        """
        response_text = ""
        thinking_blocks = []
        tool_uses = []

        async for message in client.receive_response():
            # CAPTURE COMPLETE CONVERSATION HISTORY
            # Save EVERY message to conversation history for complete transparency
            if self._save_prompts:
                self._prompt_data["conversation_history"].append(
                    self._serialize_message_for_history(message)
                )

            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text + "\n"

                        # Stream progress (but don't log text blocks)
                        self._stream(
                            {
                                "type": "claude_code",
                                "event": "text",
                                "phase": phase,
                                "content": block.text[:200],
                                "length": len(block.text),
                            }
                        )

                    elif isinstance(block, ThinkingBlock):
                        thinking_entry = {
                            "content": block.thinking,
                            "signature": block.signature,
                            "length": len(block.thinking),
                        }
                        thinking_blocks.append(thinking_entry)

                        # Stream thinking (but don't log each one)
                        self._stream(
                            {
                                "type": "claude_code",
                                "event": "thinking",
                                "phase": phase,
                                "preview": block.thinking[:300],
                                "length": len(block.thinking),
                            }
                        )

                    elif isinstance(block, ToolUseBlock):
                        tool_entry = {"name": block.name, "id": block.id, "input": block.input}
                        tool_uses.append(tool_entry)

                        # Stream tool usage (but don't log each one)
                        self._stream(
                            {
                                "type": "claude_code",
                                "event": "tool_use",
                                "phase": phase,
                                "tool": block.name,
                                "input": self._sanitize_tool_input(block.input),
                            }
                        )

            elif isinstance(message, ResultMessage):
                # Update metadata
                self.generation_metadata["thinking_blocks"].extend(thinking_blocks)
                self.generation_metadata["tool_uses"].extend(tool_uses)
                self.generation_metadata["total_thinking_tokens"] += sum(
                    t["length"] for t in thinking_blocks
                )

                # Store cost and performance data
                if message.total_cost_usd:
                    current_cost = self.generation_metadata.get("cost_usd", 0.0)
                    self.generation_metadata["cost_usd"] = current_cost + message.total_cost_usd

                self.generation_metadata["duration_ms"] = message.duration_ms
                self.generation_metadata["turns"] = message.num_turns

                # Stream completion
                self._stream(
                    {
                        "type": "claude_code",
                        "event": "phase_complete",
                        "phase": phase,
                        "cost_usd": message.total_cost_usd,
                        "duration_ms": message.duration_ms,
                    }
                )

                break

        return response_text.strip()

    def _looks_like_python_code(self, text: str) -> bool:
        """Check if text appears to be Python code without markdown formatting.

        Args:
            text: Text to check

        Returns:
            True if text appears to be Python code
        """
        # Check for common Python patterns
        python_indicators = [
            "import ",
            "from ",
            "def ",
            "class ",
            "if __name__",
            "results = ",
            "print(",
        ]

        # Must have at least 2 indicators
        indicator_count = sum(1 for indicator in python_indicators if indicator in text)

        # Check if it's wrapped in markdown code blocks (we handle those separately)
        has_code_blocks = "```" in text

        # If it has code blocks, return False (let normal extraction handle it)
        # If it has enough Python indicators and no code blocks, it's likely raw Python
        return indicator_count >= 2 and not has_code_blocks

    def _extract_code_from_text(self, text: str) -> str | None:
        """Extract Python code from text.

        Searches for code blocks in the response text using multiple patterns
        to handle various formatting styles.

        Args:
            text: Response text from Claude

        Returns:
            Extracted code or None if no code found
        """
        # Python code blocks
        matches = re.findall(r"```python\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
        if matches:
            return matches[-1].strip()

        # Generic code blocks
        matches = re.findall(r"```\n(.*?)\n```", text, re.DOTALL)
        for match in matches:
            if "import " in match or "def " in match:
                return match.strip()

        return None

    def _clean_generated_code(self, raw_code: str) -> str:
        """Clean generated code.

        Removes markdown formatting if present and normalizes whitespace.

        Args:
            raw_code: Raw extracted code

        Returns:
            Cleaned Python code
        """
        cleaned = raw_code.strip()

        # Remove markdown if present
        markdown_pattern = r"^```\s*python\s*\n(.*?)\n```$"
        match = re.match(markdown_pattern, cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()

        return cleaned

    def _serialize_message_for_history(self, message: Any) -> dict[str, Any]:
        """Serialize a Message object to JSON-serializable format for conversation history.

        Captures EVERYTHING: text, thinking, tool uses, tool results, metadata, etc.

        Args:
            message: Any Message type from Claude SDK (AssistantMessage, UserMessage, etc.)

        Returns:
            JSON-serializable dict with complete message details
        """
        import datetime

        result = {
            "type": type(message).__name__,
            "timestamp": datetime.datetime.now().isoformat(),
        }

        if isinstance(message, AssistantMessage):
            result["role"] = "assistant"
            result["model"] = message.model
            result["content"] = []
            for block in message.content:
                if isinstance(block, TextBlock):
                    result["content"].append({
                        "type": "text",
                        "text": block.text
                    })
                elif isinstance(block, ThinkingBlock):
                    result["content"].append({
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": block.signature
                    })
                elif isinstance(block, ToolUseBlock):
                    result["content"].append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })
            # Capture additional metadata
            if message.parent_tool_use_id:
                result["parent_tool_use_id"] = message.parent_tool_use_id
            if message.error:
                result["error"] = {
                    "type": message.error.type,
                    "message": message.error.message
                }

        elif isinstance(message, UserMessage):
            result["role"] = "user"
            # UserMessage.content can be a string or list of ContentBlocks
            if isinstance(message.content, str):
                result["content"] = [{
                    "type": "text",
                    "text": message.content
                }]
            else:
                result["content"] = []
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result["content"].append({
                            "type": "text",
                            "text": block.text
                        })
                    elif isinstance(block, ToolResultBlock):
                        result["content"].append({
                            "type": "tool_result",
                            "tool_use_id": block.tool_use_id,
                            "content": block.content,
                            "is_error": block.is_error
                        })
            # Also capture parent_tool_use_id if present
            if message.parent_tool_use_id:
                result["parent_tool_use_id"] = message.parent_tool_use_id

        elif isinstance(message, SystemMessage):
            result["role"] = "system"
            result["subtype"] = message.subtype
            result["data"] = message.data

        elif isinstance(message, ResultMessage):
            result["role"] = "result"
            result["result_data"] = {
                "subtype": message.subtype,
                "is_error": message.is_error,
                "num_turns": message.num_turns,
                "duration_ms": message.duration_ms,
                "total_cost_usd": message.total_cost_usd,
                "result": message.result
            }
        else:
            # Unknown message type - capture what we can
            result["raw"] = str(message)

        return result

    def _sanitize_tool_input(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Sanitize tool input for streaming (remove sensitive or verbose data).

        Args:
            tool_input: Raw tool input from Claude

        Returns:
            Sanitized version safe for streaming
        """
        # For now, just limit string lengths and remove large content
        sanitized = {}
        for key, value in tool_input.items():
            if isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + "..."
            else:
                sanitized[key] = value
        return sanitized

    def _format_tool_input_for_log(self, tool_input: dict[str, Any]) -> str:
        """Format tool input for readable logging.

        Args:
            tool_input: Tool input dictionary

        Returns:
            Human-readable string representation
        """
        # Common tool patterns
        if "target_file" in tool_input:
            # Read/Grep tools
            file_path = tool_input.get("target_file", "")
            if "pattern" in tool_input:
                # Grep
                pattern = tool_input.get("pattern", "")[:50]
                return f"searching '{pattern}' in {file_path}"
            else:
                # Read
                return f"reading {file_path}"
        elif "glob_pattern" in tool_input:
            # Glob tool
            pattern = tool_input.get("glob_pattern", "")
            return f"finding files matching '{pattern}'"
        elif "path" in tool_input:
            # Generic path-based tool
            return f"path={tool_input.get('path', '')}"
        else:
            # Generic representation
            parts = []
            for key, value in tool_input.items():
                if isinstance(value, str):
                    parts.append(f"{key}={value[:50]}")
                else:
                    parts.append(f"{key}={value}")
            return ", ".join(parts[:3])  # Limit to 3 params

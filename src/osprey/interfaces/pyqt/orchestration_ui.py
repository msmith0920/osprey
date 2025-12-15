"""Orchestration UI Handler for Osprey Framework GUI.

This module handles the display and management of multi-project orchestrated queries.
"""

from typing import List
from PyQt5.QtWidgets import QApplication
from osprey.utils.logger import get_logger

logger = get_logger("orchestration_ui")


class OrchestrationUIHandler:
    """Handles orchestration UI display and event management."""
    
    def __init__(self, parent_gui):
        """
        Initialize the orchestration UI handler.
        
        Args:
            parent_gui: Reference to the main OspreyGUI instance
        """
        self.gui = parent_gui
    
    def display_orchestration_plan(self, plan):
        """
        Display orchestration plan to user.
        
        Args:
            plan: OrchestrationPlan to display
        """
        # Display header
        self.gui._append_colored_message(
            "\n🎯 Multi-Project Query Detected",
            "#00FFFF"
        )
        
        # Display reasoning
        if plan.reasoning:
            self.gui._append_colored_message(
                f"   Reason: {plan.reasoning}",
                "#808080"
            )
        
        # Display sub-queries
        self.gui._append_colored_message(
            f"   Decomposed into {len(plan.sub_queries)} sub-queries:",
            "#FFFFFF"
        )
        
        # Add separator
        self.gui._append_colored_message("─" * 60, "#404040")
    
    def handle_orchestrated_query(self, query: str, plan, enabled_projects: List):
        """
        Handle a multi-project orchestrated query using background worker.
        
        Args:
            query: Original user query
            plan: OrchestrationPlan from analysis
            enabled_projects: List of enabled projects
        """
        try:
            # Display orchestration plan
            self.display_orchestration_plan(plan)
            
            # Create project contexts dictionary
            project_contexts = {
                p.metadata.name: p for p in enabled_projects
            }
            
            # Display start message
            self.gui._append_colored_message(
                "🔄 Executing multi-project orchestration...",
                "#00FFFF"
            )
            
            # Import here to avoid circular dependency
            from osprey.interfaces.pyqt.orchestration_worker import OrchestrationWorker
            
            # Create and configure orchestration worker
            self.gui.orchestration_worker = OrchestrationWorker(
                plan,
                project_contexts,
                self.gui.base_config,
                self.gui.router
            )
            
            # Connect signals
            self.gui.orchestration_worker.sub_query_start.connect(self.on_sub_query_start)
            self.gui.orchestration_worker.sub_query_complete.connect(self.on_sub_query_complete)
            self.gui.orchestration_worker.sub_query_error.connect(self.on_sub_query_error)
            self.gui.orchestration_worker.synthesis_start.connect(self.on_synthesis_start)
            self.gui.orchestration_worker.final_result.connect(self.on_orchestration_result)
            self.gui.orchestration_worker.processing_complete.connect(self.gui.on_processing_complete)
            self.gui.orchestration_worker.error_occurred.connect(self.gui.on_error)
            
            # Start worker thread - runs asynchronously without blocking GUI
            self.gui.orchestration_worker.start()
            
            # Process events to ensure GUI remains responsive
            QApplication.processEvents()
            
        except Exception as e:
            logger.error(f"Orchestration setup failed: {e}")
            self.gui._append_colored_message(
                f"⚠️ Orchestration error: {e}",
                "#FF0000"
            )
            self.gui.add_status(f"Orchestration error: {e}", "error")
            
            # Mark agent as no longer processing
            self.gui._agent_processing = False
            
            # Re-enable input
            self.gui.input_field.setEnabled(True)
            self.gui.send_button.setEnabled(True)
    
    def on_sub_query_start(self, index: int, project_name: str, query: str):
        """
        Handle sub-query start event.
        
        Args:
            index: Index of the sub-query
            project_name: Name of the project handling this sub-query
            query: The sub-query text
        """
        # Add visual separator (except before first one)
        if index > 0:
            self.gui._append_colored_message("", "#FFFFFF")
        
        self.gui._append_colored_message(
            f"  {index + 1}. [{project_name}] {query}",
            "#FFD700"
        )
        self.gui._append_colored_message(f"     ⏳ Processing...", "#808080")
        QApplication.processEvents()
    
    def on_sub_query_complete(self, index: int, result: str):
        """
        Handle sub-query completion event.
        
        Args:
            index: Index of the completed sub-query
            result: Result of the sub-query
        """
        self.gui._append_colored_message(f"     ✅ Complete", "#00FF00")
        QApplication.processEvents()
    
    def on_sub_query_error(self, index: int, error_msg: str):
        """
        Handle sub-query error event.
        
        Args:
            index: Index of the failed sub-query
            error_msg: Error message
        """
        self.gui._append_colored_message(f"     ❌ {error_msg}", "#FF0000")
        QApplication.processEvents()
    
    def on_synthesis_start(self):
        """Handle synthesis start event."""
        self.gui._append_colored_message(
            "\n🔗 Synthesizing results...",
            "#00FFFF"
        )
        QApplication.processEvents()
    
    def on_orchestration_result(self, combined_result: str):
        """
        Handle final orchestration result.
        
        Args:
            combined_result: The synthesized result from all sub-queries
        """
        # Save to conversation history
        if self.gui.current_conversation_id:
            # Use ConversationManager to add message
            self.gui.conversation_manager.add_message(
                self.gui.current_conversation_id,
                'agent',
                combined_result
            )
            self.gui.update_conversation_list()
            self.gui.save_conversation_history()
        
        # Display final answer
        self.gui._append_colored_message(
            "\n" + "=" * 60,
            "#404040"
        )
        self.gui._append_colored_message(
            "\n🤖 Combined Answer:",
            "#00FF00"
        )
        self.gui._append_colored_message(
            combined_result,
            "#FFFFFF"
        )
        self.gui._append_colored_message(
            "\n" + "=" * 60,
            "#404040"
        )
        QApplication.processEvents()
"""
llm_judge.py

LLM-based judge for detecting errors and recommending interventions in multi-agent systems.
Uses the error taxonomy to classify issues and trigger appropriate interventions.
"""

import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_openai import AzureChatOpenAI
import os

from ...core.dig import InteractionLog, InteractionEvent, build_activation_event_graph
from .intervention import inject_system_message, create_system_event


# ============================================================================
# Load Error Taxonomy
# ============================================================================

def load_error_taxonomy() -> str:
    """Load error taxonomy from markdown file."""
    taxonomy_path = os.path.join(
        os.path.dirname(__file__), 
        "..", 
        "error_taxonomy.md"
    )
    try:
        with open(taxonomy_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        # Fallback if file not found
        return "Error taxonomy file not found. Using basic taxonomy."


# ============================================================================
# Pydantic Models for Structured Output
# ============================================================================

class ErrorDetection(BaseModel):
    """Detected error in the multi-agent system."""
    error_type: str = Field(
        description="Error type from taxonomy: early_termination, missing_completion, "
                    "orphaned_event, deadlock, partial_aggregation, repeated_rerouting, "
                    "cross_lineage_aggregation, repeated_subproblem_solving"
    )
    severity: str = Field(
        description="Severity: critical, high, medium, low"
    )
    description: str = Field(
        description="Human-readable explanation of the error"
    )
    affected_agents: Optional[List[str]] = Field(
        default=None,
        description="Agents involved in this error"
    )
    affected_event_ids: Optional[List[str]] = Field(
        default=None,
        description="Event IDs involved in this error"
    )
    affected_activation_ids: Optional[List[str]] = Field(
        default=None,
        description="Activation IDs involved in this error"
    )


class InterventionRecommendation(BaseModel):
    """Recommendation for system intervention."""
    should_intervene: bool = Field(
        description="Whether to apply intervention"
    )
    intervention_method: str = Field(
        description="Method: inject_system_message or create_system_event"
    )
    target_agents: List[str] = Field(
        description="Agents to target with intervention"
    )
    message: str = Field(
        description="Intervention message content"
    )
    inject_event_ids: Optional[List[str]] = Field(
        default=None,
        description="Event IDs to inject message into (for inject_system_message only)"
    )
    reroute_events: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="event_id -> new_recipients mapping (for inject_system_message only)"
    )
    reasoning: str = Field(
        description="Explanation for intervention recommendation"
    )


class LLMJudgeAnalysis(BaseModel):
    """Complete analysis output from LLM judge."""
    detected_errors: List[ErrorDetection] = Field(
        default_factory=list,
        description="All detected errors"
    )
    interventions: List[InterventionRecommendation] = Field(
        default_factory=list,
        description="Intervention recommendations"
    )
    overall_assessment: str = Field(
        description="Overall system health summary"
    )


# ============================================================================
# LLM Judge System Prompt
# ============================================================================

def get_llm_judge_system_prompt() -> str:
    """Generate system prompt with loaded error taxonomy."""
    taxonomy = load_error_taxonomy()
    
    return f"""You are an expert system monitor for multi-agent cooperative systems. Your role is to analyze the Dynamic Interaction Graph (DIG) and detect errors based on a formal error taxonomy.

{taxonomy}

## Your Task

Analyze the DIG summary and:
1. Identify errors using the taxonomy above
2. Assess severity (critical/high/medium/low)
3. Recommend conservative interventions only when necessary
4. Provide clear reasoning for your decisions

## Intervention Methods

- **inject_system_message**: Add guidance to existing event and optionally reroute to different agents
- **create_system_event**: Create new intervention event with message to specific agents

## Principles

- Be conservative: only intervene when error is clear and intervention helps
- Prioritize FAILURES over RISKS
- Provide actionable, specific recommendations
- Respect agent autonomy where appropriate
"""


# ============================================================================
# LLM Judge Implementation
# ============================================================================

class LLMJudge:
    """LLM-based judge for multi-agent error detection and intervention."""
    
    def __init__(
        self,
        check_interval_activations: int = 5,
        enable_intervention: bool = True,
        model_name: str = None,
    ):
        """
        Initialize LLM judge.
        
        Args:
            check_interval_activations: Check system every N activations
            enable_intervention: Whether to apply interventions or just detect
            model_name: Azure OpenAI model name (defaults to env var)
        """
        self.check_interval = check_interval_activations
        self.enable_intervention = enable_intervention
        self.last_check_activation = 0
        
        # Initialize LLM client
        self.llm = AzureChatOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            azure_deployment=model_name or os.getenv("AZURE_OPENAI_MODEL", "gpt-5-chat"),
            temperature=0.0,
        )
    
    def should_check(self, dig: InteractionLog) -> bool:
        """Determine if it's time to run analysis."""
        current_activations = len(dig.activations)
        if current_activations - self.last_check_activation >= self.check_interval:
            return True
        return False
    
    def build_dig_summary(self, dig: InteractionLog) -> Dict[str, Any]:
        """Build concise DIG summary for LLM analysis."""
        # Get recent activations (last 50)
        recent_activations = []
        for aid, activation in list(dig.activations.items())[-50:]:
            recent_activations.append({
                "id": aid,
                "agent": activation.agent_name,
                "mode": str(activation.mode),
                "input_events": activation.input_event_ids,
                "output_events": activation.output_event_ids,
                "unconsumed_events": activation.unconsumed_event_ids,
                "timestamp": activation.started_at,
                "reasoning": activation.reasoning[:200] if activation.reasoning else None,
                "input_actions": activation.input_actions,
            })
        
        # Get recent events (last 50)
        recent_events = []
        for eid, event in list(dig.events.items())[-50:]:
            recent_events.append({
                "id": eid,
                "source_activation": event.source_activation_id,
                "recipients": event.recipients,
                "deleted_recipients": event.deleted_recipients,
                "rerouted_recipients": list(event.rerouted_recipients.keys()),
                "timestamp": event.generated_at,
                "has_system_annotation": event.system_annotation is not None,
                "payload_type": event.payload.get("type") if event.payload else None,
                "info_type": event.info.get("type") if event.info else None,
            })
        
        return {
            "total_activations": len(dig.activations),
            "total_events": len(dig.events),
            "recent_activations": recent_activations,
            "recent_events": recent_events,
            "detection_stats": dict(dig.detection_stats),
            "intervention_stats": dict(dig.intervention_stats),
        }
    
    async def analyze(self, dig: InteractionLog) -> LLMJudgeAnalysis:
        """
        Analyze DIG and return structured error detection and intervention recommendations.
        
        Args:
            dig: The DIG to analyze
            
        Returns:
            Structured analysis with detected errors and intervention recommendations
        """
        # Build DIG summary
        dig_summary = self.build_dig_summary(dig)
        
        # Create prompt
        user_prompt = f"""Analyze this multi-agent system state and detect errors using the error taxonomy.

DIG Summary:
```json
{dig_summary}
```

Provide structured analysis with:
1. All detected errors (type, severity, description, affected entities)
2. Conservative intervention recommendations (only when necessary)
3. Overall system health assessment

Focus on FAILURES first (early_termination, missing_completion, orphaned_event, deadlock), then RISKS if relevant.
"""
        
        # Call LLM with structured output
        start_time = time.time()
        
        messages = [
            {"role": "system", "content": get_llm_judge_system_prompt()},
            {"role": "user", "content": user_prompt}
        ]
        
        structured_llm = self.llm.with_structured_output(LLMJudgeAnalysis)
        analysis = await structured_llm.ainvoke(messages)
        
        elapsed = time.time() - start_time
        
        # Track LLM usage
        dig.record_llm_usage(total_tokens=0)  # Would need to extract from response metadata
        
        print(f"[LLM-JUDGE] Analysis complete in {elapsed:.2f}s")
        print(f"  Detected {len(analysis.detected_errors)} errors")
        print(f"  Recommends {len(analysis.interventions)} interventions")
        print(f"  Assessment: {analysis.overall_assessment}")
        
        return analysis
    
    async def analyze_and_intervene(
        self,
        dig: InteractionLog,
        all_agents: Dict[str, Any],
    ) -> LLMJudgeAnalysis:
        """
        Analyze DIG and apply interventions if enabled.
        
        Args:
            dig: The DIG to analyze
            all_agents: Dictionary of all agents in the system
            
        Returns:
            Analysis results
        """
        # Create system activation to track this analysis
        system_start = time.time()
        system_activation = dig.record_activation(
            agent_name="system",
            mode="llm_judge_analysis",
            input_events=[],
            output_events=[],
            started_at=system_start,
            ended_at=system_start,  # Will update after analysis
            intervention_type="llm_judge_analysis",
        )
        
        # Run analysis
        analysis = await self.analyze(dig)
        
        # Update system activation end time
        system_activation.ended_at = time.time()
        
        # Record detections
        for error in analysis.detected_errors:
            dig.record_detection(error.error_type)
            print(f"  ERROR [{error.severity}] {error.error_type}: {error.description}")
        
        # Apply interventions if enabled
        if self.enable_intervention:
            for intervention in analysis.interventions:
                if not intervention.should_intervene:
                    continue
                
                print(f"  INTERVENTION: {intervention.intervention_method} → {intervention.target_agents}")
                print(f"    Reasoning: {intervention.reasoning}")
                
                dig.record_intervention(intervention.intervention_method)
                
                if intervention.intervention_method == "inject_system_message":
                    # Inject message into specified events
                    inject_event_ids = intervention.inject_event_ids or []
                    reroute_events = intervention.reroute_events or {}
                    
                    for event_id in inject_event_ids:
                        event = dig.events.get(event_id)
                        if event:
                            reroute_to = reroute_events.get(event_id)
                            inject_system_message(
                                event=event,
                                message=intervention.message,
                                intervention_type="llm_judge",
                                reroute_to=reroute_to,
                                system_activation_id=system_activation.id,
                            )
                            
                            if reroute_to:
                                print(f"    Rerouted event {event_id} to {reroute_to}")
                                # Deliver rerouted event to agents
                                for agent_name in reroute_to:
                                    if agent_name in all_agents:
                                        await all_agents[agent_name].add_to_buffer(event)
                
                elif intervention.intervention_method == "create_system_event":
                    # Create new system intervention event
                    system_act, new_event = create_system_event(
                        dig=dig,
                        message=intervention.message,
                        intervention_type="llm_judge",
                        recipients=intervention.target_agents,
                    )
                    print(f"    Created system event {new_event.id} for {intervention.target_agents}")
                    
                    # Deliver to target agents
                    for agent_name in intervention.target_agents:
                        if agent_name in all_agents:
                            await all_agents[agent_name].add_to_buffer(new_event)
        
        # Update last check
        self.last_check_activation = len(dig.activations)
        
        return analysis


# ============================================================================
# Integration Helper
# ============================================================================

async def check_llm_judge(
    dig: InteractionLog,
    judge: LLMJudge,
    all_agents: Dict[str, Any],
) -> Optional[LLMJudgeAnalysis]:
    """
    Check if LLM judge should run and execute if needed.
    
    Args:
        dig: The DIG
        judge: LLM judge instance
        all_agents: Dictionary of all agents
        
    Returns:
        Analysis results if check was performed, None otherwise
    """
    if not judge.should_check(dig):
        return None
    
    print(f"\n[LLM-JUDGE] Starting analysis at {len(dig.activations)} activations...")
    analysis = await judge.analyze_and_intervene(dig, all_agents)
    
    return analysis

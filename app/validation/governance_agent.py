"""
Governance Agent — LangGraph StateGraph for Layer 2 validation.

Receives the deterministic Layer 1 GovernanceResult and dynamically
reasons about:
  - Precedent decisions (vector search)
  - Governance gaps (graph traversal)
  - Goal conflicts
  - Verdict and confidence

Pattern follows app/onboarding/onboarding_graph.py: StateGraph with
typed state, tool nodes, and conditional edges.

Usage
-----
    from app.validation.governance_agent import run_governance_agent

    result = await run_governance_agent(
        company_id="nexus_analytics",
        decision_text="Hire 3 engineers at $150K each",
        decision_payload={...},
        governance_result=gov_result.to_dict(),
        risk_scoring=risk_result,
        graph_context=graph_ctx,
        repo=repo,
    )
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from app.config.llm import get_llm
from app.graph.base import BaseGraphRepository
from app.validation.schemas import (
    ValidationResult,
    ValidationState,
    _VALID_VERDICTS,
)
from app.validation.tools import create_tools

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a governance agent for enterprise AI decision validation.

Your role: given a proposed AI decision and its initial governance analysis, determine:
1. Whether the decision should be APPROVED, REJECTED, ESCALATED, or REVIEWED
2. What governance gaps exist
3. What precedent decisions are most relevant
4. A clear reasoning explanation for the decision-maker

You have access to tools to query the governance knowledge graph, find similar past \
decisions, and check for governance gaps.

Rules:
- Always check for similar past decisions before making a verdict
- Always check for governance gaps in triggered rules
- Review the Layer 1 analysis which already identifies triggered rules and approval \
requirements. Use tools only for additional context not already provided.
- When calling search_governance_rules, ALWAYS pass the triggered rule IDs from the \
Layer 1 result as rule_ids -- never call it without rule_ids (fetching all rules wastes \
context and causes token overflow).
- APPROVE only if all rules are satisfied and confidence > 0.85
- REJECT only if rules are clearly violated with no remediation path
- ESCALATE when critical compliance rules are triggered or higher authority sign-off \
is needed based on the Layer 1 approval chain
- REVIEW for uncertain cases, partial rule satisfaction, or detected gaps
- Be concise in reasoning -- 2-4 sentences

Verdict definitions:
- APPROVE: decision is compliant, all approvals in place
- REJECT: decision violates governance rules, cannot proceed
- ESCALATE: decision needs higher authority sign-off
- REVIEW: decision needs human review before proceeding

After your analysis, end your response with EXACTLY this JSON block (use the key name \
"verdict", not "decision" or "action"):
```json
{
  "verdict": "APPROVE",
  "confidence": 0.85,
  "reasoning": "2-4 sentence explanation for the decision-maker"
}
```
Replace the example values. Use one of: APPROVE, REJECT, ESCALATE, REVIEW.
"""

# ---------------------------------------------------------------------------
# Max tool-calling rounds (prevents infinite loops)
# ---------------------------------------------------------------------------

_MAX_TOOL_ROUNDS = int(os.getenv("GOVERNANCE_AGENT_MAX_ROUNDS", "3"))
_MAX_CONTEXT_CHARS = 1000
_MAX_RULE_TEXT_CHARS = 500

# ---------------------------------------------------------------------------
# Lazily-cached LLM client (P1: avoid re-creating per request)
# ---------------------------------------------------------------------------

_llm_capable = None
_llm_factory_id = None


def _get_llm_capable():
    """
    Return a cached 'capable' tier LLM client, creating on first use.

    The cache is invalidated if `get_llm` is replaced (e.g. by a test mock),
    which is detected by comparing the id of the current `get_llm` function
    against the id stored when the cache was populated.
    """
    global _llm_capable, _llm_factory_id
    current_factory_id = id(get_llm)
    if _llm_capable is None or _llm_factory_id != current_factory_id:
        _llm_capable = get_llm("capable")
        _llm_factory_id = current_factory_id
    return _llm_capable


def _reset_llm_cache() -> None:
    """Reset cached LLM client. Call between tests that patch get_llm."""
    global _llm_capable, _llm_factory_id
    _llm_capable = None
    _llm_factory_id = None


# ---------------------------------------------------------------------------
# Graph cache — avoid recompiling StateGraph on every request
# ---------------------------------------------------------------------------

_graph_cache: dict[int, Any] = {}


def _get_or_build_graph(repo: BaseGraphRepository) -> Any:
    """Return a cached compiled graph for the given repo instance."""
    key = id(repo)
    if key not in _graph_cache:
        _graph_cache[key] = build_governance_agent(repo)
    return _graph_cache[key]


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_governance_agent(repo: BaseGraphRepository):
    """
    Build and compile the LangGraph governance agent.

    Args:
        repo: Graph repository for tool queries (Neo4j or InMemory).

    Returns:
        Compiled LangGraph app (call .ainvoke() to run).
    """
    llm = _get_llm_capable()
    tools = create_tools(repo)
    llm_with_tools = llm.bind_tools(tools)

    # --- Node functions ---

    async def agent_node(state: ValidationState) -> dict:
        """LLM reasoning node -- may call tools or produce final verdict."""
        messages = list(state.get("messages", []))

        # On first call, inject system prompt and decision context
        if not messages:
            messages = _build_initial_messages(state)

        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    async def synthesize_node(state: ValidationState) -> dict:
        """
        Extract verdict/confidence/reasoning from the final AI message
        and write to state.
        """
        messages = state.get("messages", [])
        verdict, confidence, reasoning = _extract_verdict_from_messages(messages)

        # Extract precedent and gap info from tool call results
        precedent_decisions = _extract_precedents_from_messages(messages)
        governance_gaps = _extract_gaps_from_messages(messages)

        return {
            "verdict": verdict,
            "confidence": confidence,
            "agent_reasoning": reasoning,
            "precedent_decisions": precedent_decisions,
            "governance_gaps": governance_gaps,
        }

    # --- Conditional edge: should we call tools or synthesize? ---

    def should_continue(state: ValidationState) -> str:
        """Decide whether to call tools, synthesize, or loop back."""
        messages = state.get("messages", [])
        if not messages:
            return "synthesize"

        last_message = messages[-1]

        # Count how many tool rounds we've done
        tool_rounds = sum(
            1 for m in messages
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
        )

        # If last message has tool calls and we haven't exceeded max rounds
        if (
            isinstance(last_message, AIMessage)
            and getattr(last_message, "tool_calls", None)
            and tool_rounds < _MAX_TOOL_ROUNDS
        ):
            return "tools"

        return "synthesize"

    # --- Build the graph ---

    graph = StateGraph(ValidationState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "synthesize": "synthesize"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("synthesize", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


async def run_governance_agent(
    company_id: str,
    decision_text: str,
    decision_payload: dict,
    governance_result: dict,
    risk_scoring: Optional[dict],
    graph_context: Optional[dict],
    repo: BaseGraphRepository,
    external_signals: Optional[dict] = None,
) -> ValidationResult:
    """
    Run the governance agent and return a ValidationResult.

    Non-fatal: returns a default ValidationResult on any error.
    """
    try:
        agent = _get_or_build_graph(repo)
        initial_state: ValidationState = {
            "company_id": company_id,
            "decision_text": decision_text,
            "decision_payload": decision_payload,
            "governance_result": governance_result,
            "risk_scoring": risk_scoring,
            "graph_context": graph_context,
            "precedent_decisions": [],
            "governance_gaps": [],
            "goal_impacts": [],
            "agent_reasoning": "",
            "verdict": "REVIEW",
            "confidence": 0.5,
            "messages": [],
            "external_signals": external_signals,
            "error": None,
        }
        final_state = await agent.ainvoke(
            initial_state,
            config={"recursion_limit": 15},
        )
        return ValidationResult(
            verdict=final_state.get("verdict", "REVIEW"),
            confidence=final_state.get("confidence", 0.5),
            agent_reasoning=final_state.get("agent_reasoning", ""),
            precedent_decisions=final_state.get("precedent_decisions", []),
            governance_gaps=final_state.get("governance_gaps", []),
            goal_impacts=final_state.get("goal_impacts", []),
            triggered_rule_ids=[
                r.get("rule_id", "")
                for r in governance_result.get("triggered_rules", [])
                if r.get("status") == "TRIGGERED"
            ],
            approval_chain=governance_result.get("approval_chain", []),
        )
    except Exception as exc:
        logger.error("Governance agent failed: %s", exc, exc_info=True)
        return ValidationResult(
            verdict="REVIEW",
            confidence=0.3,
            agent_reasoning=f"Agent error -- defaulting to REVIEW: {str(exc)[:200]}",
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_initial_messages(state: ValidationState) -> list:
    """Build the initial message list for the agent's first call."""
    gov = state.get("governance_result", {})
    risk = state.get("risk_scoring")
    ctx = state.get("graph_context")

    context_parts = [
        f"Company: {state['company_id']}",
        f"Decision: {state['decision_text']}",
        "",
        "--- Layer 1 Governance Result ---",
        f"Triggered rules: {json.dumps(gov.get('triggered_rules', []), default=str)[:_MAX_CONTEXT_CHARS]}",
        f"Flags: {gov.get('flags', [])}",
        f"Requires human review: {gov.get('requires_human_review', False)}",
        f"Approval chain: {json.dumps(gov.get('approval_chain', []), default=str)[:_MAX_RULE_TEXT_CHARS]}",
    ]

    if risk:
        agg = risk.get("aggregate", {})
        context_parts.extend([
            "",
            "--- Risk Scoring ---",
            f"Aggregate: score={agg.get('score', 'N/A')}, band={agg.get('band', 'N/A')}",
        ])

    if ctx:
        meta = ctx.get("metadata", {})
        context_parts.extend([
            "",
            "--- Graph Context ---",
            f"Nodes: {meta.get('node_count', 0)}, Edges: {meta.get('edge_count', 0)}",
        ])

    # External signals context (from Tavily live search or curated fallback)
    ext = state.get("external_signals")
    if ext and isinstance(ext, dict):
        market = ext.get("marketSignals", [])
        regulatory = ext.get("regulatorySignals", [])
        operational = ext.get("operationalSignals", [])
        adjustments = ext.get("riskAdjustments", [])

        all_sigs = (market + regulatory + operational)[:4]
        if all_sigs:
            context_parts.extend(["", "--- External Market & Regulatory Context ---"])
            for sig in all_sigs:
                context_parts.append(
                    f"- [{(sig.get('category') or '').upper()}] "
                    f"{sig.get('title', '')}: {sig.get('summary', '')} "
                    f"— {sig.get('decisionRelevance', '')}"
                )
            if adjustments:
                context_parts.append("\nExternal signals have adjusted risk scores:")
                for adj in adjustments:
                    delta = adj.get("delta", 0)
                    sign = "+" if delta > 0 else ""
                    context_parts.append(
                        f"  - {(adj.get('dimension') or '').capitalize()}: "
                        f"{sign}{delta} pts — {adj.get('rationale', '')}"
                    )

    context_text = "\n".join(context_parts)

    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Analyze this decision and determine the appropriate governance verdict.\n\n"
            f"{context_text}\n\n"
            f"Use the available tools to search for similar past decisions, check for "
            f"governance gaps, and gather any additional context needed. Then provide "
            f"your verdict."
        )),
    ]


def _extract_verdict_from_messages(messages: list) -> tuple[str, float, str]:
    """
    Extract verdict, confidence, and reasoning from the final AI message.

    Looks for a JSON block in the last AI message. Falls back to REVIEW
    if parsing fails.
    """
    default = ("REVIEW", 0.5, "Unable to extract verdict from agent response")

    # Find the last AI message (non-tool-call)
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            return _parse_verdict_json(content)

    # Fallback: take the last AIMessage even if it has tool_calls
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            logger.warning(
                "No clean AI message found for verdict extraction; "
                "falling back to last AIMessage (which has tool_calls)"
            )
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content:
                return _parse_verdict_json(content)
            break

    logger.warning(
        "No AI message found in conversation for verdict extraction; "
        "returning default REVIEW verdict"
    )
    return default


def _parse_verdict_json(text: str) -> tuple[str, float, str]:
    """Parse a verdict JSON block from text."""
    default = ("REVIEW", 0.5, text[:_MAX_RULE_TEXT_CHARS] if text else "No response")

    # 1. Try direct json.loads on the entire text
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "verdict" in data:
            return _extract_from_dict(data, text)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # 2. Try to find JSON in fenced code block
    json_str = None
    if "```json" in text:
        parts = text.split("```json")
        if len(parts) > 1:
            json_part = parts[-1].split("```")[0]
            json_str = json_part.strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            json_str = parts[1].strip()

    # 3. Try to find outermost balanced braces containing "verdict"
    if json_str is None:
        json_str = _find_balanced_json(text)

    # 4. Regex fallback for simple (non-nested) JSON
    if json_str is None:
        match = re.search(r'\{[^{}]*"(?:verdict|decision|action)"[^{}]*\}', text, re.DOTALL)
        if match:
            json_str = match.group(0)

    if json_str is None:
        # No JSON found -- extract verdict from text
        return _extract_verdict_from_text(text)

    try:
        data = json.loads(json_str)
        return _extract_from_dict(data, text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return _extract_verdict_from_text(text)


_VERDICT_KEYS = ('"verdict"', '"decision"', '"action"')


def _find_balanced_json(text: str) -> Optional[str]:
    """
    Find the outermost balanced ``{...}`` block containing a verdict key.

    Accepts "verdict", "decision", or "action" to handle LLMs that deviate
    from the prompt schema.
    """
    start = None
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : i + 1]
                if any(k in candidate for k in _VERDICT_KEYS):
                    return candidate
                start = None
    return None


def _extract_from_dict(data: dict, text: str) -> tuple[str, float, str]:
    """Extract verdict/confidence/reasoning from a parsed dict."""
    used_key = next((k for k in ("verdict", "decision", "action") if k in data), None)
    if used_key and used_key != "verdict":
        logger.warning("LLM used '%s' instead of 'verdict' key — check system prompt", used_key)
    raw = data.get(used_key) if used_key else "REVIEW"
    verdict = str(raw).upper()
    if verdict not in _VALID_VERDICTS:
        verdict = "REVIEW"
    confidence = float(data.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))
    reasoning = str(data.get("reasoning") or data.get("summary") or data.get("justification") or data.get("agent_reasoning") or "")
    return verdict, confidence, reasoning


def _extract_verdict_from_text(text: str) -> tuple[str, float, str]:
    """Fallback: extract verdict from plain text."""
    upper = text.upper()
    for v in ["ESCALATE", "REJECT", "APPROVE", "REVIEW"]:
        if v in upper:
            return v, 0.5, text[:_MAX_RULE_TEXT_CHARS]
    return "REVIEW", 0.5, text[:_MAX_RULE_TEXT_CHARS]


def _extract_precedents_from_messages(messages: list) -> list[dict]:
    """Extract precedent decision data from tool call results."""
    precedents = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data[:5]:
                    if isinstance(item, dict) and "score" in item:
                        precedents.append({
                            "decision_id": item.get("id", ""),
                            "similarity_score": item.get("score", 0.0),
                            "label": item.get("label", ""),
                            "rules_triggered": [],
                            "outcome": item.get("outcome"),
                        })
        except (json.JSONDecodeError, TypeError):
            pass
    return precedents


def _extract_gaps_from_messages(messages: list) -> list[dict]:
    """Extract governance gap data from tool call results."""
    gaps = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data[:10]:
                    if isinstance(item, dict) and "gap_label" in item:
                        severity = item.get("severity", "medium")
                        gap_type = item.get("gap_type", "governance_config")
                        gaps.append({
                            "gap_type": gap_type,
                            "description": item.get("gap_label", ""),
                            "severity": severity,
                        })
        except (json.JSONDecodeError, TypeError):
            pass
    return gaps

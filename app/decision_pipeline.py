"""
Complete Decision Governance Pipeline

End-to-end flow:
1. Decision input
2. Governance evaluation (deterministic)
3. Graph storage
4. Graph reasoning with o1 (optional)
5. Decision Pack generation
"""

import asyncio
from typing import Optional
from app.schemas import Decision
from app.governance import evaluate_governance
from app.graph_repository import BaseGraphRepository, InMemoryGraphRepository
from app.graph_reasoning import analyze_decision_graph_with_o1, format_graph_insights_for_pack
from app.decision_pack import build_decision_pack


async def process_decision_with_graph_reasoning(
    decision: Decision,
    decision_id: Optional[str] = None,
    repository: Optional[BaseGraphRepository] = None,
    company_context: dict = None,
    use_o1_governance: bool = False,
    use_o1_graph: bool = True
) -> dict:
    """
    Complete decision governance pipeline with graph reasoning.

    Args:
        decision: Decision object to process
        decision_id: Optional decision ID (auto-generated if not provided)
        repository: Graph repository (InMemory if not provided)
        company_context: Company context for governance
        use_o1_governance: Use o1 for approval chain optimization
        use_o1_graph: Use o1 for graph contradiction analysis

    Returns:
        Complete decision pack with graph reasoning
    """
    if repository is None:
        repository = InMemoryGraphRepository()

    if company_context is None:
        company_context = {}

    if decision_id is None:
        import uuid
        decision_id = f"decision_{uuid.uuid4().hex[:8]}"

    # Step 1: Evaluate governance (deterministic + optional o1 for conflicts)
    print(f"[1/5] Evaluating governance (o1={use_o1_governance})...")
    governance_result = evaluate_governance(
        decision,
        company_context=company_context,
        use_o1=use_o1_governance
    )
    governance_dict = governance_result.to_dict()
    decision_dict = decision.model_dump()

    print(f"  ✓ Governance complete: {len(governance_dict['flags'])} flags, "
          f"{len(governance_dict['triggered_rules'])} rules")

    # Step 2: Store in graph
    print(f"[2/5] Storing decision in graph...")
    decision_graph = await repository.upsert_decision_graph(
        decision=decision_dict,
        governance=governance_dict,
        decision_id=decision_id
    )
    print(f"  ✓ Graph stored: {len(decision_graph.nodes)} nodes, {len(decision_graph.edges)} edges")

    # Step 3: Analyze graph with o1 (find contradictions, patterns, insights)
    print(f"[3/5] Analyzing graph for contradictions (o1={use_o1_graph})...")
    graph_insights = await analyze_decision_graph_with_o1(
        decision_id=decision_id,
        governance=governance_dict,
        repository=repository,
        decision_data=decision_dict,
        company_data=company_context,
        use_o1=use_o1_graph
    )
    formatted_insights = format_graph_insights_for_pack(graph_insights)

    contradictions = len(graph_insights.get("logical_analysis", []))
    recommendations = len(graph_insights.get("recommendations", []))
    print(f"  ✓ Graph analysis complete: {contradictions} contradictions, "
          f"{recommendations} recommendations")

    # Step 4: Build decision pack (template-based + graph insights)
    print(f"[4/5] Building Decision Pack...")
    decision_pack = build_decision_pack(
        decision=decision_dict,
        governance=governance_dict,
        company=company_context,
        graph_insights=formatted_insights
    )
    print(f"  ✓ Decision Pack built: status={decision_pack['summary']['governance_status']}")

    # Step 5: Return complete result
    print(f"[5/5] Complete!")
    return {
        "decision_id": decision_id,
        "decision_pack": decision_pack,
        "governance_result": governance_dict,
        "graph_metadata": {
            "nodes": len(decision_graph.nodes),
            "edges": len(decision_graph.edges),
            "analysis_method": graph_insights.get("analysis_method", "not_performed")
        }
    }


async def demo_pipeline():
    """
    Demo the complete pipeline with a sample decision.
    """
    from app.demo_fixtures import get_demo_fixture
    import json

    print("\n" + "="*80)
    print("DECISION GOVERNANCE PIPELINE - GRAPH REASONING DEMO")
    print("="*80 + "\n")

    # Test with budget violation (triggers multiple rules)
    decision = get_demo_fixture("budget_violation")

    result = await process_decision_with_graph_reasoning(
        decision=decision,
        use_o1_governance=False,  # Deterministic governance
        use_o1_graph=False  # Start with deterministic graph analysis
    )

    print("\n" + "="*80)
    print("DECISION PACK OUTPUT")
    print("="*80 + "\n")

    pack = result["decision_pack"]

    print(f"Title: {pack['title']}")
    print(f"\nStatus: {pack['summary']['governance_status']}")
    print(f"Risk Level: {pack['summary']['risk_level']}")
    print(f"Requires Review: {pack['summary']['human_approval_required']}")

    print(f"\nApproval Chain: {len(pack['approval_chain'])} steps")
    for step in pack['approval_chain']:
        print(f"  - {step['role']} ({'required' if step['required'] else 'optional'})")

    print(f"\nFlags: {len(pack['audit']['flags'])}")
    for flag in pack['audit']['flags']:
        print(f"  - {flag}")

    if "graph_reasoning" in pack:
        print(f"\n✨ Graph Reasoning Enabled:")
        print(f"  Method: {pack['graph_reasoning']['analysis_method']}")
        print(f"  Contradictions: {len(pack['graph_reasoning']['logical_contradictions'])}")
        print(f"  Recommendations: {len(pack['graph_reasoning']['graph_recommendations'])}")
        print(f"  Confidence: {pack['graph_reasoning']['confidence']}")

        if pack['graph_reasoning']['logical_contradictions']:
            print(f"\n  Contradictions Found:")
            for contra in pack['graph_reasoning']['logical_contradictions'][:3]:
                print(f"    - [{contra.get('severity', 'N/A')}] {contra.get('description', 'N/A')}")

    print("\n" + "="*80)

    # Show JSON output
    print("\nFull Decision Pack (JSON):")
    print(json.dumps(pack, indent=2))


if __name__ == "__main__":
    asyncio.run(demo_pipeline())

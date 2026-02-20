"""
Pipeline Service - Async orchestrator for the full governance pipeline.

Execution order (strict):
  1. LLM extraction           (extractor.extract)
  2. Governance evaluation    (governance.evaluate_governance)
  3. Graph upsert + retrieval (graph_repository)
  4. o1 Reasoning             (decision_pipeline — MANDATORY, graceful on API error)
  5. Decision Pack            (decision_pack.build_decision_pack)

Updates DecisionRecord at each step so the polling endpoint reflects progress.
Never raises — stores error and marks record failed.
"""

import asyncio
import logging
from typing import Optional

from app.repositories import decision_store
from app.services import company_service

logger = logging.getLogger(__name__)


async def run_pipeline(
    decision_id: str,
    extractor,
    graph_repo,
    use_o1_governance: bool = False,
    use_o1_graph: bool = False,
) -> None:
    """
    Full async pipeline. Designed to run as a BackgroundTask.

    Args:
        decision_id:      ID of the DecisionRecord to process
        extractor:        DecisionExtractor instance from app globals
        graph_repo:       InMemoryGraphRepository instance from app globals
        use_o1_governance: Use o1 for governance evaluation (default: False)
        use_o1_graph:     Use o1 for graph reasoning (default: False)
    """
    record = decision_store.get(decision_id)
    if not record:
        logger.error(f"[{decision_id}] Record not found — aborting pipeline")
        return

    try:
        # ── Step 1: Extraction ───────────────────────────────────────────────
        # current_step stays 0 (processing) while extraction runs.
        # Set to 1 AFTER extraction stores results → SSE emits "extraction_complete"
        # unlocking the entities panel only when data is ready.
        decision_store.update_status(decision_id, "processing", current_step=0)
        logger.info(f"[{decision_id}] Step 1: Extraction")

        # Run synchronous LLM call in a thread pool so the event loop stays free.
        # Without this, the OpenAI HTTP call blocks the event loop for the full
        # LLM latency (~2-3s), preventing the SSE generator from polling.
        loop = asyncio.get_event_loop()
        extraction_response = await loop.run_in_executor(
            None,
            lambda: extractor.extract(decision_text=record.input_text, request_id=decision_id, company_id=record.company_id),
        )
        decision_obj = extraction_response.decision
        extraction_meta = extraction_response.extraction_metadata

        decision_store.store_results(
            decision_id,
            decision=decision_obj.model_dump(),
            extraction_metadata=extraction_meta,
        )
        decision_store.update_status(decision_id, "processing", current_step=1)
        logger.info(f"[{decision_id}] Step 1 complete → extraction_complete")

        # ── Step 2: Governance evaluation + Graph ────────────────────────────
        # Both governance and graph map to frontend step 2 ("policy_complete").
        # Set to 2 only after BOTH finish so the panel unlocks with full data.
        logger.info(f"[{decision_id}] Step 2: Governance evaluation")

        from app.governance import evaluate_governance

        company_data = company_service.get_company_data(record.company_id)

        logger.info(
            f"[{decision_id}] Governance input: "
            f"cost={decision_obj.cost} "
            f"uses_pii={decision_obj.uses_pii} "
            f"involves_hiring={decision_obj.involves_hiring} "
            f"involves_compliance_risk={decision_obj.involves_compliance_risk} "
            f"strategic_impact={decision_obj.strategic_impact} "
            f"headcount_change={decision_obj.headcount_change}"
        )
        gov_result = evaluate_governance(
            decision=decision_obj,
            company_context=company_data or {},
            use_o1=False,  # Deterministic governance for pipeline
            company_id=record.company_id  # Pass company_id for correct rules
        )
        gov_dict = gov_result.to_dict()
        derived = gov_dict.pop("derived_attributes", {})

        decision_store.store_results(
            decision_id,
            governance=gov_dict,
            derived_attributes=derived,
        )

        logger.info(f"[{decision_id}] Step 2b: Graph mapping")

        graph_payload = None
        try:
            decision_dict = decision_obj.model_dump()
            gov_for_graph = {**gov_dict, "derived_attributes": derived}
            logger.info(f"[{decision_id}] Graph: decision_dict has {len(decision_dict.get('goals', []))} goals, {len(decision_dict.get('kpis', []))} KPIs")

            decision_graph = await graph_repo.upsert_decision_graph(
                decision=decision_dict,
                governance=gov_for_graph,
                decision_id=decision_id,
            )
            logger.info(f"[{decision_id}] Graph: built {len(decision_graph.nodes)} nodes, {len(decision_graph.edges)} edges")
            graph_payload = {
                "decision_id": decision_graph.decision_id,
                "nodes": [n.model_dump() for n in decision_graph.nodes],
                "edges": [e.model_dump() for e in decision_graph.edges],
                "metadata": decision_graph.metadata or {},
            }
            decision_store.store_results(decision_id, graph_payload=graph_payload)
            logger.info(f"[{decision_id}] Graph: stored graph_payload successfully")
        except Exception as e:
            logger.error(f"[{decision_id}] Graph step failed (non-fatal): {e}", exc_info=True)

        decision_store.update_status(decision_id, "processing", current_step=2)
        logger.info(f"[{decision_id}] Step 2 complete → policy_complete")

        # ── Step 3: o1 Reasoning ─────────────────────────────────────────────
        # Set to 3 AFTER reasoning stores results → SSE emits "reasoning_complete"
        logger.info(f"[{decision_id}] Step 3: o1 Reasoning (use_o1_graph={use_o1_graph})")

        reasoning = await _run_o1_reasoning(
            decision_id=decision_id,
            decision_obj=decision_obj,
            gov_dict=gov_dict,
            company_data=company_data,
            graph_repo=graph_repo,
            use_o1_graph=use_o1_graph,
        )
        decision_store.store_results(decision_id, reasoning=reasoning)
        decision_store.update_status(decision_id, "processing", current_step=3)
        logger.info(f"[{decision_id}] Step 3 complete → reasoning_complete")

        # ── Step 4: Decision Pack ────────────────────────────────────────────
        # Set status=complete after pack is built → SSE emits "complete" event
        logger.info(f"[{decision_id}] Step 4: Decision Pack")

        from app.decision_pack import build_decision_pack

        decision_pack = build_decision_pack(
            decision=decision_obj.model_dump(),
            governance=gov_dict,
            company=company_data or {},
        )
        decision_store.store_results(decision_id, decision_pack=decision_pack)

        # ── Done ─────────────────────────────────────────────────────────────
        decision_store.update_status(decision_id, "complete", current_step=4)
        logger.info(f"[{decision_id}] Pipeline complete")

    except Exception as e:
        logger.error(f"[{decision_id}] Pipeline failed: {e}", exc_info=True)
        decision_store.store_error(decision_id, str(e))


async def _run_o1_reasoning(
    decision_id: str,
    decision_obj,
    gov_dict: dict,
    company_data: Optional[dict],
    graph_repo=None,
    use_o1_graph: bool = False,
) -> dict:
    """
    Run graph reasoning for step 4.

    When use_o1_graph=True: calls analyze_decision_graph_with_o1 against graph_repo.
    When use_o1_graph=False: returns deterministic stub immediately — o1 is NOT called.
    """
    if not use_o1_graph:
        logger.info(f"[{decision_id}] o1 reasoning skipped (use_o1_graph=False)")
        return {
            "source": "deterministic",
            "graph_reasoning": None,
            "o1_available": False,
        }

    try:
        from app.graph_reasoning import analyze_decision_graph_with_o1, format_graph_insights_for_pack

        graph_insights = await analyze_decision_graph_with_o1(
            decision_id=decision_id,
            governance=gov_dict,
            repository=graph_repo,
            decision_data=decision_obj.model_dump(),
            company_data=company_data or {},
            use_o1=True,
        )
        formatted = format_graph_insights_for_pack(graph_insights)

        return {
            "source": "o1",
            "graph_reasoning": formatted,
            "o1_available": True,
        }

    except Exception as e:
        logger.warning(
            f"[{decision_id}] o1 reasoning failed: {e} — returning deterministic fallback"
        )
        return {
            "source": "deterministic_fallback",
            "graph_reasoning": None,
            "o1_available": False,
        }

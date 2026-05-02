"""
Pipeline Service - Async orchestrator for the full governance pipeline.

Execution order (strict):
  Step 1: LLM extraction           (extractor.extract)
  Step 2: Decision context          (optional LLM — non-fatal)
  Step 3: Governance evaluation     (governance.evaluate_governance)
  Step 4: Graph upsert + retrieval  (graph_repository)
  Step 5: Semantics inference       (optional LLM — non-fatal)
  Step 5b: External signals         (Tavily live search + curated fallback — non-fatal)
  Step 6: Risk scoring              (risk_scoring_service — non-fatal, receives ext adjustments)
  Step 7: Governance agent          (LangGraph — non-fatal, requires Neo4j, receives ext signals)
  Step 8: Reasoning stub            (deterministic — Nova removed)
  Step 9: Simulation                (non-fatal)
  Step 10: Decision Pack            (decision_pack.build_decision_pack)

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
) -> None:
    """
    Full async pipeline. Designed to run as a BackgroundTask.

    Args:
        decision_id:      ID of the DecisionRecord to process
        extractor:        DecisionExtractor instance from app globals
        graph_repo:       InMemoryGraphRepository instance from app globals
    """
    record = decision_store.get(decision_id)
    if not record:
        logger.error("[%s] Record not found — aborting pipeline", decision_id)
        return

    try:
        # ── Step 1: Extraction ───────────────────────────────────────────────
        decision_store.update_status(decision_id, "processing", current_step=0)
        logger.info("[%s] Step 1: Extraction", decision_id)

        loop = asyncio.get_running_loop()
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
        logger.info("[%s] Step 1 complete", decision_id)

        # ── Step 2: Decision Context Extraction (optional LLM) ──────────────
        logger.info("[%s] Step 2: Decision Context Extraction (optional LLM)", decision_id)
        try:
            from app.services.decision_context_service import extract_decision_context

            _ctx_result = await loop.run_in_executor(
                None,
                lambda: extract_decision_context(
                    decision_text=record.input_text,
                    agent_name=record.agent_name,
                    agent_name_en=record.agent_name_en,
                ),
            )
            if _ctx_result is not None:
                decision_store.store_results(decision_id, decision_context=_ctx_result)
                logger.info(
                    f"[{decision_id}] Decision context stored — "
                    f"{len(_ctx_result.get('entities', []))} entities"
                )
            else:
                logger.info("[%s] Decision context not available — skipped", decision_id)
        except Exception as _ctx_e:
            logger.warning(
                f"[{decision_id}] Decision Context Extraction failed (non-fatal): {_ctx_e}",
                exc_info=True,
            )

        # ── Step 3: Governance evaluation + Graph ────────────────────────────
        logger.info("[%s] Step 3: Governance evaluation", decision_id)

        from app.governance import evaluate_governance

        company_data = company_service.get_company_data(record.company_id, lang="en")

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
            company_id=record.company_id,
        )
        gov_dict = gov_result.to_dict()
        derived = gov_dict.pop("derived_attributes", {})

        decision_store.store_results(
            decision_id,
            governance=gov_dict,
            derived_attributes=derived,
        )

        # ── Step 4: Graph mapping ────────────────────────────────────────────
        logger.info("[%s] Step 4: Graph mapping", decision_id)

        graph_payload = None
        try:
            decision_dict = decision_obj.model_dump()
            gov_for_graph = {**gov_dict, "derived_attributes": derived}
            logger.info("[%s] Graph: decision_dict has %d goals, %d KPIs", decision_id, len(decision_dict.get('goals', [])), len(decision_dict.get('kpis', [])))

            decision_graph = await graph_repo.upsert_decision_graph(
                decision=decision_dict,
                governance=gov_for_graph,
                decision_id=decision_id,
                company_context=company_data or {},
            )
            logger.info("[%s] Graph: built %d nodes, %d edges", decision_id, len(decision_graph.nodes), len(decision_graph.edges))
            graph_payload = {
                "decision_id": decision_graph.decision_id,
                "nodes": [n.model_dump() for n in decision_graph.nodes],
                "edges": [e.model_dump() for e in decision_graph.edges],
                "metadata": decision_graph.metadata or {},
            }

            decision_store.store_results(decision_id, graph_payload=graph_payload)
            logger.info("[%s] Graph: stored graph_payload successfully", decision_id)
        except Exception as e:
            logger.error("[%s] Graph step failed (non-fatal): %s", decision_id, e, exc_info=True)

        decision_store.update_status(decision_id, "processing", current_step=2)
        logger.info("[%s] Steps 3-4 complete", decision_id)

        # ── Step 5: Optional Semantics Inference ─────────────────────────────
        logger.info("[%s] Step 5: Semantics Inference (optional LLM)", decision_id)
        _risk_semantics_dict: dict | None = None
        try:
            from app.services.risk_evidence_llm import infer_risk_semantics

            _company_summary_for_sem = {
                "strategic_goals": (company_data or {}).get("strategic_goals", []),
            }
            _triggered_for_sem = gov_dict.get("triggered_rules", [])

            _semantics = await loop.run_in_executor(
                None,
                lambda: infer_risk_semantics(
                    decision_text=record.input_text,
                    company_summary=_company_summary_for_sem,
                    triggered_rules_summary=_triggered_for_sem,
                ),
            )
            if _semantics is not None:
                _risk_semantics_dict = _semantics.model_dump()
                decision_store.store_results(
                    decision_id,
                    risk_semantics=_risk_semantics_dict,
                )
                logger.info(
                    f"[{decision_id}] Semantics stored — "
                    f"{len(_semantics.goal_impacts)} goal_impacts, "
                    f"global_confidence={_semantics.global_confidence:.2f}"
                )
            else:
                logger.info("[%s] Semantics not available — skipped", decision_id)
        except Exception as _e:
            logger.warning(
                f"[{decision_id}] Semantics Inference failed (non-fatal): {_e}",
                exc_info=True,
            )

        # ── Step 5b: External Signals (before risk scoring) ─────────────────
        logger.info("[%s] Step 5b: External Signals (live search + curated fallback)", decision_id)
        _ext_payload = None
        _ext_adjustments: list[dict] = []
        try:
            from app.services.external_signal_service import build_external_signals

            _ext_payload = build_external_signals(
                company_id=record.company_id,
                decision=decision_obj.model_dump(),
                governance_result=gov_dict,
                risk_scoring=None,  # risk scoring hasn't run yet
            )
            if _ext_payload is not None:
                decision_store.store_results(
                    decision_id, external_signals=_ext_payload.model_dump()
                )
                _ext_adjustments = [
                    a.model_dump() if hasattr(a, "model_dump") else a
                    for a in (_ext_payload.riskAdjustments or [])
                ]
                logger.info(
                    f"[{decision_id}] External signals assembled — "
                    f"market={len(_ext_payload.marketSignals)}, "
                    f"regulatory={len(_ext_payload.regulatorySignals)}, "
                    f"operational={len(_ext_payload.operationalSignals)}, "
                    f"risk_adjustments={len(_ext_adjustments)}"
                )
            else:
                logger.info(
                    f"[{decision_id}] External signals: no payload "
                    f"(no profile configured or sources unavailable)"
                )
        except Exception as _ext_e:
            logger.error(
                f"[{decision_id}] External signal retrieval failed (non-fatal): {_ext_e}",
                exc_info=True,
            )

        # ── Step 6: Risk Scoring ─────────────────────────────────────────────
        logger.info("[%s] Step 6: Risk Scoring", decision_id)
        try:
            from app.services.risk_scoring_service import RiskScoringService

            _risk_service = RiskScoringService()
            _risk_result = _risk_service.score(
                decision_payload=decision_obj.model_dump(),
                company_payload=company_data or {},
                governance_result={**gov_dict, "derived_attributes": derived},
                graph_data=graph_payload,
                risk_semantics=_risk_semantics_dict,
                company_id=record.company_id,
                external_signal_adjustments=_ext_adjustments or None,
            )
            decision_store.store_results(
                decision_id,
                risk_scoring=_risk_result.to_dict(),
            )
            # Sync derived_attributes.risk_level to the quantified risk scoring band
            _band_to_level = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high", "CRITICAL": "critical"}
            _synced_level = _band_to_level.get(_risk_result.aggregate.band.upper(), derived.get("risk_level", "medium"))
            derived = {**derived, "risk_level": _synced_level}
            decision_store.store_results(decision_id, derived_attributes=derived)
            logger.info(
                f"[{decision_id}] Risk Scoring complete — "
                f"aggregate={_risk_result.aggregate.score} ({_risk_result.aggregate.band}), "
                f"derived.risk_level synced to '{_synced_level}'"
            )
        except Exception as _e:
            logger.error(
                f"[{decision_id}] Risk Scoring failed (non-fatal): {_e}",
                exc_info=True,
            )

        # ── Step 7: Governance Agent Validation (non-fatal) ──────────────────
        import os as _os
        if _os.getenv("NEO4J_URI"):
            logger.info("[%s] Step 7: Governance Agent Validation (Neo4j available)", decision_id)
            _neo4j_repo = None
            try:
                from app.validation.governance_agent import run_governance_agent
                from app.graph.neo4j_repository import Neo4jGraphRepository

                _neo4j_repo = Neo4jGraphRepository()
                await _neo4j_repo.initialize(record.company_id or "nexus_analytics")
                _validation_result = await run_governance_agent(
                    company_id=record.company_id or "nexus_analytics",
                    decision_text=record.input_text,
                    decision_payload=decision_obj.model_dump() if decision_obj else {},
                    governance_result=gov_dict,
                    risk_scoring=record.risk_scoring,
                    graph_context=graph_payload,
                    repo=_neo4j_repo,
                    external_signals=record.external_signals,
                )
                decision_store.store_results(
                    decision_id,
                    validation_result=_validation_result.model_dump(),
                )
                logger.info(
                    f"[{decision_id}] Governance agent complete — "
                    f"verdict={_validation_result.verdict}, "
                    f"confidence={_validation_result.confidence:.2f}"
                )
            except Exception as _val_e:
                logger.warning(
                    f"[{decision_id}] Governance agent validation failed (non-fatal): {_val_e}",
                    exc_info=True,
                )
            finally:
                if _neo4j_repo is not None:
                    try:
                        await _neo4j_repo.close()
                    except Exception:
                        pass
        else:
            logger.info("[%s] Step 7: Governance Agent skipped (NEO4J_URI not set)", decision_id)

        # ── Step 8: Reasoning (deterministic stub — Nova removed) ────────────
        logger.info("[%s] Step 8: Reasoning (deterministic stub)", decision_id)
        reasoning = {
            "source": "deterministic",
            "graph_reasoning": None,
        }
        decision_store.store_results(decision_id, reasoning=reasoning)
        decision_store.update_status(decision_id, "processing", current_step=3)
        logger.info("[%s] Step 8 complete", decision_id)

        # ── Step 9: Simulation ─────────────────────────────────────────────────
        logger.info("[%s] Step 9: Simulation", decision_id)
        try:
            from app.services.risk_response_simulation_service import (
                RiskResponseSimulationService,
            )
            _sim_service = RiskResponseSimulationService()
            _sim_result = _sim_service.simulate(
                decision_payload=decision_obj.model_dump(),
                governance_result=gov_dict,
                risk_scoring=record.risk_scoring or {},
                company_payload=company_data or {},
                company_id=record.company_id,
            )
            decision_store.store_results(decision_id, simulation=_sim_result)
            n_scenarios = len(_sim_result.get("scenarios", []))
            logger.info(
                f"[{decision_id}] Simulation complete — {n_scenarios} scenario(s) generated"
            )
        except Exception as _sim_e:
            logger.error(
                f"[{decision_id}] Simulation failed (non-fatal): {_sim_e}",
                exc_info=True,
            )

        # ── Step 10: Decision Pack ───────────────────────────────────────────
        logger.info("[%s] Step 10: Decision Pack", decision_id)

        from app.decision_pack import build_decision_pack

        _graph_insights = (reasoning or {}).get("graph_reasoning")

        decision_pack = build_decision_pack(
            decision=decision_obj.model_dump(),
            governance=gov_dict,
            company=company_data or {},
            graph_insights=_graph_insights,
            risk_scoring=record.risk_scoring,
            external_signals=_ext_payload.model_dump() if _ext_payload else None,
            decision_context=record.decision_context,
        )
        decision_store.store_results(decision_id, decision_pack=decision_pack)

        # ── Done ─────────────────────────────────────────────────────────────
        decision_store.update_status(decision_id, "complete", current_step=4)
        logger.info("[%s] Pipeline complete", decision_id)

        # ── Write-back: update workspace DB record if linked ─────────────────
        if record.workspace_decision_id:
            try:
                from app.db.session import SessionLocal
                from app.repositories import decision_repository

                _contract_value = None
                if decision_obj.cost is not None:
                    _contract_value = int(decision_obj.cost)

                _gov_flags = set(gov_dict.get("flags", []))
                _blocking_flags = {
                    "HIGH_RISK", "CRITICAL_CONFLICT", "FINANCIAL_THRESHOLD_EXCEEDED",
                    "PRIVACY_REVIEW_REQUIRED", "COMPLIANCE_VIOLATION", "STRATEGIC_CRITICAL",
                }
                _ws_status = "blocked" if _gov_flags & _blocking_flags else "validated"

                _db = SessionLocal()
                try:
                    updated = decision_repository.update_from_analysis(
                        _db,
                        decision_id=record.workspace_decision_id,
                        risk_level=derived.get("risk_level"),
                        confidence=derived.get("confidence"),
                        contract_value=_contract_value,
                        affected_count=decision_obj.headcount_change,
                        status=_ws_status,
                    )
                finally:
                    _db.close()
                if updated:
                    logger.info(
                        f"[{decision_id}] Workspace decision '{record.workspace_decision_id}' "
                        f"updated — status={_ws_status}, risk_level={derived.get('risk_level')}, "
                        f"confidence={derived.get('confidence')}, "
                        f"contract_value={_contract_value}, "
                        f"affected_count={decision_obj.headcount_change}"
                    )
                else:
                    logger.warning(
                        f"[{decision_id}] Workspace decision '{record.workspace_decision_id}' not found in DB"
                    )
            except Exception as _wb_e:
                logger.error(
                    f"[{decision_id}] Workspace write-back failed (non-fatal): {_wb_e}",
                    exc_info=True,
                )

    except Exception as e:
        logger.error("[%s] Pipeline failed: %s", decision_id, e, exc_info=True)
        decision_store.store_error(decision_id, str(e))

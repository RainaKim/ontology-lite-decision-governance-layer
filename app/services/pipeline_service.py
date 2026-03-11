"""
Pipeline Service - Async orchestrator for the full governance pipeline.

Execution order (strict):
  1. LLM extraction           (extractor.extract)
  2. Governance evaluation    (governance.evaluate_governance)
  3. Graph upsert + retrieval (graph_repository)
  2d. Semantics inference     (risk_evidence_llm — OPTIONAL, non-fatal)
  2c. Risk Scoring            (risk_scoring_service — non-fatal, consumes semantics if available)
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

        # ── Step 1b: Decision Context Extraction (optional LLM) ──────────────
        # Extracts left-panel-safe structured entities from the raw decision text.
        # Non-fatal: a failure here must not block the rest of the pipeline.
        logger.info(f"[{decision_id}] Step 1b: Decision Context Extraction (optional LLM)")
        try:
            from app.services.decision_context_service import extract_decision_context

            _ctx_result = await loop.run_in_executor(
                None,
                lambda: extract_decision_context(
                    decision_text=record.input_text,
                    agent_name=record.agent_name,
                    agent_name_en=record.agent_name_en,
                    lang=record.lang,
                ),
            )
            if _ctx_result is not None:
                decision_store.store_results(decision_id, decision_context=_ctx_result)
                logger.info(
                    f"[{decision_id}] Decision context stored — "
                    f"{len(_ctx_result.get('entities', []))} entities"
                )
            else:
                logger.info(f"[{decision_id}] Decision context not available — skipped")
        except Exception as _ctx_e:
            logger.warning(
                f"[{decision_id}] Decision Context Extraction failed (non-fatal): {_ctx_e}",
                exc_info=True,
            )

        # ── Step 2: Governance evaluation + Graph ────────────────────────────
        # Both governance and graph map to frontend step 2 ("policy_complete").
        # Set to 2 only after BOTH finish so the panel unlocks with full data.
        logger.info(f"[{decision_id}] Step 2: Governance evaluation")

        from app.governance import evaluate_governance

        company_data = company_service.get_company_data(record.company_id, lang=record.lang)

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
            company_id=record.company_id,
            lang=record.lang,
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
                company_context=company_data or {},
            )
            logger.info(f"[{decision_id}] Graph: built {len(decision_graph.nodes)} nodes, {len(decision_graph.edges)} edges")
            graph_payload = {
                "decision_id": decision_graph.decision_id,
                "nodes": [n.model_dump() for n in decision_graph.nodes],
                "edges": [e.model_dump() for e in decision_graph.edges],
                "metadata": decision_graph.metadata or {},
            }

            # Enrich Korean node labels with English translations (non-fatal)
            try:
                await loop.run_in_executor(None, lambda: _enrich_node_labels_en(graph_payload["nodes"]))
            except Exception as _lbl_e:
                logger.warning(f"[{decision_id}] Node label enrichment failed (non-fatal): {_lbl_e}")

            decision_store.store_results(decision_id, graph_payload=graph_payload)
            logger.info(f"[{decision_id}] Graph: stored graph_payload successfully")
        except Exception as e:
            logger.error(f"[{decision_id}] Graph step failed (non-fatal): {e}", exc_info=True)

        decision_store.update_status(decision_id, "processing", current_step=2)
        logger.info(f"[{decision_id}] Step 2 complete → policy_complete")

        # ── Step 2d: Optional Semantics Inference ───────────────────────────
        # LLM classifies goal impacts + compliance facts as structured JSON.
        # Non-fatal: None is stored when the call fails or API key is absent.
        # Result is consumed by risk scoring (step 2c) as fallback input only.
        logger.info(f"[{decision_id}] Step 2d: Semantics Inference (optional LLM)")
        _risk_semantics_dict: dict | None = None
        try:
            from app.services.risk_evidence_llm import infer_risk_semantics

            _company_summary_for_sem = {
                "strategic_goals": (company_data or {}).get("strategic_goals", []),
            }
            _triggered_for_sem = gov_dict.get("triggered_rules", [])

            loop = asyncio.get_event_loop()
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
                logger.info(f"[{decision_id}] Semantics not available — skipped")
        except Exception as _e:
            logger.warning(
                f"[{decision_id}] Semantics Inference failed (non-fatal): {_e}",
                exc_info=True,
            )

        # ── Step 2c: Risk Scoring ────────────────────────────────────────────
        # Runs after governance + graph so it has triggered_rules + goal edges.
        # Consumes semantics (if available) as fallback for missing structural data.
        # Non-fatal: a failure here must not block the rest of the pipeline.
        logger.info(f"[{decision_id}] Step 2c: Risk Scoring")
        try:
            from app.services.risk_scoring_service import RiskScoringService

            _risk_service = RiskScoringService()
            _risk_result = _risk_service.score(
                decision_payload=decision_obj.model_dump(),
                company_payload=company_data or {},
                governance_result={**gov_dict, "derived_attributes": derived},
                graph_payload=graph_payload,
                risk_semantics=_risk_semantics_dict,
                company_id=record.company_id,
            )
            decision_store.store_results(
                decision_id,
                risk_scoring=_risk_result.to_dict(),
            )
            # Sync derived_attributes.risk_level to the quantified risk scoring band
            # so that the feed card and the detail view always show the same value.
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
            lang=record.lang,
        )
        decision_store.store_results(decision_id, reasoning=reasoning)
        decision_store.update_status(decision_id, "processing", current_step=3)
        logger.info(f"[{decision_id}] Step 3 complete → reasoning_complete")

        # ── Step 4b: Risk Response Simulation ────────────────────────────────
        # Non-fatal: generates counterfactual remediation scenarios by re-running
        # governance + risk scoring on patched decision payloads.
        logger.info(f"[{decision_id}] Step 4b: Risk Response Simulation")
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
                lang=record.lang,
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

        # ── Step 4c: External Signal Retrieval ───────────────────────────────
        # Non-fatal: retrieves and summarizes external market / regulatory /
        # operational signals that provide supporting context for this decision.
        # External signals are ADDITIVE — they never modify governance outcomes.
        # Runs before Decision Pack so signals can be included in the pack report.
        logger.info(f"[{decision_id}] Step 4c: External Signal Retrieval")
        _ext_payload = None
        try:
            from app.services.external_signal_service import build_external_signals

            _ext_payload = build_external_signals(
                company_id=record.company_id,
                decision=decision_obj.model_dump(),
                governance_result=gov_dict,
                risk_scoring=record.risk_scoring,
                lang=record.lang,
            )
            if _ext_payload is not None:
                decision_store.store_results(
                    decision_id, external_signals=_ext_payload.model_dump()
                )
                logger.info(
                    f"[{decision_id}] External signals assembled — "
                    f"market={len(_ext_payload.marketSignals)}, "
                    f"regulatory={len(_ext_payload.regulatorySignals)}, "
                    f"operational={len(_ext_payload.operationalSignals)}"
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

        # ── Step 4: Decision Pack ────────────────────────────────────────────
        # Set status=complete after pack is built → SSE emits "complete" event
        logger.info(f"[{decision_id}] Step 4: Decision Pack")

        from app.decision_pack import build_decision_pack

        decision_pack = build_decision_pack(
            decision=decision_obj.model_dump(),
            governance=gov_dict,
            company=company_data or {},
            lang=record.lang,
            risk_scoring=record.risk_scoring,
            external_signals=_ext_payload.model_dump() if _ext_payload else None,
            decision_context=record.decision_context,
        )
        decision_store.store_results(decision_id, decision_pack=decision_pack)

        # ── Done ─────────────────────────────────────────────────────────────
        decision_store.update_status(decision_id, "complete", current_step=4)
        logger.info(f"[{decision_id}] Pipeline complete")

        # ── Write-back: update workspace DB record if linked ─────────────────
        if record.workspace_decision_id:
            try:
                from app.db.session import SessionLocal
                from app.repositories import decision_repository

                _contract_value = None
                if decision_obj.cost is not None:
                    _contract_value = int(decision_obj.cost)

                # Derive workspace status from governance flags
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
        logger.error(f"[{decision_id}] Pipeline failed: {e}", exc_info=True)
        decision_store.store_error(decision_id, str(e))


async def _run_o1_reasoning(
    decision_id: str,
    decision_obj,
    gov_dict: dict,
    company_data: Optional[dict],
    graph_repo=None,
    use_o1_graph: bool = False,
    lang: str = "ko",
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
            lang=lang,
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


def _enrich_node_labels_en(nodes: list[dict]) -> None:
    """
    Batch-translate Korean node labels to English via Nova.
    Mutates each node dict in-place by setting properties["label_en"].
    Skips nodes that already have label_en or whose label is already ASCII.
    """
    import json as _json
    from app.bedrock_client import BedrockClient

    to_translate = [
        {"id": n["id"], "type": n.get("type", ""), "label": n.get("label", "")}
        for n in nodes
        if n.get("label") and not n.get("label", "").isascii()
        and not (n.get("properties") or {}).get("label_en")
    ]
    if not to_translate:
        return

    client = BedrockClient()
    user_msg = (
        "Translate each Korean governance graph node label to concise English (≤60 chars).\n"
        "Return ONLY a JSON object: {\"<id>\": \"<English label>\", ...}\n\n"
        + _json.dumps(to_translate, ensure_ascii=False)
    )
    system_prompt = (
        "You are a bilingual translator for a corporate governance system. "
        "Translate Korean labels to professional English. "
        "Keep proper nouns and identifiers unchanged. Return only the JSON object."
    )
    raw = client.invoke(user_msg, system_prompt=system_prompt, max_tokens=512)
    translations: dict = _json.loads(raw)
    if not isinstance(translations, dict):
        return

    id_to_node = {n["id"]: n for n in nodes}
    for node_id, en_label in translations.items():
        if not isinstance(en_label, str) or not en_label.strip():
            continue
        node = id_to_node.get(node_id)
        if node is None:
            continue
        if node.get("properties") is None:
            node["properties"] = {}
        node["properties"]["label_en"] = en_label.strip()
    logger.info(f"[graph_label] Enriched {len(translations)} node label(s) with English")

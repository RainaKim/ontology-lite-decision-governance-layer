"""
End-to-End Test Runner - Demo Stability Validation

Validates the complete governance flow through the unified pipeline:
  Decision → Governance → Graph Storage → Graph Reasoning (subgraph extraction) → Decision Pack

Invariants (MUST NEVER fail):
- Decision Pack is never null
- Graph is never empty after governance
- Approval chain exists when rules triggered
- Graph reasoning section present when graph analysis enabled
- Subgraph metadata populated after extraction
"""

import asyncio
from typing import Optional

from app.demo_fixtures import get_all_fixtures, get_demo_fixture, get_company_context
from app.decision_pipeline import process_decision_with_graph_reasoning


class InvariantViolation(Exception):
    """Critical invariant violated - demo unstable."""
    pass


class E2EValidator:
    """End-to-end validation for governance flow."""

    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0

    # ------------------------------------------------------------------
    # Helper methods for recording results
    # ------------------------------------------------------------------

    def _pass(self, check: str, scenario: str, details: str) -> None:
        self.results.append({
            "check": check,
            "scenario": scenario,
            "status": "PASS",
            "details": details,
        })
        self.passed += 1

    def _warn(self, check: str, scenario: str, details: str) -> None:
        self.results.append({
            "check": check,
            "scenario": scenario,
            "status": "WARN",
            "details": details,
        })
        self.passed += 1  # warnings still count as passed

    def _fail(self, check: str, scenario: str, details: str) -> None:
        self.results.append({
            "check": check,
            "scenario": scenario,
            "status": "FAIL",
            "details": details,
        })
        self.failed += 1

    # ------------------------------------------------------------------
    # Core invariant checks
    # ------------------------------------------------------------------

    def validate_approval_chain(self, governance_result: dict, scenario: str) -> None:
        """
        INVARIANT: If triggered_rules non-empty, approval_chain must exist.
        """
        triggered_rules = governance_result.get("triggered_rules", [])
        approval_chain = governance_result.get("approval_chain", [])

        if len(triggered_rules) > 0 and len(approval_chain) == 0:
            raise InvariantViolation(
                f"[{scenario}] Rules triggered but approval chain empty. "
                f"Triggered: {len(triggered_rules)} rules, Chain: 0 steps"
            )

        self._pass(
            "approval_chain_when_rules_triggered",
            scenario,
            f"Rules: {len(triggered_rules)}, Chain steps: {len(approval_chain)}",
        )

    def validate_graph_metadata(self, graph_meta: dict, scenario: str) -> None:
        """
        INVARIANT: Graph must never be empty after governance.
        Validates the graph_metadata dict returned by the pipeline.
        """
        nodes = graph_meta.get("nodes", 0)
        edges = graph_meta.get("edges", 0)

        if nodes == 0:
            raise InvariantViolation(
                f"[{scenario}] Graph has zero nodes — construction failed"
            )

        self._pass(
            "graph_not_empty",
            scenario,
            f"Nodes: {nodes}, Edges: {edges}, Method: {graph_meta.get('analysis_method', 'N/A')}",
        )

    def validate_decision_pack_generated(self, decision_pack: dict, scenario: str) -> None:
        """
        INVARIANT: Decision Pack must NEVER be null and must contain all required sections.
        """
        if decision_pack is None:
            raise InvariantViolation(
                f"[{scenario}] Decision Pack is None — generation failed"
            )

        required_sections = [
            "title", "summary", "goals_kpis", "risks",
            "approval_chain", "recommended_next_actions", "audit",
        ]
        missing_sections = [s for s in required_sections if s not in decision_pack]
        if missing_sections:
            raise InvariantViolation(
                f"[{scenario}] Decision Pack missing sections: {missing_sections}"
            )

        summary = decision_pack.get("summary", {})
        required_summary_fields = [
            "decision_statement", "human_approval_required",
            "risk_level", "governance_status",
        ]
        missing_summary = [f for f in required_summary_fields if f not in summary]
        if missing_summary:
            raise InvariantViolation(
                f"[{scenario}] Decision Pack summary missing fields: {missing_summary}"
            )

        self._pass(
            "decision_pack_always_generated",
            scenario,
            f"All sections present, status: {summary.get('governance_status')}",
        )

    def validate_graph_reasoning_section(self, decision_pack: dict, scenario: str) -> None:
        """
        INVARIANT: When graph_analysis_enabled is True in the summary, the
        graph_reasoning section must exist and contain required keys.
        """
        summary = decision_pack.get("summary", {})
        graph_enabled = summary.get("graph_analysis_enabled", False)

        if not graph_enabled:
            self._pass(
                "graph_reasoning_section",
                scenario,
                "Graph analysis not enabled — skipped",
            )
            return

        graph_reasoning = decision_pack.get("graph_reasoning")
        if graph_reasoning is None:
            raise InvariantViolation(
                f"[{scenario}] graph_analysis_enabled=True but graph_reasoning section missing"
            )

        required_keys = [
            "analysis_method",
            "logical_contradictions",
            "graph_recommendations",
            "confidence",
        ]
        missing = [k for k in required_keys if k not in graph_reasoning]
        if missing:
            raise InvariantViolation(
                f"[{scenario}] graph_reasoning missing keys: {missing}"
            )

        self._pass(
            "graph_reasoning_section",
            scenario,
            (
                f"Method: {graph_reasoning['analysis_method']}, "
                f"Contradictions: {len(graph_reasoning['logical_contradictions'])}, "
                f"Recommendations: {len(graph_reasoning['graph_recommendations'])}, "
                f"Confidence: {graph_reasoning['confidence']}"
            ),
        )

    def validate_subgraph_metadata(self, graph_meta: dict, scenario: str) -> None:
        """
        Validate that the pipeline reports a valid analysis method and
        non-zero graph when analysis was performed.
        """
        method = graph_meta.get("analysis_method", "not_performed")
        nodes = graph_meta.get("nodes", 0)
        edges = graph_meta.get("edges", 0)

        if method != "not_performed" and nodes == 0:
            raise InvariantViolation(
                f"[{scenario}] Analysis method is '{method}' but graph has 0 nodes"
            )

        self._pass(
            "subgraph_metadata",
            scenario,
            f"Method: {method}, Nodes: {nodes}, Edges: {edges}",
        )

    # ------------------------------------------------------------------
    # Scenario-specific expectations
    # ------------------------------------------------------------------

    def validate_scenario_specific(
        self, scenario: str, governance_result: dict, decision_pack: dict
    ) -> None:
        """
        Validate scenario-specific expectations.
        Relaxed checks to work with any rule set.
        """
        flags = governance_result.get("flags", [])
        status = decision_pack.get("summary", {}).get("governance_status")
        risk_level = decision_pack.get("summary", {}).get("risk_level")

        if scenario == "compliant":
            if status == "blocked":
                return self._fail(
                    f"scenario_{scenario}", scenario,
                    "Compliant decision should not be blocked",
                )

        elif scenario == "budget_violation":
            if status == "compliant" and risk_level == "low":
                return self._fail(
                    f"scenario_{scenario}", scenario,
                    "Budget violation should trigger governance review",
                )

        elif scenario == "privacy_violation":
            if len(flags) == 0 and not governance_result.get("requires_human_review"):
                return self._fail(
                    f"scenario_{scenario}", scenario,
                    "Privacy violation should trigger flags or review",
                )

        elif scenario == "blocked":
            if status == "compliant":
                return self._fail(
                    f"scenario_{scenario}", scenario,
                    f"Blocked decision should not have status 'compliant', got '{status}'",
                )

        self._pass(
            f"scenario_{scenario}",
            scenario,
            f"Scenario behaves reasonably: status={status}, flags={len(flags)}, risk={risk_level}",
        )

    # ------------------------------------------------------------------
    # Run single scenario through full pipeline
    # ------------------------------------------------------------------

    async def run_e2e_test(self, scenario_name: str, decision) -> dict:
        """
        Run end-to-end test for a single scenario through the unified pipeline.

        Uses process_decision_with_graph_reasoning which performs:
          1. Governance evaluation (deterministic)
          2. Graph storage (InMemoryGraphRepository)
          3. Graph reasoning — subgraph extraction + deterministic analysis
          4. Decision Pack generation (template-based + graph insights)
        """
        print(f"\n{'='*80}")
        print(f"Testing scenario: {scenario_name}")
        print(f"{'='*80}")

        try:
            # Load company context (needed for subgraph extraction)
            company_context = get_company_context()

            # Run through the unified pipeline (deterministic — no OpenAI calls)
            print("  Running full pipeline (governance → graph → reasoning → pack)...")
            result = await process_decision_with_graph_reasoning(
                decision=decision,
                decision_id=f"test_{scenario_name}",
                company_context=company_context,
                use_o1_governance=False,   # deterministic governance
                use_o1_graph=False,        # deterministic graph analysis (no OpenAI)
            )

            decision_pack = result["decision_pack"]
            governance_result = result["governance_result"]
            graph_meta = result["graph_metadata"]

            print(f"  ✓ Pipeline complete. Status: {decision_pack['summary']['governance_status']}")
            print(f"    Graph: {graph_meta['nodes']} nodes, {graph_meta['edges']} edges")
            print(f"    Analysis: {graph_meta.get('analysis_method', 'N/A')}")

            # --- Invariant checks ---
            self.validate_approval_chain(governance_result, scenario_name)
            self.validate_graph_metadata(graph_meta, scenario_name)
            self.validate_decision_pack_generated(decision_pack, scenario_name)
            self.validate_graph_reasoning_section(decision_pack, scenario_name)
            self.validate_subgraph_metadata(graph_meta, scenario_name)

            # Scenario-specific
            self.validate_scenario_specific(scenario_name, governance_result, decision_pack)

            print(f"\n✓ Scenario '{scenario_name}' PASSED all checks")

            return {
                "scenario": scenario_name,
                "status": "PASS",
                "governance": governance_result,
                "graph_metadata": graph_meta,
                "decision_pack": decision_pack,
            }

        except InvariantViolation as e:
            print(f"\n✗ INVARIANT VIOLATION: {e}")
            self.failed += 1
            self.results.append({
                "check": "invariant",
                "scenario": scenario_name,
                "status": "CRITICAL_FAIL",
                "details": str(e),
            })
            raise

        except Exception as e:
            print(f"\n✗ ERROR: {e}")
            self.failed += 1
            self.results.append({
                "check": "execution",
                "scenario": scenario_name,
                "status": "FAIL",
                "details": str(e),
            })
            raise

    # ------------------------------------------------------------------
    # Run all scenarios
    # ------------------------------------------------------------------

    async def run_all_scenarios(self) -> dict:
        """Run all demo scenarios and collect results."""
        print("\n" + "="*80)
        print("E2E GOVERNANCE VALIDATION — FULL PIPELINE (with subgraph extraction)")
        print("="*80)

        fixtures = get_all_fixtures()
        results = {}

        for scenario_name, decision in fixtures.items():
            try:
                result = await self.run_e2e_test(scenario_name, decision)
                results[scenario_name] = result
            except Exception as e:
                results[scenario_name] = {
                    "scenario": scenario_name,
                    "status": "FAIL",
                    "error": str(e),
                }

        return results

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def print_summary(self) -> bool:
        """Print validation summary. Returns True if all passed."""
        print("\n" + "="*80)
        print("VALIDATION SUMMARY")
        print("="*80)

        total = self.passed + self.failed
        print(f"\nTotal checks: {total}")
        print(f"Passed: {self.passed} ✓")
        print(f"Failed: {self.failed} ✗")
        print(f"Success rate: {(self.passed/total*100) if total > 0 else 0:.1f}%")

        critical_fails = [r for r in self.results if r.get("status") == "CRITICAL_FAIL"]
        fails = [r for r in self.results if r.get("status") == "FAIL"]
        warnings = [r for r in self.results if r.get("status") == "WARN"]

        if critical_fails:
            print(f"\n⚠️  CRITICAL FAILURES ({len(critical_fails)}):")
            for r in critical_fails:
                print(f"  - [{r['scenario']}] {r['check']}: {r['details']}")

        if fails:
            print(f"\n✗ FAILURES ({len(fails)}):")
            for r in fails:
                print(f"  - [{r['scenario']}] {r['check']}: {r['details']}")

        if warnings:
            print(f"\n⚠️  WARNINGS ({len(warnings)}):")
            for r in warnings:
                print(f"  - [{r['scenario']}] {r['check']}: {r['details']}")

        print("\n" + "="*80)

        if self.failed > 0:
            print("❌ DEMO UNSTABLE — Failures detected")
            return False
        else:
            print("✅ DEMO STABLE — All checks passed")
            return True


async def main():
    """Run E2E validation."""
    validator = E2EValidator()

    try:
        await validator.run_all_scenarios()
        stable = validator.print_summary()

        if not stable:
            exit(1)

    except Exception as e:
        print(f"\n❌ Critical failure: {e}")
        validator.print_summary()
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())

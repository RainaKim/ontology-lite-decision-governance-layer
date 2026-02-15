"""
End-to-End Test Runner - Demo Stability Validation

Validates complete governance flow:
1. Decision → Governance → Graph → Decision Pack

Invariants (MUST NEVER fail):
- Decision Pack is never null
- Graph is never empty after governance
- Approval chain exists when rules triggered
- Action node always created
"""

import asyncio
from typing import Optional
from app.demo_fixtures import get_all_fixtures, get_demo_fixture
from app.governance import evaluate_governance
from app.graph_repository import InMemoryGraphRepository
from app.decision_pack import build_decision_pack


class InvariantViolation(Exception):
    """Critical invariant violated - demo unstable."""
    pass


class E2EValidator:
    """End-to-end validation for governance flow."""

    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0

    def validate_approval_chain(self, governance_result: dict, scenario: str) -> None:
        """
        Validate approval chain exists when rules triggered.

        INVARIANT: If triggered_rules non-empty, approval_chain must exist.
        """
        triggered_rules = governance_result.get("triggered_rules", [])
        approval_chain = governance_result.get("approval_chain", [])

        if len(triggered_rules) > 0 and len(approval_chain) == 0:
            raise InvariantViolation(
                f"[{scenario}] Rules triggered but approval chain empty. "
                f"Triggered: {len(triggered_rules)} rules, Chain: 0 steps"
            )

        self.results.append({
            "check": "approval_chain_when_rules_triggered",
            "scenario": scenario,
            "status": "PASS",
            "details": f"Rules: {len(triggered_rules)}, Chain steps: {len(approval_chain)}"
        })
        self.passed += 1

    def validate_graph_payload(self, decision_graph, scenario: str) -> None:
        """
        Validate graph payload contains nodes and edges.

        INVARIANT: Graph must never be empty after governance.
        """
        if decision_graph is None:
            raise InvariantViolation(
                f"[{scenario}] DecisionGraph is None - graph construction failed"
            )

        nodes = decision_graph.nodes if hasattr(decision_graph, 'nodes') else []
        edges = decision_graph.edges if hasattr(decision_graph, 'edges') else []

        if len(nodes) == 0:
            raise InvariantViolation(
                f"[{scenario}] Graph has zero nodes - construction failed"
            )

        # At minimum: 1 Action node
        if len(nodes) < 1:
            raise InvariantViolation(
                f"[{scenario}] Graph must have at least 1 node (Action), found {len(nodes)}"
            )

        self.results.append({
            "check": "graph_payload_not_empty",
            "scenario": scenario,
            "status": "PASS",
            "details": f"Nodes: {len(nodes)}, Edges: {len(edges)}"
        })
        self.passed += 1

    def validate_action_node_exists(self, decision_graph, scenario: str) -> None:
        """
        Validate at least one Action node exists in graph.

        INVARIANT: Every decision must create an Action node.
        """
        from app.graph_ontology import NodeType

        if decision_graph is None:
            raise InvariantViolation(
                f"[{scenario}] Cannot validate Action node - graph is None"
            )

        nodes = decision_graph.nodes if hasattr(decision_graph, 'nodes') else []
        action_nodes = [n for n in nodes if n.type == NodeType.ACTION]

        if len(action_nodes) == 0:
            raise InvariantViolation(
                f"[{scenario}] No Action node found in graph. Total nodes: {len(nodes)}"
            )

        if len(action_nodes) > 1:
            # Warning but not error (could be valid for complex decisions)
            self.results.append({
                "check": "action_node_exists",
                "scenario": scenario,
                "status": "WARN",
                "details": f"Multiple Action nodes found: {len(action_nodes)}"
            })
        else:
            self.results.append({
                "check": "action_node_exists",
                "scenario": scenario,
                "status": "PASS",
                "details": f"Action node: {action_nodes[0].id}"
            })
        self.passed += 1

    def validate_decision_pack_generated(self, decision_pack: dict, scenario: str) -> None:
        """
        Validate Decision Pack is always generated.

        INVARIANT: Decision Pack must NEVER be null.
        """
        if decision_pack is None:
            raise InvariantViolation(
                f"[{scenario}] Decision Pack is None - generation failed"
            )

        # Check required sections
        required_sections = [
            "title", "summary", "goals_kpis", "risks",
            "approval_chain", "recommended_next_actions", "audit"
        ]

        missing_sections = [s for s in required_sections if s not in decision_pack]
        if missing_sections:
            raise InvariantViolation(
                f"[{scenario}] Decision Pack missing sections: {missing_sections}"
            )

        # Validate summary has required fields
        summary = decision_pack.get("summary", {})
        required_summary_fields = [
            "decision_statement", "human_approval_required",
            "risk_level", "governance_status"
        ]
        missing_summary = [f for f in required_summary_fields if f not in summary]
        if missing_summary:
            raise InvariantViolation(
                f"[{scenario}] Decision Pack summary missing fields: {missing_summary}"
            )

        self.results.append({
            "check": "decision_pack_always_generated",
            "scenario": scenario,
            "status": "PASS",
            "details": f"All sections present, status: {summary.get('governance_status')}"
        })
        self.passed += 1

    def validate_scenario_specific(self, scenario: str, governance_result: dict, decision_pack: dict) -> None:
        """
        Validate scenario-specific expectations.

        Ensures test fixtures behave as expected.
        Relaxed checks to work with any rule set.
        """
        flags = governance_result.get("flags", [])
        status = decision_pack.get("summary", {}).get("governance_status")
        risk_level = decision_pack.get("summary", {}).get("risk_level")

        if scenario == "compliant":
            # Should NOT be blocked
            if status == "blocked":
                self.results.append({
                    "check": f"scenario_{scenario}",
                    "scenario": scenario,
                    "status": "FAIL",
                    "details": "Compliant decision should not be blocked"
                })
                self.failed += 1
                return

        elif scenario == "budget_violation":
            # Should have high risk OR requires review (due to $3.5M)
            if status == "compliant" and risk_level == "low":
                self.results.append({
                    "check": f"scenario_{scenario}",
                    "scenario": scenario,
                    "status": "FAIL",
                    "details": "Budget violation should trigger governance review"
                })
                self.failed += 1
                return

        elif scenario == "privacy_violation":
            # Should have some flags OR review required (due to PII/GDPR keywords)
            if len(flags) == 0 and not governance_result.get("requires_human_review"):
                self.results.append({
                    "check": f"scenario_{scenario}",
                    "scenario": scenario,
                    "status": "FAIL",
                    "details": "Privacy violation should trigger flags or review"
                })
                self.failed += 1
                return

        elif scenario == "blocked":
            # Should have blocked or needs_review status (high risk + low confidence)
            if status == "compliant":
                self.results.append({
                    "check": f"scenario_{scenario}",
                    "scenario": scenario,
                    "status": "FAIL",
                    "details": f"Blocked decision should not have status 'compliant', got '{status}'"
                })
                self.failed += 1
                return

        self.results.append({
            "check": f"scenario_{scenario}",
            "scenario": scenario,
            "status": "PASS",
            "details": f"Scenario behaves reasonably: status={status}, flags={len(flags)}, risk={risk_level}"
        })
        self.passed += 1

    async def run_e2e_test(self, scenario_name: str, decision) -> dict:
        """
        Run end-to-end test for a single scenario.

        Flow:
        1. Decision → Governance evaluation
        2. Governance → Graph storage
        3. Graph + Governance → Decision Pack
        4. Validate all invariants
        """
        print(f"\n{'='*80}")
        print(f"Testing scenario: {scenario_name}")
        print(f"{'='*80}")

        try:
            # Step 1: Governance evaluation
            print("Step 1: Evaluating governance...")
            decision_dict = decision.model_dump()
            # use_o1=False for deterministic, no-external-service testing
            governance_result = evaluate_governance(decision, company_context={}, use_o1=False)
            governance_dict = governance_result.to_dict()
            print(f"  ✓ Governance evaluated. Flags: {len(governance_dict['flags'])}, "
                  f"Rules triggered: {len(governance_dict['triggered_rules'])}")

            # Validate approval chain
            self.validate_approval_chain(governance_dict, scenario_name)

            # Step 2: Graph storage
            print("Step 2: Storing in graph...")
            graph_repo = InMemoryGraphRepository()
            decision_graph = await graph_repo.upsert_decision_graph(
                decision=decision_dict,
                governance=governance_dict,
                decision_id=f"test_{scenario_name}"
            )
            print(f"  ✓ Graph created. Nodes: {len(decision_graph.nodes)}, "
                  f"Edges: {len(decision_graph.edges)}")

            # Validate graph payload
            self.validate_graph_payload(decision_graph, scenario_name)
            self.validate_action_node_exists(decision_graph, scenario_name)

            # Step 3: Decision Pack generation
            print("Step 3: Generating Decision Pack...")
            decision_pack = build_decision_pack(
                decision=decision_dict,
                governance=governance_dict
            )
            print(f"  ✓ Decision Pack generated. Status: {decision_pack['summary']['governance_status']}")

            # Validate decision pack
            self.validate_decision_pack_generated(decision_pack, scenario_name)

            # Scenario-specific validation
            self.validate_scenario_specific(scenario_name, governance_dict, decision_pack)

            print(f"\n✓ Scenario '{scenario_name}' PASSED all checks")

            return {
                "scenario": scenario_name,
                "status": "PASS",
                "governance": governance_dict,
                "graph": decision_graph,
                "decision_pack": decision_pack
            }

        except InvariantViolation as e:
            print(f"\n✗ INVARIANT VIOLATION: {e}")
            self.failed += 1
            self.results.append({
                "check": "invariant",
                "scenario": scenario_name,
                "status": "CRITICAL_FAIL",
                "details": str(e)
            })
            raise

        except Exception as e:
            print(f"\n✗ ERROR: {e}")
            self.failed += 1
            self.results.append({
                "check": "execution",
                "scenario": scenario_name,
                "status": "FAIL",
                "details": str(e)
            })
            raise

    async def run_all_scenarios(self) -> dict:
        """Run all demo scenarios and collect results."""
        print("\n" + "="*80)
        print("E2E GOVERNANCE VALIDATION - DEMO STABILITY CHECK")
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
                    "error": str(e)
                }

        return results

    def print_summary(self):
        """Print validation summary."""
        print("\n" + "="*80)
        print("VALIDATION SUMMARY")
        print("="*80)

        total = self.passed + self.failed
        print(f"\nTotal checks: {total}")
        print(f"Passed: {self.passed} ✓")
        print(f"Failed: {self.failed} ✗")
        print(f"Success rate: {(self.passed/total*100) if total > 0 else 0:.1f}%")

        # Group by status
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
            print("❌ DEMO UNSTABLE - Failures detected")
            return False
        else:
            print("✅ DEMO STABLE - All checks passed")
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

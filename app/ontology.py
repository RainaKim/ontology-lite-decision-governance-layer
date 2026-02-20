"""
Ontology-Lite Layer - Relationship-based reasoning for decision governance.

Provides:
- Goal mapping based on organizational relationships (o1-powered)
- Owner validation against personnel hierarchy (o1-powered)
- Approval chain generation from org structure
- Constraint checking using graph traversal (o1-powered)

"Structure without graph overhead" - uses simple dict/list operations instead of graph DB.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple

from app.schemas import Decision, Owner, KPI
from app.o1_reasoner import O1Reasoner

logger = logging.getLogger(__name__)


class OntologyEngine:
    """
    Ontology-lite reasoning engine.

    Builds lightweight relationship graph from company data and provides
    relationship-aware governance reasoning.
    """

    def __init__(self, company_data_path: str = "mock_company.json", use_o1: bool = True):
        """
        Initialize ontology engine with company data.

        Args:
            company_data_path: Path to company governance JSON
            use_o1: Whether to use o1 reasoning (True) or heuristics (False)
        """
        self.company_data_path = Path(company_data_path)
        self.company_data = self._load_company_data()
        self.use_o1 = use_o1

        # Build relationship indices for fast lookup
        self.personnel_by_id = self._index_personnel()
        self.personnel_by_role = self._index_personnel_by_role()
        self.goals_by_id = self._index_goals()
        self.reporting_chain = self._build_reporting_chain()

        # Initialize o1 reasoner if enabled
        if self.use_o1:
            self.o1_reasoner = O1Reasoner(model="o4-mini")
            logger.info("o1 reasoning enabled for ontology layer")

        logger.info(f"Initialized OntologyEngine with {len(self.personnel_by_id)} personnel, "
                   f"{len(self.goals_by_id)} strategic goals")

    def _load_company_data(self) -> dict:
        """Load company data from JSON."""
        try:
            with open(self.company_data_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load company data: {e}")
            raise

    def _index_personnel(self) -> Dict[str, dict]:
        """Build personnel lookup by ID."""
        personnel = self.company_data.get('approval_hierarchy', {}).get('personnel', [])
        return {p['id']: p for p in personnel}

    def _index_personnel_by_role(self) -> Dict[str, dict]:
        """Build personnel lookup by role."""
        personnel = self.company_data.get('approval_hierarchy', {}).get('personnel', [])
        return {p['role'].upper(): p for p in personnel}

    def _index_goals(self) -> Dict[str, dict]:
        """Build strategic goals lookup by ID."""
        goals = self.company_data.get('strategic_goals', [])
        return {g['goal_id']: g for g in goals}

    def _build_reporting_chain(self) -> Dict[str, List[str]]:
        """
        Build reporting chain graph: person_id -> [manager_id, manager's_manager_id, ...]

        Example: david_004 -> [charlie_003, alice_001]
        """
        chain = {}

        for person_id, person in self.personnel_by_id.items():
            managers = []
            current_id = person_id

            # Traverse up the reporting chain
            visited = set()
            while current_id:
                if current_id in visited:  # Prevent infinite loops
                    break
                visited.add(current_id)

                current_person = self.personnel_by_id.get(current_id)
                if not current_person:
                    break

                reports_to = current_person.get('reports_to')
                if reports_to:
                    managers.append(reports_to)
                    current_id = reports_to
                else:
                    break

            chain[person_id] = managers

        return chain

    def map_decision_to_goals(self, decision: Decision) -> List[Dict]:
        """
        Map decision to strategic goals.

        Uses o1 reasoning if enabled, otherwise falls back to heuristics.

        Returns:
            List of matched goals with match reasons
        """
        if self.use_o1:
            return self._map_goals_with_o1(decision)
        else:
            return self._map_goals_with_heuristics(decision)

    def _map_goals_with_o1(self, decision: Decision) -> List[Dict]:
        """Use o1 reasoning for goal mapping."""
        # Prepare decision data for o1
        decision_data = {
            'decision_statement': decision.decision_statement,
            'goals': [{'description': g.description, 'metric': g.metric} for g in decision.goals],
            'kpis': [{'name': k.name, 'target': k.target} for k in decision.kpis],
            'owners': [{'name': o.name, 'role': o.role} for o in decision.owners]
        }

        # Get strategic goals
        company_goals = list(self.goals_by_id.values())

        # Call o1 reasoner
        o1_result = self.o1_reasoner.reason_about_goal_alignment(decision_data, company_goals)

        # Convert o1 result to our format
        mapped_goals = []
        for goal_mapping in o1_result.get('mapped_goals', []):
            mapped_goals.append({
                'goal_id': goal_mapping.get('goal_id'),
                'goal_name': self.goals_by_id.get(goal_mapping['goal_id'], {}).get('name'),
                'match_score': goal_mapping.get('alignment_score', 0) * 10,  # Scale to 0-10
                'match_reasons': [goal_mapping.get('reasoning', '')],
                'goal_owner_id': self.goals_by_id.get(goal_mapping['goal_id'], {}).get('owner_id'),
                'goal_priority': self.goals_by_id.get(goal_mapping['goal_id'], {}).get('priority'),
                'o1_confidence': goal_mapping.get('confidence'),
                'o1_alignment_type': goal_mapping.get('alignment_type')
            })

        logger.info(f"o1 mapped decision to {len(mapped_goals)} strategic goals")
        return mapped_goals

    def _map_goals_with_heuristics(self, decision: Decision) -> List[Dict]:
        """Fallback heuristic-based goal mapping (original implementation)."""
        matched_goals = []

        # Get decision text for keyword matching
        decision_text = f"{decision.decision_statement} {' '.join([g.description for g in decision.goals])}"
        decision_text_lower = decision_text.lower()

        # Extract KPI names from decision
        decision_kpi_names = [kpi.name.lower() for kpi in decision.kpis]

        # Extract owner names from decision
        decision_owner_names = [owner.name.lower() for owner in decision.owners]

        for goal_id, goal in self.goals_by_id.items():
            match_reasons = []
            match_score = 0

            # 1. Check KPI matching
            for goal_kpi in goal.get('kpis', []):
                goal_kpi_name = goal_kpi.get('name', '').lower()
                for decision_kpi_name in decision_kpi_names:
                    # Check for partial match
                    if goal_kpi_name in decision_kpi_name or decision_kpi_name in goal_kpi_name:
                        match_reasons.append(f"KPI match: {goal_kpi.get('name')}")
                        match_score += 2

            # 2. Check owner matching
            goal_owner_id = goal.get('owner_id')
            if goal_owner_id:
                goal_owner = self.personnel_by_id.get(goal_owner_id)
                if goal_owner:
                    goal_owner_name = goal_owner.get('name', '').lower()
                    if any(goal_owner_name in owner_name or owner_name in goal_owner_name
                           for owner_name in decision_owner_names):
                        match_reasons.append(f"Owner match: {goal_owner.get('name')}")
                        match_score += 3

            # 3. Check keyword matching in goal description
            goal_keywords = goal.get('description', '').lower().split()
            significant_keywords = [w for w in goal_keywords if len(w) > 4]  # Filter small words

            for keyword in significant_keywords[:5]:  # Check top 5 significant words
                if keyword in decision_text_lower:
                    match_reasons.append(f"Keyword match: {keyword}")
                    match_score += 1

            # 4. Check for explicit goal references (G1, G2, G3)
            if goal_id.lower() in decision_text_lower:
                match_reasons.append(f"Explicit goal reference: {goal_id}")
                match_score += 5

            if match_score > 0:
                matched_goals.append({
                    'goal_id': goal_id,
                    'goal_name': goal.get('name'),
                    'match_score': match_score,
                    'match_reasons': match_reasons,
                    'goal_owner_id': goal_owner_id,
                    'goal_priority': goal.get('priority')
                })

        # Sort by match score (highest first)
        matched_goals.sort(key=lambda x: x['match_score'], reverse=True)

        logger.info(f"Mapped decision to {len(matched_goals)} strategic goals")
        return matched_goals

    def validate_owners(self, decision: Decision) -> Dict:
        """
        Validate decision owners against personnel hierarchy.

        Uses o1 reasoning if enabled.

        Returns:
            validation_result with valid_owners, invalid_owners, warnings
        """
        if self.use_o1:
            return self._validate_owners_with_o1(decision)
        else:
            return self._validate_owners_with_heuristics(decision)

    def _validate_owners_with_o1(self, decision: Decision) -> Dict:
        """Use o1 reasoning for ownership validation."""
        # Prepare decision data
        decision_data = {
            'decision_statement': decision.decision_statement,
            'owners': [{'name': o.name, 'role': o.role, 'responsibility': o.responsibility}
                      for o in decision.owners]
        }

        # Get personnel list
        personnel = list(self.personnel_by_id.values())

        # Call o1 reasoner
        o1_result = self.o1_reasoner.reason_about_ownership_validity(decision_data, personnel)

        # Convert o1 result to our format
        valid_owners = []
        invalid_owners = []
        warnings = []

        for validated in o1_result.get('validated_owners', []):
            if validated.get('is_valid'):
                matched_person_id = validated.get('matched_person_id')
                if matched_person_id:
                    matched_person = self.personnel_by_id.get(matched_person_id)
                    # Find matching owner from decision
                    owner = next((o for o in decision.owners if o.name == validated['proposed_owner']), None)
                    if owner and matched_person:
                        valid_owners.append({
                            'owner': owner,
                            'matched_person': matched_person,
                            'person_id': matched_person_id,
                            'level': matched_person.get('level'),
                            'o1_reasoning': validated.get('reasoning')
                        })
            else:
                owner = next((o for o in decision.owners if o.name == validated['proposed_owner']), None)
                if owner:
                    invalid_owners.append({
                        'owner': owner,
                        'reason': validated.get('reasoning'),
                        'suggested_correction': validated.get('suggested_correction')
                    })
                    warnings.append(f"Owner '{owner.name}': {validated.get('reasoning')}")

        # Add missing owners warnings
        for missing in o1_result.get('missing_owners', []):
            warnings.append(f"Missing recommended owner: {missing}")

        return {
            'valid_owners': valid_owners,
            'invalid_owners': invalid_owners,
            'warnings': warnings,
            'all_valid': len(invalid_owners) == 0,
            'o1_ownership_issues': o1_result.get('ownership_issues', [])
        }

    def _validate_owners_with_heuristics(self, decision: Decision) -> Dict:
        """Fallback heuristic-based owner validation (original implementation)."""
        valid_owners = []
        invalid_owners = []
        warnings = []

        for owner in decision.owners:
            owner_name = owner.name.lower()
            owner_role = owner.role.lower() if owner.role else ""

            # Try to find in personnel
            found = False
            matched_person = None

            # Check by exact name match
            for person_id, person in self.personnel_by_id.items():
                person_name = person.get('name', '').lower()
                person_role = person.get('role', '').lower()

                if owner_name in person_name or person_name in owner_name:
                    found = True
                    matched_person = person
                    break

                # Also check role match if no name match
                if owner_role and owner_role in person_role:
                    found = True
                    matched_person = person
                    break

            if found and matched_person:
                valid_owners.append({
                    'owner': owner,
                    'matched_person': matched_person,
                    'person_id': matched_person.get('id'),
                    'level': matched_person.get('level')
                })
            else:
                invalid_owners.append({
                    'owner': owner,
                    'reason': 'Not found in personnel hierarchy'
                })
                warnings.append(f"Owner '{owner.name}' not found in personnel hierarchy")

        return {
            'valid_owners': valid_owners,
            'invalid_owners': invalid_owners,
            'warnings': warnings,
            'all_valid': len(invalid_owners) == 0
        }

    def build_approval_chain_from_org(self, decision: Decision, mapped_goals: List[Dict]) -> List[Dict]:
        """
        Build approval chain by traversing organizational structure.

        Strategy:
        1. Start with decision owners
        2. If decision maps to strategic goals, include goal owners
        3. Traverse up reporting chain to get all managers
        4. Deduplicate and order by level (highest first)

        Returns:
            List of approvers with person details
        """
        approvers = {}  # Use dict to deduplicate by person_id

        # 1. Add decision owners' managers
        owner_validation = self.validate_owners(decision)
        for valid_owner in owner_validation['valid_owners']:
            person_id = valid_owner['person_id']

            # Get reporting chain
            managers = self.reporting_chain.get(person_id, [])
            for manager_id in managers:
                if manager_id not in approvers:
                    manager = self.personnel_by_id.get(manager_id)
                    if manager:
                        approvers[manager_id] = {
                            'person_id': manager_id,
                            'name': manager.get('name'),
                            'role': manager.get('role'),
                            'level': manager.get('level'),
                            'reason': f"Manager in reporting chain of {valid_owner['owner'].name}"
                        }

        # 2. Add goal owners if decision maps to strategic goals
        for goal_match in mapped_goals[:2]:  # Top 2 matched goals
            goal_owner_id = goal_match.get('goal_owner_id')
            if goal_owner_id and goal_owner_id not in approvers:
                goal_owner = self.personnel_by_id.get(goal_owner_id)
                if goal_owner:
                    approvers[goal_owner_id] = {
                        'person_id': goal_owner_id,
                        'name': goal_owner.get('name'),
                        'role': goal_owner.get('role'),
                        'level': goal_owner.get('level'),
                        'reason': f"Owner of strategic goal {goal_match['goal_id']}"
                    }

        # Convert to list and sort by level (highest first)
        approval_chain = list(approvers.values())
        approval_chain.sort(key=lambda x: x['level'], reverse=True)

        logger.info(f"Built approval chain with {len(approval_chain)} approvers from org structure")
        return approval_chain

    def check_constraints(self, decision: Decision, mapped_goals: List[Dict], owner_validation: Dict) -> List[Dict]:
        """
        Check ontology constraints.

        Uses o1 reasoning if enabled.

        Returns:
            List of constraint violations
        """
        if self.use_o1:
            return self._check_constraints_with_o1(decision, mapped_goals, owner_validation)
        else:
            return self._check_constraints_with_heuristics(decision, mapped_goals, owner_validation)

    def _check_constraints_with_o1(self, decision: Decision, mapped_goals: List[Dict],
                                   owner_validation: Dict) -> List[Dict]:
        """Use o1 reasoning for constraint checking."""
        # Prepare decision data
        decision_data = {
            'decision_statement': decision.decision_statement,
            'goals': [{'description': g.description} for g in decision.goals],
            'kpis': [{'name': k.name, 'target': k.target} for k in decision.kpis],
            'owners': [{'name': o.name, 'role': o.role} for o in decision.owners],
            'risks': [{'description': r.description, 'severity': r.severity} for r in decision.risks]
        }

        # Call o1 reasoner
        o1_result = self.o1_reasoner.reason_about_constraint_violations(
            decision_data, mapped_goals, self.company_data
        )

        # Convert o1 violations to our format
        violations = []
        for violation in o1_result.get('violations', []):
            violations.append({
                'constraint': violation.get('constraint_type'),
                'severity': violation.get('severity'),
                'message': violation.get('description'),
                'impact': violation.get('impact'),
                'recommendation': violation.get('recommendation'),
                'o1_reasoning': True
            })

        return violations

    def _check_constraints_with_heuristics(self, decision: Decision, mapped_goals: List[Dict],
                                          owner_validation: Dict) -> List[Dict]:
        """Fallback heuristic-based constraint checking (original implementation)."""
        violations = []

        # Constraint 1: High-priority goals must have valid owners
        for goal_match in mapped_goals:
            if goal_match.get('goal_priority') in ['high', 'critical']:
                if not owner_validation['all_valid']:
                    violations.append({
                        'constraint': 'high_priority_goal_ownership',
                        'severity': 'high',
                        'message': f"Decision maps to high-priority goal {goal_match['goal_id']} but has invalid owners"
                    })

        # Constraint 2: Decision should have at least one valid owner
        if len(owner_validation['valid_owners']) == 0:
            violations.append({
                'constraint': 'valid_ownership',
                'severity': 'critical',
                'message': 'Decision has no owners that match personnel hierarchy'
            })

        # Constraint 3: If decision maps to multiple goals, check for owner alignment
        if len(mapped_goals) >= 2:
            goal_owner_ids = set()
            for goal_match in mapped_goals[:3]:
                owner_id = goal_match.get('goal_owner_id')
                if owner_id:
                    goal_owner_ids.add(owner_id)

            # Check if decision owners include goal owners
            decision_person_ids = set(vo['person_id'] for vo in owner_validation['valid_owners'])

            if not goal_owner_ids.intersection(decision_person_ids):
                violations.append({
                    'constraint': 'cross_goal_alignment',
                    'severity': 'medium',
                    'message': 'Decision maps to multiple strategic goals but decision owners do not include goal owners'
                })

        return violations

    def reason(self, decision: Decision) -> Dict:
        """
        Main ontology reasoning function.

        Performs:
        1. Goal mapping
        2. Owner validation
        3. Org-based approval chain
        4. Constraint checking

        Returns:
            Comprehensive ontology reasoning result
        """
        logger.info("Starting ontology-lite reasoning")

        # 1. Map to strategic goals
        mapped_goals = self.map_decision_to_goals(decision)

        # 2. Validate owners
        owner_validation = self.validate_owners(decision)

        # 3. Build approval chain from org structure
        org_approval_chain = self.build_approval_chain_from_org(decision, mapped_goals)

        # 4. Check constraints
        constraint_violations = self.check_constraints(decision, mapped_goals, owner_validation)

        result = {
            'mapped_goals': mapped_goals,
            'owner_validation': owner_validation,
            'org_approval_chain': org_approval_chain,
            'constraint_violations': constraint_violations,
            'ontology_flags': self._generate_flags(mapped_goals, owner_validation, constraint_violations)
        }

        logger.info(f"Ontology reasoning complete: {len(mapped_goals)} goals, "
                   f"{len(org_approval_chain)} approvers, {len(constraint_violations)} violations")

        return result

    def _generate_flags(self, mapped_goals: List[Dict], owner_validation: Dict,
                       constraint_violations: List[Dict]) -> List[str]:
        """Generate ontology-specific flags."""
        flags = []

        if not owner_validation['all_valid']:
            flags.append('INVALID_OWNER')

        if len(mapped_goals) == 0:
            flags.append('NO_GOAL_ALIGNMENT')

        if len(mapped_goals) >= 3:
            flags.append('MULTI_GOAL_CONFLICT_RISK')

        if any(v['severity'] == 'critical' for v in constraint_violations):
            flags.append('CRITICAL_CONSTRAINT_VIOLATION')

        return flags

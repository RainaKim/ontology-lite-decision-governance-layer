#!/bin/bash
# Test script for /extract endpoint with decision_pack response

echo "========================================="
echo "Testing /extract endpoint with decision_pack"
echo "========================================="
echo ""

# Set the API URL (change to deployed URL when ready)
API_URL="http://localhost:8000"

echo "Testing with compliant decision (PASS_001 from demo_cases.json)..."
echo ""

curl -X POST "${API_URL}/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "decision_text": "We should optimize our PostgreSQL database queries to reduce infrastructure costs by 15% and improve API response times from 800ms to under 400ms. This initiative directly supports our cost reduction goal (G3) and targets the $500/customer cost KPI (K6). Engineering Manager David will lead a 3-week sprint with 2 backend engineers to refactor the top 20 slowest queries, implement connection pooling, and add query result caching. Total cost: $18,000 (developer time only, no new infrastructure). Timeline: Start February 20, complete March 10. Risks include potential query regression bugs and temporary performance degradation during migration. Key assumptions: Current query patterns will remain stable, and caching hit rate will reach 70%. Success metrics: 50% reduction in database CPU usage, 50% improvement in P95 API latency. No customer-facing changes, no PII access required, internal optimization only.",
    "apply_governance_rules": true
  }' | python3 -m json.tool

echo ""
echo "========================================="
echo "Testing with non-compliant decision (FAIL_001 from demo_cases.json)..."
echo "========================================="
echo ""

curl -X POST "${API_URL}/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "decision_text": "We should launch a new AI-powered analytics dashboard for enterprise clients by end of Q2. This will require hiring 2 senior data engineers at $180k each, cloud infrastructure costs of $35k annually, and third-party ML API subscriptions at $15k/year. Total first-year cost: $230k. The dashboard will increase user engagement by 30% and help us compete with Tableau and PowerBI. Engineering Manager David will own delivery, with support from the data science team. Timeline: 12 weeks from approval. Key risks include integration complexity with existing data pipeline and potential performance issues at scale. We assume enterprise clients are willing to pay a 20% premium for AI features.",
    "apply_governance_rules": true
  }' | python3 -m json.tool

echo ""
echo "========================================="
echo "Test complete!"
echo "========================================="

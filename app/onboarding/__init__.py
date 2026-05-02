"""
app.onboarding — Phase 1 onboarding pipeline.

Onboarding runs once per client and populates the company's governance graph
in Neo4j from their existing artifacts.

Modules
-------
seed.py          Company domain graph seeder (Step 6).
                 Takes a CompanyConfig and writes Goal, Rule, Actor, KPI,
                 Jurisdiction, and Department nodes + their relationships.

scouts/          Scout swarm (Step 7 — LangGraph agents, parallel).
transform/       Transform pipeline (Step 7 — chunk → embed → ontologize → write).
"""

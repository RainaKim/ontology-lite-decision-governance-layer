# BUILD PLAN — Hackathon MVP

## Project
Ontology-lite Decision Governance Layer

---

## 🎯 Mission

Ship a minimal but production-looking system that demonstrates:

- structured enterprise decisions
- rule-based approval chains
- governance-aware decision packs

This is a **7-day hackathon MVP.**

Speed and reliability matter more than architectural perfection.

---

## ⚠️ Core Engineering Philosophy

Prefer:

✅ simplicity  
✅ determinism  
✅ deployability  
✅ demo stability  

Avoid:

❌ over-engineering  
❌ infrastructure-heavy systems  
❌ premature scaling  

Act like a senior startup engineer racing a deadline.

Cut everything non-essential.

---

## 🚫 What We Are NOT Building

Do NOT introduce:

- knowledge graphs
- Neo4j
- vector databases
- RAG pipelines
- enterprise integrations (Slack, Notion, etc.)
- distributed systems
- event streaming
- microservices

We are NOT modeling the entire enterprise.

We are modeling **decisions.**

---

## ✅ What We ARE Building

A minimal system that:

1. Converts decision text → structured Decision JSON  
2. Evaluates governance via lightweight rules  
3. Generates an approval chain  
4. Produces a Decision Pack  
5. Allows human review  

Nothing more.

---

## 🧱 Architecture Strategy

Keep the architecture intentionally thin.

Client  
→ FastAPI  
→ LLM Extractor  
→ Pydantic Validation  
→ Governance Rules  
→ Decision Pack  

Avoid additional layers unless absolutely necessary.

---

## 📅 Day 1–2 Scope (CRITICAL)

### Goal:
Reliable Decision Objectization.

### Must Ship:

- Pydantic Decision schema
- LLM structured extractor
- retry logic (max 2)
- fallback decision object
- `/extract` endpoint
- local run + deployable backend

### Success Criteria:

- endpoint returns valid JSON consistently
- schema validation never crashes the app
- failures degrade gracefully
- demo cannot break

---

## 🧠 Governance Strategy (Future — NOT Day 1–2)

Governance will later include:

- conditional approval chains
- risk thresholds
- owner enforcement
- audit logs

For now:

Design schemas with future fields in mind,
but DO NOT build the full engine yet.

---

## 🧪 Mocking Strategy

Prefer mock data over real integrations.

A realistic demo > a complex architecture.

---

## 🚀 Deployment Principle

Deploy early.

A live URL is more valuable than perfect code.

---

## 🔥 Most Important Rule

If forced to choose between:

- impressive architecture
- a stable demo

Choose the stable demo.

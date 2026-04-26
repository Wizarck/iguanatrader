# Phase 1: SD + OP Workflow (Steps 1.1-1.8)

**Goal**: Operations-facing technical blueprint (SD: decomposition, CMDB, fulfillment, technology, change mgmt, assurance) and detailed procedures (OP: SR, SA, MON). Together they are the **source of truth** — created first, then packaged into OD for customers.

**Source**: Derive from `02_OS/03_Offering_Taxonomy_Roadmap.md` (OTR) — NOT from OD (which doesn't exist yet).

#### Step 1.1: Service Decomposition
- Map CFS (from OTR) → RFS → Resource SKUs
- For RE: direct mapping (no RFS layer)
- **ASK USER** about RFS granularity:
  ```
  ❓ Decision needed: RFS decomposition granularity

  How should we decompose the internal services?
  - Option A: Consolidated (2-3 RFS) → Simpler CMDB, less tracking overhead
  - Option B: Granular (4-6 RFS) → Better impact analysis, more CMDB complexity

  Each RFS becomes a CMDB Application CI.
  ```
- Define Per User / Per Instance / Conditional resources
- **ASK USER** about conditional resources (which attributes trigger which resources)

#### Step 1.2: CMDB Structure
- Build CI hierarchy from decomposition
- Define Business Service CI with attributes from OTR
- Map all RFS and Resources to CIs
- **PRESENT** for review

#### Step 1.3: Fulfillment Workflow
- Design Order-to-Activation task sequence **organized by Phase** (matching SA phases from Step 1.5)
- Reference specific SA-XXX IDs in each workflow step
- Link each task to its RFS
- Estimate durations and automation %
- Note **parallelization opportunities** within phases (SAs with no inter-dependencies)
- Document **phase dependency chain** using taxonomic IDs (e.g., SA-001 → SA-002/SA-003 → SA-101/SA-201/SA-301 per-service → SA-004 → SA-005)
- Define validation gates before customer handover
- **ASK USER** about automation level:
  ```
  ❓ Decision needed: Automation approach

  For [task name]:
  - Option A: Fully automated (API call) → Fast but needs API integration
  - Option B: Semi-automated (script + human validation) → Safer but slower
  - Option C: Manual (human task) → No development needed but slower SLA

  This affects fulfillment time estimate.
  ```

#### Step 1.4: Technology Implementation Guides
- One guide per Deployment Platform from OTR
- Setup steps, prerequisites, API integrations, scripts
- Configuration standards, security baselines
- **PRESENT** for review

#### Step 1.5: Operational Playbook (OP)
- Create `OPERATIONAL_PLAYBOOK.md` using the OP template
- Define and author Service Requests (SR-XXX) **organized by Service Component** (matching OD components), with detailed procedures (steps, automation, SLA, error scenarios)
- Include a **Service-wide** SR section for cross-cutting requests (reporting, vendor case management)
- Define and author Setup Activities (SA-XXX) **organized by Phase** (matching fulfillment workflow phases), with detailed procedures (commands, rollback, dependencies)
- Note **parallelization** where SAs in the same phase can run concurrently
- Define and author Monitors (MON-XXX) **organized by Service Component**, with configuration (platform, thresholds, alert routing)
- Each MON must include **Alert (Yes/No)** and **Resolution** fields (action taken when threshold breached)
- **RACI note**: OP defines detailed procedures; RACI responsibility assignments are consolidated in the OD's RACI Matrix section (not in OP)
- **ASK USER** about operations scope:
  ```
  ❓ Decision needed: Service Requests scope

  Which service requests should this service support?
  - Option A: Basic (SR-0XX service-wide + 1-2 per-service SRs)
  - Option B: Standard (A + config changes, reporting across service ranges)
  - Option C: Comprehensive (full taxonomic coverage across all service ranges)

  Each SR/SA/MON authored in the OP will be summarized in the OD.
  ```
- Write escalation paths
- Write at least 1 incident response runbook
- **PRESENT** for review

#### Step 1.6: Change Management + Service Assurance (if Required)
- Define change types with examples
- Define rollback procedures
- Document availability design, SPOF analysis
- Document DR/BCP and capacity management
- **PRESENT** for review

#### Step 1.7: SD + OP Approval Gate
- Present complete SD and OP documents
- **"Aprobado? / Approved?"**
- Only proceed to Phase 2 after user confirms

#### Step 1.8: SD + OP QA
- **CALL `/qa-sd`** to validate SD + OP (independent validation — no OD exists yet)
- If ⚠️ → fix issues and re-validate
- If ✅ → proceed to Phase 2

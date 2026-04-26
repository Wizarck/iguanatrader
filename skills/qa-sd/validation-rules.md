# SD Validation Rules (Sections 1-10)

### 1. Structure & Applicability
- [ ] All required sections present per Delivery Type (see template applicability table)
- [ ] N/A sections omitted entirely (not left empty)
- [ ] Purpose section identifies companion OD and OP documents
- [ ] OPERATIONAL_PLAYBOOK.md exists if SD has MS delivery type
- [ ] Version History and Document Control present

### 2. TMF Service Decomposition
**For RE services**:
- [ ] Direct mapping: Product Offering → 1 Resource SKU (no RFS layer)
- [ ] No labor resources
- [ ] No tool resources

**For MS services (Full decomposition)**:
- [ ] CFS → RFS → Resource mapping complete
- [ ] Each RFS has description and at least 1 Resource SKU
- [ ] Resource SKU references match TABLE 3 naming (from 50_OPS_POV.md)
- [ ] Per User / Per Instance / Conditional resources clearly separated
- [ ] Conditional resources tied to specific OTR Service Attributes

**For MS services (Pass-Through — simplified)**:
- [ ] Direct mapping: Product Offering → Resources (no RFS layer) — valid for straightforward services
- [ ] Resource SKU references match TABLE 3 naming
- [ ] Labor resources present (distinguishes from PR)
- [ ] Per User / Per Instance / Conditional resources clearly separated

**For PS services**:
- [ ] Minimal decomposition (1-2 RFS: typically labor + tools)

### 3. Labor Resource Types
- [ ] Only LABOR-PS and LABOR-SS types used
- [ ] No LABOR-MS, LABOR-TAAS, LABOR-NOC, or other invented types
- [ ] Labor SKU format: `LABOR-[PS|SS]-[REGION]-[COVERAGE]` (no focus area — labor pools are shared)
- [ ] Labor allocation documented (hours/user/month or FTE)

### 4. CMDB Structure
- [ ] CI hierarchy matches TMF decomposition (Business Service → Application → Resource)
- [ ] Business Service CI has all required fields (Name, Class, SKU, Owner, Attributes)
- [ ] CI mapping table complete — every RFS and Resource has a CI
- [ ] Relationship types defined (Depends on, Runs on, Connected to)
- [ ] Tracking level appropriate for delivery type (RE=2 CIs, MS=4+)

### 5. Fulfillment Workflows
- [ ] Task count meets minimum per delivery type:
  - RE: ≤ 2 tasks
  - MS (Pass-Through): ≥ 4 tasks
  - MS (Full): ≥ 8 tasks
  - PS: varies (1-10)
- [ ] Each task has: System, Actions, Duration, Owner
- [ ] Resource SKU referenced where applicable
- [ ] RFS linkage noted for each task (which RFS does this task provision?)
- [ ] Validation gates present before customer handover
- [ ] Hand-off table present (if multiple teams involved)
- [ ] Total fulfillment time estimated with automation %
- [ ] Decommissioning workflow present (for MS): data handling, resource release, CMDB cleanup
- [ ] **Phase organization**: Workflow steps grouped by Phase (matching SA phases in Section 5)
- [ ] **SA references**: Each fulfillment step references its corresponding SA-XXX ID
- [ ] **Phase dependency chain**: Documented using taxonomic IDs (e.g., SA-001 → SA-002/SA-003 → SA-101/SA-201 per-service → SA-004 → SA-005)
- [ ] **Parallelization**: Noted where SAs within a phase can run in parallel

### 5.5. Service Dependencies (if applicable)
- [ ] Upstream dependencies documented (what this service requires)
- [ ] Downstream dependencies documented (what depends on this service)
- [ ] Impact if unavailable described for each dependency

### 5.6. Monitor Thresholds
- [ ] MON configurations use "Default Thresholds" pattern (not fixed values)
- [ ] Each threshold has: Default value + Allowed Range
- [ ] Note indicates thresholds are adjusted per customer during onboarding

### 5.7. Knowledge Management (if applicable)
- [ ] Runbook locations documented
- [ ] Training requirements identified
- [ ] Vendor documentation referenced

### 6. SD-OD Alignment (only in `--alignment` mode, after OD exists)
> **Skip this section if OD does not exist yet (Phase 1 independent validation).**

- [ ] **Every SR-XXX in OP** has a matching summary in OD Operations table
- [ ] **Every SA-XXX in OP** has a matching summary in OD Operations table
- [ ] **Every MON-XXX in OP** has a matching summary in OD Operations table
- [ ] No orphan IDs in OD (every OD operation ID exists in OP — OD must not invent IDs)
- [ ] CFS/RFS in SD map logically to Service Components in OD
- [ ] OD components are infrastructure/technology pieces only — not protocols, operational activities, or deliverables
- [ ] Technology Implementation Guides in SD have corresponding Deployment Platforms in OD

### 7. Operational Procedures (if applicable)
- [ ] SR procedures have: Catalog Item, Fulfillment Method, Steps, Validation, SLA, Error Scenarios
- [ ] **SRs organized by Service Component** (with `#### Component:` headers matching OD components)
- [ ] **Service-wide SRs** section present for cross-cutting requests (reporting, vendor case mgmt)
- [ ] SA procedures have: Prerequisites, Steps (with commands), Duration, Dependencies, Rollback
- [ ] **SAs organized by Phase** (with `#### Phase N:` headers matching fulfillment workflow phases)
- [ ] **SA parallelization** documented where applicable (SAs in same phase with no inter-dependencies)
- [ ] MON configurations have: Platform, Type, Metric, Default Thresholds (with ranges), Alert Routing
- [ ] **MONs organized by Service Component** (with `#### Component:` headers matching SR grouping)
- [ ] **MON Alert field**: Each MON has explicit Alert (Yes/No) indicating active alert vs informational
- [ ] **MON Resolution field**: Each MON has Resolution text (action taken when threshold breached)
- [ ] Escalation paths defined with levels, contacts, response times
- [ ] At least 1 incident response runbook present

### 8. Change Management (if applicable)
- [ ] Standard/Normal/Emergency change types defined with examples
- [ ] Testing requirements table present
- [ ] Rollback procedure defined with triggers, steps, time estimate, point of no return

### 9. Service Assurance (if applicable)
- [ ] Availability design documented (resilience pattern, SPOF analysis)
- [ ] Service continuity: RTO/RPO defined (published to OD Offer Attributes)
- [ ] Capacity management: current capacity, scaling triggers, growth planning

### 10. Content Quality
- [ ] No [placeholder] text remaining in populated sections
- [ ] Procedures are actionable (specific commands/tools, not abstract descriptions)
- [ ] No financial information (no costs, revenue, margin calculations)
- [ ] No customer-facing language (this is an internal document)

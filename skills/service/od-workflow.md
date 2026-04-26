# Phase 2: OD Workflow (Steps 2.1-2.6)

**Goal**: Customer-facing offer description derived from SD + OP. Packages the technical design into components, operations summary, and attributes for the customer catalogue.

**Source**: Derive from SD + OP (just created) + `02_OS/03_Offering_Taxonomy_Roadmap.md` (OTR).

#### Step 2.1: Metadata + Overview
- Fill metadata table from OTR
- Write Overview specific to this service (not generic)
- Write Key Benefits (specific and measurable)
- **ASK USER** to validate overview and benefits

#### Step 2.2: Prerequisites, Lifecycle, Change Management & Table of Services
- Write "Offer - Prerequisites & Customer Responsibilities" (Prerequisite | Notes — no "Responsibility" column)
- Write "Services Lifecycle" (H2) BEFORE Table of Services:
  - Standard rows: Order / Modify / Cancel with lead times
  - Extended rows (when applicable): Suspend (Lay-Up) / Reactivate / Upgrade / Downgrade
  - Notes: Lay-Up freezes MS fees; RE fees subject to CSP/vendor terms (annual commitments not freezable). Tier changes via Non-Standard Change Request.
- Write "Change Management" (H2) AFTER Services Lifecycle, BEFORE Table of Services:
  - 3-tier model table: Standard Change (existing SRs) / Non-Standard Change (assessment + quote) / Emergency Change (immediate action)
  - Columns: Type | Scope | Process | Lead Time
- List all services from OTR (Service Name | Delivery Type | Description)
- Delivery Type Codes legend inline below table
- Optional: IMPORTANT box (when service depends on customer subscription)
- Optional: Service Dependency blockquote after IMPORTANT box (when one service requires another)
- Optional: Supported Configurations (H2, when multiple deployment environments)
- **PRESENT** for approval

#### Step 2.3: Per-Service Details

**Heading hierarchy**: H2 = `## Service: [Name]` (numbered), H3 = all sub-items (in TOC)
**Naming convention**: "Offer - " prefix (H2, offer-level), "Component - " prefix (H2, prerequisites), no prefix for service sub-sections

For each service in the Table of Services:

**RE services** (simple):
- Description paragraph + What's Included (H3) + `### Supported Technologies` as bullet list + Out of Scope (H3)
- No components, no operations

**MS services** (lightweight — operations are at offer level):

**a) What's Included** (H3):
- Bullet list of included features/capabilities

**b) Service Components** (H3, desacoplado format):
- Each component as H3 heading with description paragraph
- 2-column table per component: Platform | Supported Technologies (techs on separate lines via `<br>`)
- **Component criteria**: discrete infrastructure/software/technology with own deployable resource. Exclude: protocols (BGP, OSPF), operational activities, deliverables.
- **ASK USER** to confirm deployment platforms

**c) Limitations** (H3, inside service):
- Table: ID | Description | Workaround / Alternative

**d) Service Attributes** (H3, inside service — optional):
- One H3 per attribute with value table: Value | Description | Affects Price
- Include only service-specific attributes (technology, vendor, capacity tier)
- Omit for services with no meaningful attribute (single-option services)
- **ASK USER** which attributes apply to this service

**e) Out of Scope** (H3, inside service):
- List of tasks not included in this managed service

#### Step 2.4: Operations (offer-level, grouped by component)

All operations sections are H2 at offer level — they apply across ALL managed services. Grouped by component (H3), not by service.

**a) Component - Prerequisites & Customer Responsibilities** (H2):
- H3 headings per component
- No Supported Technologies lines (already in Service Components tables)
- No table — bullet lists per component

**b) Client Notifications** (H2):
- Grouped by H3 per component. Service-wide first, then by component
- Tables: 4 columns — Type | Trigger | Method | Recipient (no Component column)

**c) Setup Activities** (H2):
- **No RACI columns** in any SA table (RACI is consolidated in RACI Matrix section)
- Phases as H3: `### [Phase Name]` (no "Phase N:" prefix)
- SA tables: 3 columns only — ID | Name | Description
- `### Out of Scope` (H3) after last phase
- IDs must match OP exactly — do not invent new IDs

**d) Service Requests** (H2):
- Grouped by H3 per component. Service-wide first, then by component
- Tables: 4 columns — ID | Name | Description | SLA (no Component column)
- **No RACI columns** in SR table
- SLA disclaimer as blockquote below last component table

**e) SLA Reference Table** (H3, inside Service Requests):
- P1-P4 priority table (Response Time + Resolution Time)
- SR = 24x7 CET, SA = 8x5 CET
- Scheduled operations note

**f) Available Monitors** (H2):
- Grouped by H3 per component. Service-wide first, then by component
- Tables: 5 columns — ID | Name | Metric | Alert (Yes/No) | Resolution (no Component column)

#### Step 2.5: RACI Matrix & Offer-level closing sections

**a) RACI Matrix** (H2):
- Consolidated responsibility matrix covering ALL operational activities (SAs, SRs, MONs)
- One table per component (Service-wide first, then by component)
- Table columns: Activity | IDs | Marlink | Customer
- Activity = descriptive name; IDs = grouped SR/SA/MON IDs (one per line via `<br>`)
- RACI values: R (Responsible), A (Accountable), C (Consulted), I (Informed)
- Setup Activities grouped by phase within the Service-wide table
- Position: AFTER Available Monitors, BEFORE Offer Attributes / Offer - Out of Scope

**b) Offer Attributes** (H2, optional — only for cross-cutting attributes):
- Include only attributes that genuinely apply to ALL managed services (SLA Tier, Support Hours, Compliance Framework)
- Service-specific attributes (technology, capacity) belong in Service Attributes inside each service
- One H3 per attribute with value table: Value | Description | Affects Price
- "Affects Price" uses X marker — no dollar amounts (pricing in LEAN_BUSINESS_CASE.md)
- Omit entirely if all attributes are service-specific
- **ASK USER** which cross-cutting attributes apply

**c) Offer - Out of Scope** (H2, LAST section — always):
- General exclusions that apply to the entire offering
- Always the final section in the document

#### Step 2.6: OD Approval Gate
- Present complete OD document
- **"Aprobado? / Approved?"**

#### Step 2.7: OD QA
- **CALL `/qa-od`** to validate OD
- If ⚠️ → fix issues and re-validate
- If ✅ → run final alignment check

#### Step 2.8: Final SD-OD Alignment Check
- **CALL `/qa-sd --alignment`** to verify SD-OD ID consistency
- If ⚠️ → fix issues in OD (SD + OP are source of truth)
- If ✅ → complete

# OD Validation Rules (Sections 1-8)

### 1. Metadata & Structure
- [ ] All metadata fields present (Service Offering, Pillar, Delivery Type, Owner, Status, Version, Updated)
- [ ] Delivery Type correctly identified
- [ ] Document title follows pattern: "Offer Description (OD): [Service Name]"

### 1.5. Heading Hierarchy
- [ ] H2 = numbered sections: services (`## Service: [Name]`), operations (`## Service Requests`, `## Setup Activities`, etc.), offer-level (`## Offer - Out of Scope`, `## Offer Attributes`)
- [ ] H3 = all sub-items within H2 sections (components, phases, component groups, Limitations, Out of Scope, SLA Reference Table) — appears in TOC, no numbering
- [ ] H5 = fallback bold paragraph (NOT in TOC) — rarely used in v7+ structure
- [ ] No H4 or H6 headings used

### 2. Prerequisites, Scope & Lifecycle
- [ ] "Offer - Prerequisites & Customer Responsibilities" (H2) present with specific items (not placeholders)
- [ ] Offer Prerequisites table uses columns: Prerequisite | Notes (no "Responsibility" column)
- [ ] "Services Lifecycle" (H2) present BEFORE Table of Services
- [ ] Standard lifecycle rows present: Order / Modify / Cancel with lead times
- [ ] Extended lifecycle rows (when applicable): Suspend (Lay-Up) / Reactivate / Upgrade / Downgrade
- [ ] Lay-Up note: MS fees frozen, RE fees subject to CSP/vendor terms
- [ ] Tier changes via Non-Standard Change Request
- [ ] Minimum Contract Term and Billing Cycle defined
- [ ] Delivery Type Codes legend placed inline below Table of Services (not as separate section)

### 2.3. Change Management
- [ ] "Change Management" (H2) present AFTER Services Lifecycle, BEFORE Table of Services
- [ ] 3-tier model: Standard Change (existing SRs) / Non-Standard Change (assessment + quote) / Emergency Change (immediate action)
- [ ] Table columns: Type | Scope | Process | Lead Time
- [ ] Standard Changes reference existing SR IDs
- [ ] Non-Standard Changes require assessment + formal quote
- [ ] Emergency Changes have immediate action + retrospective documentation

### 2.5. Naming Convention
- [ ] "Offer - " prefix for offer-level sections at H2 (e.g., "Offer - Prerequisites & Customer Responsibilities", "Offer - Out of Scope")
- [ ] "Component - " prefix for component prerequisites at H2 (e.g., "Component - Prerequisites & Customer Responsibilities")
- [ ] No prefix for service sub-sections at H3: "Limitations" (NOT "Service — Limitations"), "Out of Scope" (NOT "Service — Out of Scope" or "Setup — Out of Scope")
- [ ] Section names match exactly: "Services Lifecycle" (not "Service Lifecycle"), "Offer Attributes" (not "Service Offer Attributes"), "SLA Reference Table" (not "SLA Reference")

### 3. Applicability by Delivery Type
- [ ] Sections marked N/A in template are OMITTED (not left empty)
- [ ] Sections marked Required are PRESENT and populated
- [ ] Sections marked Optional are either populated or omitted (not empty stubs)

**All Delivery Types**:
- [ ] Offer - Prerequisites & Customer Responsibilities present
- [ ] Offer - Out of Scope present (LAST section in document)
- [ ] Services Lifecycle present
- [ ] Delivery Type codes use only RE/MS/PS (not PF, SS, CS)

**RE Delivery Type specific**:
- [ ] No operations sub-sections, no Offer Attributes
- [ ] No Client Notifications
- [ ] `### Supported Technologies` heading (in TOC) AFTER What's Included, as bullet list
- [ ] Description + What's Included / Supported Technologies / Out of Scope (H3, simple structure, no components)

**MS Delivery Type specific**:
- [ ] Service section is lightweight: What's Included, Service Components (desacoplado), Limitations, Out of Scope
- [ ] Operations sections at OFFER LEVEL (H2): Component - Prerequisites, Client Notifications, Setup Activities, Service Requests, Available Monitors
- [ ] Operations grouped by COMPONENT (H3), not by service
- [ ] Service Components in desacoplado format: each component as H3 with description + 2-col table (Platform | Supported Technologies)
- [ ] Supported Technologies in component tables use `<br>` for line separation
- [ ] `**Supported Technologies**:` bold inline under each H3 component in Component - Prerequisites
- [ ] SLA Reference Table inside Service Requests as H3 (not separate H2)
- [ ] Offer Attributes present at H2 level (outside services) — one H3 per attribute with value table

**PS Delivery Type specific**:
- [ ] Minimal structure (Overview + Table of Services)
- [ ] Operations only if applicable to the specific PS type

### 4. Table of Services & Service Compliance
- [ ] Table of Services uses descriptive service names (no SKU codes in table)
- [ ] Table of Services columns: Service Name | Delivery Type | Description
- [ ] Services in Table of Services align with `02_OS/03_Offering_Taxonomy_Roadmap.md`
- [ ] Delivery Type is specified for each service (RE / MS / PS)
- [ ] No duplicate services
- [ ] Optional: IMPORTANT box after Table of Services (when managed service depends on customer subscription)
- [ ] Optional: Service Dependency blockquote after IMPORTANT box (when one service requires another — e.g., "Service A requires Service B")
- [ ] Optional: Supported Configurations (H2) after Table of Services (when multiple deployment environments exist)

### 4.5. Supported Technologies
- [ ] **RE services**: `### Supported Technologies` heading (H3, in TOC) AFTER What's Included, as bullet list (one technology per line)
- [ ] **MS services**: Technology info ONLY inside each component's 2-column table (Platform | Supported Technologies) in Service Components section
- [ ] **MS Component Prerequisites**: NO Supported Technologies lines — technologies already in Service Components table
- [ ] Technologies listed match the key product/platform (RE) or component-specific tools/APIs (MS)

### 5. Service Components (MS services)
- [ ] Desacoplado format: each component as H3 heading with description paragraph + 2-column table
- [ ] Table columns: Platform | Supported Technologies (2 columns — NO Component or Overview columns in the table)
- [ ] Technologies within table cells on separate lines using `<br>` tags
- [ ] **Component criteria**: each component is a discrete piece of infrastructure, software, or technology platform that has its own deployable resource and can be independently configured
- [ ] **NOT components**: protocols (BGP, OSPF), operational activities (monitoring, alerting, reporting), deliverables (reports, notifications) — these belong to the delivery model or Client Notifications
- [ ] Deployment Platforms are specific (not generic placeholders)

### 6. Operations (offer-level, MS services)

All operations sections are at H2 (offer level), grouped by component (H3). They apply across ALL managed services in the offering.

**6a. Component - Prerequisites & Customer Responsibilities** (H2):
- [ ] H3 headings for each component (no "Component:" prefix)
- [ ] No Supported Technologies lines — technologies are in Service Components tables
- [ ] Components with NO prerequisites are OMITTED (no empty headings)
- [ ] No table format — each component has its own bullet list
- [ ] Each prerequisite sits under the component it belongs to

**6b. Client Notifications** (H2):
- [ ] Grouped by H3 headings for each component. Service-wide first, then by component
- [ ] Table columns: Type | Trigger | Method | Recipient (4 columns, no Component column)

**6c. Setup Activities** (H2):
- [ ] **No RACI columns** (R/A/C/I) in any SA table (RACI is consolidated in RACI Matrix section)
- [ ] Phases as H3 headings: `### [Phase Name]` (no "Phase N:" prefix — just the name)
- [ ] SA tables: 3 columns only — ID | Name | Description
- [ ] `### Out of Scope` (H3) after last phase (NOT "Setup — Out of Scope")
- [ ] SA IDs unique and follow taxonomic range convention (e.g., SA-001..SA-005 cross-service, SA-101 component 1, SA-301 component 3 — ranges encode component ownership)

**6d. Service Requests** (H2):
- [ ] Grouped by H3 headings for each component (no "Component:" prefix)
- [ ] **Service-wide first**, then by component
- [ ] Table columns: ID | Name | Description | SLA (4 columns, no Component column)
- [ ] **No RACI columns** in SR table
- [ ] SLA column uses P1-P4 values
- [ ] SLA disclaimer as blockquote below last component table referencing SLA Reference Table
- [ ] SR IDs unique and follow taxonomic range convention (e.g., SR-0XX service-wide, SR-1XX component A, SR-2XX component B — ranges encode component ownership)

**6e. SLA Reference Table** (H3, inside Service Requests):
- [ ] `### SLA Reference Table` present inside Service Requests section
- [ ] NOT as separate H2 section — it's a sub-section of Service Requests
- [ ] Table uses Priority levels: P1 (Critical), P2 (High), P3 (Normal), P4 (Low)
- [ ] Each priority has Description, Response Time, and Resolution Time
- [ ] **Service Requests**: 24x7 CET noted below table
- [ ] **Setup Activities**: 8x5 CET noted below table
- [ ] Note present: "Scheduled operations are not subject to priority-based SLA"

**6f. Available Monitors** (H2):
- [ ] Grouped by H3 headings for each component. Service-wide first, then by component
- [ ] Table columns: ID | Name | Metric | Alert (Yes/No) | Resolution (5 columns, no Component column)
- [ ] MON IDs unique and follow taxonomic range convention (e.g., MON-0XX service-wide, MON-1XX component A — ranges encode component ownership)

**6g. Service Limitations** (H3, inside service):
- [ ] `### Limitations` (NOT "Service — Limitations")
- [ ] Table columns: ID | Description | Workaround / Alternative
- [ ] Inside the MS service section (not at offer level)

**6h. Service Out of Scope** (H3, inside service):
- [ ] `### Out of Scope` (NOT "Service — Out of Scope")
- [ ] List of tasks not included in the managed service
- [ ] Inside the MS service section (not at offer level)

**6i. General Operations Rules**:
- [ ] All IDs (SR/SA/MON) are unique and follow taxonomic range convention (0XX=service-wide, 1XX/2XX/3XX/4XX=per-component)
- [ ] Each SR/SA/MON has meaningful description
- [ ] No RACI columns in any operations table (RACI consolidated in RACI Matrix section)

**6j. RACI Matrix** (H2):
- [ ] "RACI Matrix" (H2) present AFTER Available Monitors, BEFORE Offer Attributes / Offer - Out of Scope
- [ ] One table per component (Service-wide first, then by component)
- [ ] Table columns: Activity | IDs | Marlink | Customer
- [ ] IDs column contains SR/SA/MON IDs grouped (one per line via `<br>`)
- [ ] Setup Activities grouped by phase within the Service-wide table
- [ ] RACI values use only: R (Responsible), A (Accountable), C (Consulted), I (Informed)
- [ ] Every SR/SA/MON ID in the document appears in exactly one RACI table row
- [ ] No RACI assignment block inside Setup Activities section (consolidated here)

### 6.5. SD/OP-Derived Consistency (if SD + OP exist)
> **This section validates that OD operations are correctly derived from the companion SD and Operational Playbook.**
> If SD/OP do not exist yet, skip — but flag that OD was created without its source documents.

- [ ] **Every SR-XXX in OD** exists as a detailed procedure in OP (OD must not invent SR IDs)
- [ ] **Every SA-XXX in OD** exists as a detailed procedure in OP (OD must not invent SA IDs)
- [ ] **Every MON-XXX in OD** exists as a configuration in OP (OD must not invent MON IDs)
- [ ] No orphan IDs in OD — every ID in OD has a matching OP procedure
- [ ] OD Service Components map to SD's CFS → RFS decomposition
- [ ] OD Deployment Platforms match SD's Technology Implementation Guides
- [ ] OD Limitations are consistent with SD's technical constraints

### 7. Attributes

**7a. Service Attributes** (H3, inside each MS service — optional):
- [ ] `### Service Attributes` heading inside MS service section, before `### Out of Scope`
- [ ] One sub-section (H3) per attribute with a value table (Value | Description | Affects Price)
- [ ] Contains only service-specific attributes (technology, vendor, capacity tier)
- [ ] Omitted for services with no meaningful attribute (single-option services)
- [ ] "Affects Price" column uses X marker (no dollar amounts or margins — pricing details in LEAN_BUSINESS_CASE.md)

**7b. Offer Attributes** (H2, offer-level — optional):
- [ ] Section at H2 level, outside all services
- [ ] Contains only truly cross-cutting attributes that apply to ALL managed services (SLA Tier, Support Hours, Compliance Framework)
- [ ] Service-specific attributes (technology, capacity) belong in Service Attributes, NOT here
- [ ] Omitted entirely if all attributes are service-specific
- [ ] One sub-section (H3) per attribute with a value table (Value | Description | Affects Price)
- [ ] "Affects Price" column uses X marker (no dollar amounts or margins)

### 7.5. Pricing & Segment Firewall
- [ ] No dollar amounts ($) anywhere in the document
- [ ] No margins, costs, or pricing notes
- [ ] No segment-specific strategies or eligibility rules (belong in OTR / LEAN_BUSINESS_CASE.md)
- [ ] No SKU codes in Table of Services (use descriptive service names)
- [ ] Microsoft license families referred to generically (e.g., "Microsoft 365 Licenses") not by individual SKU

### 7.7. Document Order
- [ ] Overview → Offer - Prerequisites → Services Lifecycle → Change Management → Table of Services → [Supported Configurations] → Services (RE then MS, with Service Attributes inside MS services) → Component - Prerequisites → Client Notifications → Setup Activities → Service Requests (with SLA Reference Table) → Available Monitors → RACI Matrix → [Offer Attributes] → Offer - Out of Scope
- [ ] "Offer - Out of Scope" is always the LAST section in the document
- [ ] "RACI Matrix" appears AFTER Available Monitors, BEFORE Offer Attributes / Offer - Out of Scope
- [ ] "Offer Attributes" (if present) appears AFTER RACI Matrix, BEFORE Offer - Out of Scope
- [ ] "Service Attributes" (if present) appears inside each MS service, BEFORE Out of Scope
- [ ] "Change Management" appears AFTER Services Lifecycle, BEFORE Table of Services

### 8. Content Quality
- [ ] Overview is specific to this service (not generic template text)
- [ ] No [placeholder] text remaining in populated sections
- [ ] Benefits are specific and measurable
- [ ] Descriptions are customer-appropriate language (no internal jargon)
- [ ] No iteration/roadmap references (e.g., "Iteration 1", "planned for", "future phase")
- [ ] No use cases or segment strategies (belong in OTR / LEAN_BUSINESS_CASE.md)
- [ ] No delivery center references (unless multi-region is a service attribute)

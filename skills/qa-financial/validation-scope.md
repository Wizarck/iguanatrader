# Financial Validation Scope (Sections 1-6b)

### 1. Pricing Formula Validation

**Standard Margins by Delivery Type**:

| Delivery Type | Overhead | Target Margin | Price Formula |
|---------------|----------|---------------|---------------|
| **RE (Resell)** | None | 15% | `Cost ÷ 0.85` |
| **MS (Managed Services)** | Labor × 1.15 | 35% | `(Labor × 1.15) ÷ 0.65` or `(Labor × 1.15 + Fixed) ÷ 0.65` |
| **PS (Professional Services)** | Labor × 1.15 | 45% | `(Labor × 1.15) ÷ 0.55` |

**Pass-Through Rule**:
```
CRITICAL: 15% overhead applies ONLY to labor costs.
Pass-through items have NO overhead:
- Licenses (Microsoft, third-party software)
- Hardware/VM costs
- Partner products (resale)
```

**Validation Process**:
1. Read each SKU from `OFFER-XXX/RESOURCES.md` TABLE 3
2. Identify Delivery Type from SKU code (e.g., CIT-RE-XXX = RE, CIT-MS-XXX = MS)
3. Separate cost into: Labor vs Pass-Through
4. Apply correct formula
5. Compare calculated price vs documented price
6. Flag discrepancies with delta %

---

### 2. ARPU Calculation Validation

**Generic ARPU Formula**:
```
ARPU = Σ(SKU_Price × Quantity_per_RGU)
```

**Validation Process**:
1. List all SKUs included in 1 RGU
2. For variable SKUs: verify quantity calculation
3. For fixed SKUs: verify single price per RGU
4. Sum all components
5. Compare calculated ARPU vs documented ARPU
6. Repeat for each segment if segment-specific ARPU exists

---

### 3. ARPU↔RGU Table Validation

**CRITICAL RULE**: Every table showing ARPU ($) MUST also show RGU (units).

**Validation Process**:
1. Scan all tables in LEAN_BUSINESS_CASE.md and financial.md
2. If table contains ARPU column → must have RGU column
3. If table contains Revenue column → must have RGU column
4. ARPU and RGU must be in SEPARATE columns (never combined)

**Valid Table Example**:
```markdown
| Segment | RGUs | ARPU ($) | Revenue |
|---------|------|----------|---------|
| Merchant | 100 | $9,768 | $976,800 |
```

**Invalid Table Examples**:
```markdown
# Missing RGU column
| Segment | ARPU ($) | Revenue |  ← INVALID
|---------|----------|---------|

# Combined ARPU/RGU
| Segment | ARPU/RGU |  ← INVALID (use separate columns)
|---------|----------|
```

---

### 4. RGU Calculation Validation

**Generic RGU Formula**:
```
Addressable_RGUs = Total_Base × Adoption_Filter
```

**Validation Process**:
1. Verify Total_Base from source (e.g., 12_Customer_Base.md)
2. Verify Adoption_Filter justified with source
3. Calculate Addressable_RGUs
4. Compare with documented value

---

### 5. Revenue Forecast Validation

**Formulas**:
```
New_Business_Revenue = New_RGUs × ARPU
Cross_Sell_Revenue = Installed_Base × Penetration_Rate × Weighted_ARPU
Total_Revenue = New_Business + Cross_Sell
YoY_Growth = (Year_N - Year_N-1) ÷ Year_N-1 × 100
```

**Validation Process**:
1. Verify each year's calculation
2. Check cumulative totals
3. Verify YoY growth percentages
4. Cross-check Section 4 tables internally consistent

---

### 6. Cross-File Consistency

### 6a. Cost-vs-Research Validation

**CRITICAL**: Business Case cost assumptions must be traceable to `00_Research/financial.md`.

**Validation Process**:
1. Read cost breakdown from LEAN_BUSINESS_CASE.md (Section 4.5-4.6 / 6.1)
2. Read cost research from `OFFER-XXX/00_Research/financial.md`
3. Compare each cost line: BC value vs Research value
4. Flag discrepancies >10% with **[COST MISMATCH]** tag
5. If no research source exists for a cost, flag as **[COST UNVALIDATED]**

**Common Errors**:
- AI inventing labor hours not supported by research (e.g., 10h when research shows 4-5h)
- Infrastructure costs rounded or approximated without citing source
- Software/tools costs classified as labor (should be fixed/pass-through)

---

### 6b. Cross-File Consistency (Documents)

**Documents to Cross-Reference**:

| Document | Fields to Match |
|----------|-----------------|
| `OFFER-XXX/00_Research/financial.md` | ARPU by segment, SKU costs |
| `OFFER-XXX/RESOURCES.md` | TABLE 3 pricing |
| `OFFER-XXX/LEAN_BUSINESS_CASE.md` | Section 4.4 ARPU, Section 4.7-4.8 Forecasts |
| `10_MARLINK/40_Market/12_Customer_Base.md` | Installed Base |

---

### 7. Source Traceability (End-to-End, All Financial Claims)

**CRITICAL**: Every quantitative claim in LEAN_BUSINESS_CASE.md must trace to its **original source** — not just the intermediary research file. The full provenance chain must be visible so any number can be verified back to where it was first published.

**Citation format required**:
| Scenario | Format | Example |
|----------|--------|---------|
| External via research file | `[Source: Original, URL — via file.md]` | `[Source: MarketsandMarkets, https://..., 2025 — via market.md]` |
| Internal document | `[Source: document_name]` | `[Source: 12_Customer_Base.md, Marlink CRM 2025]` |
| User decision | `[User Decision: description]` | `[User Decision: capture rate 5%]` |
| Calculation | `[Calculated: formula, Section X.X]` | `[Calculated: 150 RGUs × $9,768 ARPU, Section 4.7]` |
| Internal projection | `[Internal Projection: basis]` | `[Internal Projection: 15% YoY based on OFFER-001 trend]` |

**What to check**:
- [ ] Market size figures carry the **original analyst report name + URL**, not just "market.md"
- [ ] RGU base / installed base traces to **named CRM data or industry report** via `12_Customer_Base.md`
- [ ] Cost assumptions trace to **vendor pricing pages, quotes, or benchmarks** via `financial.md`
- [ ] Competitor pricing traces to **vendor website or analyst report** via `competitive.md` or `financial.md`
- [ ] Adoption/penetration rates cite **named survey, report, or user decision**
- [ ] Growth rates cite **analyst forecast with URL** or marked as `[Internal Projection]` with basis
- [ ] Any number citing only a research file WITHOUT the original source → flag as **[INCOMPLETE TRACE]**
- [ ] Any number with NO citation at all → flag as **[UNTRACED]**

**Validation process**:
1. For each number in LEAN_BUSINESS_CASE.md, check: does citation include original source?
2. If citation says `[Source: market.md]` only → open market.md → find the original source → flag as **[INCOMPLETE TRACE]** with the original source found
3. If no citation → flag as **[UNTRACED]**

**Severity**:
- ❌ FAIL: Market size, RGU base, or cost figures without original source
- ⚠️ WARNING: Citation points to research file but missing original source behind it
- ⚠️ WARNING: Growth rates or adoption rates as `[Internal Projection]` without stated basis
- ✅ PASS: All numbers fully traced (original source → research file → BC), calculations cross-referenced

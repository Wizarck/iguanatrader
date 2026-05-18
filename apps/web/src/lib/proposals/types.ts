/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * ``apps/api/src/iguanatrader/api/dtos/proposals.py``. Decimals
 * serialize as strings; timestamps as ISO 8601 strings.
 *
 * Slice ``frontend-gaps-batch`` adds the listing + detail surfaces
 * the audit flagged as backend-only.
 */

export type ProposalOut = {
  id: string;
  tenant_id: string;
  strategy_config_id: string;
  symbol: string;
  side: string;
  quantity: string;
  entry_price_indicative: string;
  stop_price: string;
  target_price: string | null;
  confidence_score: string | null;
  reasoning: Record<string, unknown>;
  research_brief_id: string | null;
  mode: string;
  correlation_id: string;
  created_at: string;
};

export type ProposalListOut = {
  items: ProposalOut[];
  next_cursor: string | null;
  total: number | null;
};

export type ExplainResponse = {
  proposal_id: string;
  narrative: string;
};

export type RiskReviewResponse = {
  proposal_id: string;
  risk_assessment: {
    risk_score: number;
    flags: string[];
    rationale: string;
  };
};

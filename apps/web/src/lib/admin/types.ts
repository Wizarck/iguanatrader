/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * ``apps/api/src/iguanatrader/api/routes/admin_ingest.py``.
 *
 * Slice ``frontend-gaps-batch`` exposes the I7 scheduler history so an
 * operator can see what ran, what errored, and how many facts each
 * job inserted.
 */

export type IngestRunOut = {
  id: string;
  source_id: string;
  symbol: string | null;
  invoked_by: string; // "ingest-scheduler" | "cli" | "api"
  status: string; // "started" | "ok" | "error"
  facts_inserted: number;
  error_detail: string | null;
  started_at: string;
  finished_at: string | null;
};

export type IngestRunListOut = {
  items: IngestRunOut[];
  next_cursor: string | null;
  total: number | null;
};

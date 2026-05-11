/**
 * Mock FastAPI backend for the slice 4 Playwright e2e suite.
 *
 * The real Python backend lands its dependency closure via the
 * `regenerate-lock` workflow (slice 4 task 1.6) which only runs at
 * end-of-slice. The Playwright e2e walks the user-agent through the
 * full SvelteKit redirect-after-login flow today by routing
 * `/api/v1/auth/login` and `/api/v1/auth/me` against this in-process
 * mock instead of the real uvicorn.
 *
 * Behaviour mirrored from `apps/api/src/iguanatrader/api/routes/auth.py`:
 *
 * * `POST /api/v1/auth/login` with `{email, password}`:
 *   - email === MOCK_VALID_EMAIL && password === MOCK_VALID_PASSWORD
 *     → 200, sets `iguana_session=<deterministic-jwt>; HttpOnly; Secure;
 *       SameSite=Strict; Max-Age=604800; Path=/`, body
 *       `{"redirect_to": "/"}`.
 *   - any other combination → 401 with RFC 7807 Problem Detail.
 * * `GET /api/v1/auth/me` requires the `iguana_session` cookie:
 *   - cookie matches → 200 with the canonical user payload.
 *   - cookie missing/bad → 401.
 *
 * The "JWT" is a fixed string — the SvelteKit form action only cares
 * that there IS a `Set-Cookie` header to propagate, not its contents.
 *
 * Port: env `MOCK_API_PORT` (default 9999). Logs to stderr so the
 * Playwright `webServer` `stdout: pipe` capture can attribute output.
 */

import { createServer } from 'node:http';

const PORT = parseInt(process.env.MOCK_API_PORT ?? '9999', 10);
const MOCK_VALID_EMAIL = 'alice@example.com';
const MOCK_VALID_PASSWORD = 'correct horse battery staple';
const MOCK_SESSION_VALUE = 'mock-jwt-deterministic';
const MOCK_USER_PAYLOAD = {
  user_id: '00000000-0000-0000-0000-000000000001',
  tenant_id: '00000000-0000-0000-0000-000000000002',
  email: MOCK_VALID_EMAIL,
  role: 'tenant_user',
  created_at: '2026-01-01T00:00:00Z'
};

function log(...args) {
  // eslint-disable-next-line no-console
  console.error('[mock-fastapi]', ...args);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function send(res, status, body, extraHeaders = {}) {
  const payload = typeof body === 'string' ? body : JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': body && typeof body !== 'string'
      ? 'application/json'
      : 'application/problem+json',
    'Content-Length': Buffer.byteLength(payload),
    ...extraHeaders
  });
  res.end(payload);
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  log(`${req.method} ${url.pathname}`);

  if (req.method === 'POST' && url.pathname === '/api/v1/auth/login') {
    const raw = await readBody(req);
    let body = {};
    try {
      body = JSON.parse(raw);
    } catch {
      return send(res, 400, {
        type: 'urn:iguanatrader:error:validation',
        title: 'Bad JSON',
        status: 400
      });
    }

    if (
      body.email === MOCK_VALID_EMAIL &&
      body.password === MOCK_VALID_PASSWORD
    ) {
      return send(
        res,
        200,
        { redirect_to: '/' },
        {
          'Set-Cookie': `iguana_session=${MOCK_SESSION_VALUE}; HttpOnly; Secure; SameSite=Strict; Max-Age=604800; Path=/`
        }
      );
    }

    return send(res, 401, {
      type: 'urn:iguanatrader:error:auth',
      title: 'Authentication Required',
      status: 401,
      detail: 'Invalid email or password.'
    });
  }

  if (req.method === 'GET' && url.pathname === '/api/v1/auth/me') {
    const cookie = req.headers['cookie'] ?? '';
    const sessionMatch = /iguana_session=([^;]+)/.exec(cookie);
    if (!sessionMatch || sessionMatch[1] !== MOCK_SESSION_VALUE) {
      return send(res, 401, {
        type: 'urn:iguanatrader:error:auth',
        title: 'Authentication Required',
        status: 401
      });
    }
    return send(res, 200, MOCK_USER_PAYLOAD);
  }

  // Slice research-frontend-extras-2 mocks — minimal Brief + Facts.
  const briefMatch = /^\/api\/v1\/research\/briefs\/([A-Za-z0-9._-]+)$/.exec(url.pathname);
  if (req.method === 'GET' && briefMatch) {
    const symbol = briefMatch[1].toUpperCase();
    return send(res, 200, {
      id: '00000000-0000-0000-0000-00000000aaaa',
      symbol_universe_id: '00000000-0000-0000-0000-00000000bbbb',
      watchlist_config_id: '00000000-0000-0000-0000-00000000cccc',
      version: 1,
      methodology: 'three_pillar',
      thesis_text: 'short summary',
      score_overall: '0.75',
      score_components: null,
      citations: [],
      audit_trail: [
        {
          formula: 'pe = price / earnings',
          inputs: [
            { fact_id: '00000000-0000-0000-0000-00000000f001', value: '180.0' },
            { fact_id: '00000000-0000-0000-0000-00000000f002', value: '6.0' }
          ],
          intermediate_steps: ['180.0 / 6.0 = 30.0'],
          final_output: 30.0
        }
      ],
      llm_provider: 'mock',
      llm_model: 'mock-001',
      llm_input_tokens: 0,
      llm_output_tokens: 0,
      llm_cache_hit_tokens: 0,
      partial: false,
      created_at: '2026-05-11T00:00:00Z',
      body_markdown:
        `## ${symbol} thesis\n\nStrong quarter per ` +
        `[fact:00000000-0000-0000-0000-00000000f001] and growing earnings ` +
        `per [fact:00000000-0000-0000-0000-00000000f002].\n\n- bullet one\n- bullet two`,
      pillar_scores: null,
      audit_trail_summary: null,
      next_scheduled_refresh_at: null,
      last_fact_recorded_at: null,
      stale: false,
      resolved_citations: []
    });
  }

  const factsMatch = /^\/api\/v1\/research\/facts\/([A-Za-z0-9._-]+)$/.exec(url.pathname);
  if (req.method === 'GET' && factsMatch) {
    return send(res, 200, [
      {
        id: '00000000-0000-0000-0000-00000000f001',
        source_id: 'EDGAR 10-Q FY26 Q1',
        symbol_universe_id: '00000000-0000-0000-0000-00000000bbbb',
        fact_kind: 'price',
        value_numeric: '180.0',
        value_text: null,
        value_jsonb: null,
        unit: 'USD',
        currency: 'USD',
        effective_from: '2026-05-01T00:00:00Z',
        effective_to: null,
        recorded_from: '2026-05-01T00:00:00Z',
        recorded_to: null,
        source_url: 'https://example.test/edgar/q1',
        retrieval_method: 'api',
        retrieved_at: '2026-05-01T00:00:00Z',
        confidence: null,
        created_at: '2026-05-01T00:00:00Z'
      },
      {
        id: '00000000-0000-0000-0000-00000000f002',
        source_id: 'EDGAR 10-Q FY26 Q1',
        symbol_universe_id: '00000000-0000-0000-0000-00000000bbbb',
        fact_kind: 'earnings',
        value_numeric: '6.0',
        value_text: null,
        value_jsonb: null,
        unit: 'USD',
        currency: 'USD',
        effective_from: '2026-05-01T00:00:00Z',
        effective_to: null,
        recorded_from: '2026-05-01T00:00:00Z',
        recorded_to: null,
        source_url: 'https://example.test/edgar/q1',
        retrieval_method: 'api',
        retrieved_at: '2026-05-01T00:00:00Z',
        confidence: null,
        created_at: '2026-05-01T00:00:00Z'
      }
    ]);
  }

  send(res, 404, {
    type: 'urn:iguanatrader:error:not-found',
    title: 'Not Found',
    status: 404,
    detail: `Mock has no route for ${req.method} ${url.pathname}`
  });
});

server.listen(PORT, () => {
  log(`Listening on http://127.0.0.1:${PORT}`);
});

const shutdown = (signal) => {
  log(`Received ${signal}, shutting down`);
  server.close(() => process.exit(0));
};
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

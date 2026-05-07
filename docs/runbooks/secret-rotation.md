# Runbook — Secret Rotation

Operator procedure for rotating production secrets (Anthropic API key,
IBKR credentials, future 2Captcha key) via the SOPS-encrypted manifest
that `sops-secrets-operator` decrypts at deploy time.

This runbook applies to slice **deployment-foundation** (Wave 4) and
later. Pre-Wave-4 deploys do not yet handle these secrets.

---

## 1. Surface

| Secret | Env var | Consumed by |
|---|---|---|
| `ANTHROPIC_API_KEY` | identical | `AnthropicLLMClient` (R5) |
| `IBKR_USERNAME` | identical | `IbAsyncIBClient` (T2) |
| `IBKR_PASSWORD` | identical | `IbAsyncIBClient` (T2) |
| `LITESTREAM_AWS_ACCESS_KEY_ID` | identical | litestream sidecar |
| `LITESTREAM_AWS_SECRET_ACCESS_KEY` | identical | litestream sidecar |
| `TWOCAPTCHA_API_KEY` *(future)* | identical | Tier-4 scrape (deferred slice) |

The `TWS_PORT`, `IBKR_HOST`, and `IB_CLIENT_ID` env vars are NOT
secrets — they live in the `configmap-env.yaml` ConfigMap and are
edited via a normal PR.

The encrypted manifest lives at `deploy/secrets/<env>.enc.yaml` (one
per env: dev / paper / live). The decryption key is an `age` keypair;
the public key is committed to the repo, the private key lives only
in the operator's password manager and on the cluster's
`sops-secrets-operator` namespace.

---

## 2. Pre-rotation checklist

- [ ] Operator has `sops` ≥ 3.8 installed locally.
- [ ] Operator has `age` private key (`~/.config/sops/age/keys.txt`).
- [ ] Operator has push access to the repo.
- [ ] Operator has confirmed which env(s) are affected (dev / paper / live).
- [ ] Operator has notified the team in `#iguanatrader-ops` BEFORE
      issuing the new key (rotation triggers a rolling pod restart).

---

## 3. Rotation procedure (per secret)

### 3.1 Issue the new credential

| Secret | How |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic console → API keys → Create. Pin to `iguanatrader-prod-<YYYY-MM-DD>`. Save the `sk-ant-…` string. |
| `IBKR_USERNAME` / `IBKR_PASSWORD` | IBKR Account Management → Settings → User. Generate a new password; update the username only if the old account is being decommissioned. |
| `LITESTREAM_AWS_*` | AWS IAM → Users → `litestream-iguanatrader-<env>` → Security credentials → Create access key. Save the access-key-id + secret. |
| `TWOCAPTCHA_API_KEY` | 2Captcha dashboard → API keys → Refresh. |

### 3.2 Decrypt the existing manifest

```bash
sops --decrypt deploy/secrets/<env>.enc.yaml > /tmp/iguanatrader-secrets.yaml
```

The output is the plaintext Kubernetes Secret manifest. **Do NOT commit
this file. Keep `/tmp/` free of these files via `shred` after editing.**

### 3.3 Edit the manifest

```bash
"$EDITOR" /tmp/iguanatrader-secrets.yaml
```

Update ONLY the field being rotated. Leave all other fields unchanged.
Each `data` value is base64-encoded (Kubernetes Secret semantics):

```yaml
data:
  ANTHROPIC_API_KEY: "<base64 of new sk-ant-… string>"
```

To produce base64:

```bash
echo -n "sk-ant-new-key-here" | base64 -w0
```

### 3.4 Re-encrypt

```bash
sops --encrypt /tmp/iguanatrader-secrets.yaml > deploy/secrets/<env>.enc.yaml
shred -uz /tmp/iguanatrader-secrets.yaml
```

Verify that `git diff deploy/secrets/<env>.enc.yaml` shows ONLY the
changed encrypted byte block — no other fields should differ. If you
see drift in the `sops_metadata` block beyond the modified field's
mac, abort and reach out (it indicates stale `.sops.yaml` config).

### 3.5 Commit + push

```bash
git checkout -b chore/rotate-anthropic-key-<YYYY-MM-DD>
git add deploy/secrets/<env>.enc.yaml
git commit -m "chore(secrets): rotate ANTHROPIC_API_KEY (<env>)"
git push -u origin chore/rotate-anthropic-key-<YYYY-MM-DD>
gh pr create --title "Rotate ANTHROPIC_API_KEY (<env>)" --body "Manual rotation; operator: $(whoami)"
```

The PR triggers normal CI (license-boundary + helm lint). When merged,
the Fleet GitRepo CR detects the change and triggers a sync; the
`sops-secrets-operator` decrypts the new manifest and updates the live
`Secret`. The api StatefulSet detects the env-var change (via
`reloader.stakater.com/auto: "true"` annotation, applied per ADR-027)
and rolls the pod.

---

## 4. Post-rotation verification

```bash
# 1. Confirm the Fleet sync succeeded:
kubectl get gitrepo iguanatrader -n fleet-default

# 2. Confirm the Secret was decrypted + applied:
kubectl get secret iguanatrader-secrets -n iguanatrader -o jsonpath='{.data.ANTHROPIC_API_KEY}' | base64 -d | head -c 8

# 3. Confirm the api pod was rolled and the new key is live:
kubectl get pods -n iguanatrader -l component=api
kubectl logs -n iguanatrader -l component=api --tail=50 | grep -i "synthesizer.startup"

# 4. Smoke-test a synthesis call:
kubectl exec -n iguanatrader sts/iguanatrader-api -c api -- \
  python -c "import asyncio; \
             from iguanatrader.contexts.research.synthesis.anthropic_client import build_anthropic_llm_client_from_env; \
             c = build_anthropic_llm_client_from_env(); \
             r = asyncio.run(c.complete('hello', model='claude-3-5-haiku', replay_key=None, max_tokens=16)); \
             print(r.text[:80])"
```

If step 4 returns Claude's response → rotation successful.
If step 4 returns `MissingSecretError` → the new Secret didn't propagate;
reach out to runbook `cascade-failure-template.md` step 2.

---

## 5. Rollback

The previous SOPS-encrypted manifest stays in git history. To revert:

```bash
git checkout main
git pull origin main
git revert <rotation-commit-sha>
git push origin main
```

The revert PR follows the normal CI + Fleet sync path — within ~3 min
the old key is reapplied. Do NOT manually `kubectl apply` an older
manifest version (Fleet will overwrite it on next sync, causing a
pod-flap loop).

---

## 6. Common failures + recovery

| Symptom | Likely cause | Recovery |
|---|---|---|
| `sops` decrypt error: "no key could decrypt the data" | Operator's age key isn't the one the file was encrypted with | Verify `cat ~/.config/sops/age/keys.txt` matches the public key recorded in `.sops.yaml` for this env |
| `sops` re-encrypt error: "config file not found" | Working dir is wrong (need to be at repo root) | `cd $(git rev-parse --show-toplevel)` then retry |
| Fleet sync stuck "ErrApplied" | The new manifest fails K8s validation (e.g. missing required field) | `kubectl describe gitrepo iguanatrader -n fleet-default` for the apply error; fix in a follow-up PR |
| Pod won't start: `MissingSecretError` after sync | sops-secrets-operator hasn't rotated yet OR an env var is missing from the new manifest | `kubectl describe secret iguanatrader-secrets -n iguanatrader`; verify each field name from `helm/iguanatrader-stack/values.yaml` `secret.fields` is present |

---

**References**

- Encrypted manifest format: [SOPS docs](https://github.com/getsops/sops)
- sops-secrets-operator: [doc](https://github.com/getsops/secrets-operator)
- Per-env Helm values: `helm/iguanatrader-stack/values.yaml`
- ADR-013 (AGPL openbb-sidecar boundary)
- ADR-015 (eligia-core/helm pattern this chart mirrors)

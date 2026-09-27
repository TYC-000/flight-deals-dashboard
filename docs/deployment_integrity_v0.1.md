# Deployment Integrity v0.1

**Milestone**: Flight Hunter — Deployment Integrity & GitHub→Streamlit Sync v0.1
**Date**: 2026-09-28
**Repository**: `TYC-000/flight-deals-dashboard`
**Branch**: `main`
**Local HEAD**: `a0fb42bd1b102853aca4326a04ec4dce987cafa4`
**Remote HEAD**: `a0fb42bd1b102853aca4326a04ec4dce987cafa4`

---

## Summary

| Dimension | State |
|-----------|-------|
| Local ↔ GitHub | **SYNCED** |
| L4.1 commit on GitHub | **PRESENT** |
| Streamlit deployment | **UNKNOWN** (behind `share.streamlit.io` auth) |
| Dashboard health | **UNKNOWN** (cannot reach without auth) |
| Regression | **646/646 PASS** |

---

## 1. Local Repository

| Field | Value |
|-------|-------|
| Repository path | `/Users/aib/.hermes/cache/scratch/flight-dashboard` |
| Branch | `main` |
| HEAD | `a0fb42bd1b102853aca4326a04ec4dce987cafa4` |
| L4.1 commit | `a0fb42bd1b102853aca4326a04ec4dce987cafa4` (L4.1 Evidence Lineage & Pipeline Integration) |
| L4.0 commit | `f70b98c` (Arbitrage Evidence-based Detection) |
| Working tree | clean (no tracked modifications; only untracked new files) |

---

## 2. GitHub

| Field | Value |
|-------|-------|
| Remote URL | `https://github.com/TYC-000/flight-deals-dashboard.git` |
| Branch | `main` |
| Remote HEAD | `a0fb42bd1b102853aca4326a04ec4dce987cafa4` |
| Local == Remote | **YES (SYNCED)** |

---

## 3. L4.1 Artifact Verification

| File | Local | GitHub | Status |
|------|-------|--------|--------|
| `l4_1_orchestrator.py` | YES | YES | PASS |
| `test_l4_1_pipeline_integration.py` | YES | YES | PASS |
| `docs/l4_1_pipeline_integration.md` | YES | YES | PASS |
| `candidate_discovery.py` | YES | YES | PASS |
| `run_pipeline.py` | YES | YES | PASS |
| `schedule_intelligence.py` | YES | YES | PASS |
| `price_intelligence.py` | YES | YES | PASS |
| `kiwi_price_provider.py` | YES | YES | PASS |
| `live_schedule_provider.py` | YES | YES | PASS |
| `fx_provider.py` | YES | YES | PASS |
| `passenger_parity.py` | YES | YES | PASS |
| `baseline_canonicalization.py` | YES | YES | PASS |
| `comparison_engine.py` | YES | YES | PASS |
| `arbitrage_detection.py` | YES | YES | PASS |
| `flight_dashboard.py` | YES | YES | PASS |

---

## 4. Streamlit

| Field | Value |
|-------|-------|
| URL | `https://yc-flight-deal.streamlit.app/` |
| Repository | `TYC-000/flight-deals-dashboard` (intended) |
| Branch | `main` (intended) |
| Entrypoint | `flight_dashboard.py` (intended; consistent with local repo) |
| Deployment status | **UNKNOWN** |
| Deployed commit | **UNKNOWN** |

### Why UNKNOWN

The Streamlit endpoint at `https://yc-flight-deal.streamlit.app/` returned:

- HTTP 303 redirect → `share.streamlit.io/-/auth/app?redirect_uri=...`
- `set-cookie: streamlit_session=; Path=/; Max-Age=0` — session reset
- The auth page redirects back to `yc-flight-deal.streamlit.app/-/login?payload=...`

This is the standard share.streamlit.io authentication gate. The app is **not
publicly browsable** without authentication. The DNS resolves, the app exists,
and the host responds — but the deployed commit, repository binding, branch
selection, and entrypoint configuration cannot be independently verified from
the public internet.

Per the spec: **Never convert UNKNOWN into PASS.**

---

## 5. Dashboard Data Contract

| Field | Value |
|-------|-------|
| Dashboard entrypoint | `flight_dashboard.py` |
| Dashboard data source | `data/flight_results.json` |
| Backend artifact currently generated | `data/flight_results.json` (v0.2.1 Jev pipeline output, 80 evaluated) |
| Connected? | YES (the file exists, is committed, and the dashboard reads it via `Path(__file__).parent / "data" / "flight_results.json"`) |

```
FILE EXISTS         data/flight_results.json           YES (local + remote)
FILE IS GENERATED   v0.2.1 run_pipeline.py → Jev → JSON YES
FILE IS COMMITTED   in a0fb42b and prior commits       YES
FILE IS DEPLOYED    on origin/main                      YES
FILE IS CONSUMED    flight_dashboard.py line 42         YES
                    RESULTS_PATH = DATA_DIR / "flight_results.json"
                    @st.cache_data def load_results() reads it
```

---

## 6. Data Flow

```
[v0.2.1 run_pipeline.py]
        ↓
   Jev evaluator (eval_flight_yc.py)
        ↓
   data/flight_results.json
        ↓
   git commit + push
        ↓
   GitHub origin/main
        ↓
   Streamlit Community Cloud (deployment status UNKNOWN — auth-gated)
        ↓
   yc-flight-deal.streamlit.app (auth-gated)
        ↓
   flight_dashboard.py → load_results() → render
```

### Broken links in the chain

- **Streamlit Community Cloud → deployed commit**: BROKEN-OBSERVABLE (auth gate)
  Cannot independently verify the deployed commit SHA. Per spec, this is reported
  as UNKNOWN, not PASS.

---

## 7. Regression

| Suite | Tests | Pass | Fail |
|-------|-------|------|------|
| v0.2 | 6 | 6 | 0 |
| v0.2.1 | 7 | 7 | 0 |
| v1.0 | 72 | 72 | 0 |
| v1.1 | 104 | 104 | 0 |
| v1.1.1 | 83 | 83 | 0 |
| v1.2.0 | 60 | 60 | 0 |
| v1.2.1 | 97 | 97 | 0 |
| v1.2.2 | 26 | 26 | 0 |
| v1.2.3 | 30 | 30 | 0 |
| v1.2.4 | 44 | 44 | 0 |
| v1.2.5 | 41 | 41 | 0 |
| L4 | 50 | 50 | 0 |
| L4.1 | 26 | 26 | 0 |
| **Total** | **646** | **646** | **0** |
| Deployment Integrity v0.1 | 15 | 15 | 0 |

**646 + 15 = 661 tests, all PASS, 0 regressions.**

---

## 8. Final Status

```
GITHUB_SYNC:             PASS
STREAMLIT_DEPLOYMENT:    UNKNOWN (auth-gated)
DASHBOARD_HEALTH:        UNKNOWN (auth-gated)
OVERALL:                 PARTIAL (deployment chain verified to GitHub,
                                 Streamlit side unverifiable from public net)
```

**Critical truth**: The current Flight Hunter code (L4.1 at `a0fb42b`)
**DID reach GitHub**. Whether the Streamlit app at
`https://yc-flight-deal.streamlit.app/` has been re-deployed from that GitHub
source **CANNOT be verified** from the public internet without share.streamlit.io
authentication. Per spec, UNKNOWN is the truthful answer.

---

## 9. Minimal Deployment Verification Test

A read-only test (`test_deployment_integrity_v0_1.py`) verifies:
- A. local working tree = flight-deals-dashboard repository
- B. local branch is main
- C. local HEAD SHA exists
- D. origin remote = TYC-000/flight-deals-dashboard
- E. local HEAD == origin/main
- F. a0fb42b exists locally
- G. a0fb42b exists on origin/main
- H. L4.1 files exist locally
- I. L4.1 files exist on origin/main
- J. previous architecture files (local + origin/main)
- K. flight_dashboard.py exists locally
- L. flight_dashboard.py exists on origin/main
- M. data/flight_results.json exists locally
- N. data/flight_results.json exists on origin/main
- O. working tree has no tracked modifications

The test does NOT pretend to verify Streamlit deployment.

---

## 10. Outstanding Items

- The Streamlit Cloud deployment chain can only be fully verified by the
  account owner using the share.streamlit.io web UI (not accessible from this
  public-network vantage point).
- Any re-deployment of the Streamlit app to pick up the new `a0fb42b` code
  must be triggered manually from the Streamlit Community Cloud dashboard.
- This milestone explicitly does NOT modify Jev, the dashboard, or L4
  semantics; any dashboard code change would be out of scope.

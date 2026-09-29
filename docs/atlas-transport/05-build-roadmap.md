# 05 — Build roadmap (PoC → limited rollout)

> Two tracks that proceed in parallel: **Track A** (the Atlas transport) and **Track B** (the
> independent panel). Each phase names the **adversarial test it must pass before we trust it** — the
> repo's existing discipline ("the test is the argument, not the intuition") applied to circumvention.
> No calendar dates; ordering + relative effort only.

## Guiding principles

1. **Measure before trust.** Every stealth claim is validated against a local re-implementation of the
   known detectors *before* it carries a customer. Build the **Detector Lab** (below) first.
2. **We already have an in-country oracle.** Owner's Android over real MCI, driven by adb (see memory
   [[phone-testing-via-adb]]): latency button, real client from shell, UUID cleanup. This is how we get
   ground truth that no VPS test can give — MCI's post-handshake kills, per-operator waves, PMTU
   blackholes. Extend it to Irancell/Rightel SIMs if possible.
3. **Small, disposable, diverse beats one monolith** (the NaiveProxy thesis). Prefer many cheap rotating
   endpoints over one clever server.
4. **Coexist, don't cut over.** Xray/REALITY keeps serving the whole customer base until Atlas earns its
   place on measured results.

## Phase 0 — De-risk the open decisions (before writing transport code)

Resolve the choices that would be expensive to reverse:

- **Client strategy** (biggest one): sing-box-compatible outbound vs. thin custom Go client + gomobile.
  Spike both far enough to know which is viable; a brand-new protocol with no client ships nothing.
- **QUIC library** (quic-go vs alternatives) and **Noise library** (a reviewed Go implementation).
- **Detector Lab scope** (below).
- **Backing-origin strategy** for the fallback: which real, reputationally-consistent sites/`dest`s
  (ideally domestic-CDN-hosted) each carrier fronts, and how we host them consistently (reverse-DNS/WHOIS).

**Gate:** a one-page decision record for each, committed here. No transport code until these are picked.

## The Detector Lab (build once, use every phase)

A local test harness that runs our candidate transport against the published attacks:
- **Entropy heuristic (Ex1–Ex5)** — implement the popcount/printable checks on first packets; assert our
  first packet is exempted for every carrier.
- **Probe-resistance timing** — a prober that sends garbage / replays / wrong byte counts and diffs our
  server's timing + close behavior against the real backing origin (the NDSS '20 tell). Assert
  indistinguishable.
- **TLS-in-TLS classifier** — re-implement the USENIX '24 encapsulated-handshake features (record sizes,
  bursts, cross-layer RTT) and score our flattened streams; track the detection rate as a regression
  number.
- **uTLS fingerprint check** — confirm our ClientHello matches a current popular browser and sits in a
  large anonymity set (no unique quirks).

This lab is the equivalent of `tests/test_*.py` for the transport, and the same rule applies: a stealth
change that isn't measured here didn't happen.

---

## Track A — the Atlas transport

### A1 — Secure-channel core PoC
Noise_IK (Curve25519 / ChaCha20-Poly1305 / BLAKE2s) + AEAD records + **replay window** + resumption
tickets. Client ↔ server on one of our nodes; proxy a real TCP stream end to end.
- **Gate:** interop + a replay/nonce-reuse test (assert replays rejected); rekey works; no clock coupling.

### A2 — Direct carrier (borrowed TLS) + probe-resistant fallback
Implement the REALITY-pattern carrier (uTLS ClientHello → authenticator → temp-cert splice; unauthorized
→ transparent forward to the real `dest`) and the §6 fallback state machine.
- **Gate (Detector Lab):** a prober gets the real `dest`'s genuine cert/content; reject-path timing
  matches the real origin. Then: it connects over real MCI via the adb oracle.

### A3 — Framing: polymorphic records + first-packet shaping + inner-handshake flattening
The §4 layer. This is the research-grade phase.
- **Gate (Detector Lab):** first packet exempted by Ex1–Ex5; TLS-in-TLS detection rate on flattened
  streams driven down and tracked as a regression metric; overhead measured and bounded.

### A4 — Fronted carrier (CDN) + clean-IP scanner + agility
WS/XHTTP behind Cloudflare/ArvanCloud with the **Noise** channel inside (no inner TLS handshake); the
built-in clean-IP scanner (real-handshake edge probing); per-operator carrier pinning table.
- **Gate:** survives simulated throttling/loss (netem) staying usable ("slow but connected"); scanner
  finds and self-heals onto a working edge; adb oracle confirms on MCI under real throttling.

### A5 — Masquerade carrier (H3/HTTPS) + dual-stack failover
Genuine H3 to a real origin, with a TCP/HTTPS twin and automatic failover when UDP/QUIC is dropped.
- **Gate:** under a simulated protocol allow-list (only 80/443 TCP + DNS), the masquerade path passes and
  the UDP twin fails over cleanly; adb oracle under the tightest real MCI conditions.

### A6 — Rendezvous + SURVIVAL mode
Signed fresh-config delivery via the **existing Telegram bot** + fronted mirrors + DoH TXT; the bearer
hook interface (satellite/mesh) — readiness, not a magic carrier ([03](03-atlas-protocol-spec.md) §9).
- **Gate:** with all primary endpoints blocked, the client bootstraps a fresh working endpoint from
  rendezvous alone; signed-blob trust verified (reject unsigned/tampered).

---

## Track B — the independent panel

### B1 — Adapter seam
Wrap the current `XUIClient` as the **Xray-over-3x-ui adapter** behind the `EngineAdapter` interface
([04](04-panel-architecture.md) §5). Control plane now speaks "adapter," behavior identical.
- **Gate:** existing panel operations (provision, disable, usage, online counts) pass unchanged against a
  test 3x-ui; the bulk-snapshot / no-per-client-loop rules ([PROJECT_MAP](../../PROJECT_MAP.md) §6) hold.

### B2 — Node agent
A small gRPC + mTLS agent on the SSH-reachable nodes, first fronting the same Xray adapter. We now own the
control channel instead of HTTP-logging-in to each 3x-ui.
- **Gate:** a leased/compromised node can't pull the user table or impersonate another (mTLS + capability
  scoping); usage streams match the old HTTP-polled numbers to the byte.

### B3 — Data-model generalization
Introduce `Engine`/`capabilities`/`engine_kind`; keep reseller grandfathering, custom pricing, per-profile
`ip_limit` intact.
- **Gate:** reseller billing + IP-guard tests pass verbatim on the generalized schema.

### B4 — Atlas adapter + subscription descriptor + accounting
Add the Atlas adapter (per-user **hot** changes), the signed Atlas subscription descriptor, and wire Atlas
`UsageDelta` into the same accounting/quota path.
- **Gate:** an Atlas user provisions, connects, meters, expires, and renews through the *same* pricing and
  quota code as an Xray user; adding/removing one Atlas user drops **zero** other connections.

---

## Convergence — limited rollout

1. **Adversarial external review** of the Atlas design + Detector Lab results (net4people/bbs, academic
   contacts) before any customer traffic.
2. **Pilot cohort** on Atlas beside Xray, per-operator, measured via the adb oracle and volunteer testers
   on MCI/Irancell/Rightel across regions.
3. **Rotation discipline** live (48h–2-week IP horizon, modest per-IP volume, proactive retirement).
4. Expand only where measured; retire 3x-ui per node as Atlas proves out.

## Rough effort & sequencing

- **Track B is the lower-risk, higher-certainty win** and unlocks the transport seam — start B1–B2
  immediately; they're valuable even if Atlas slips (independence from 3x-ui + hot user updates + better
  node security).
- **Track A is research-grade at A3 (flattening) and A5–A6.** Expect iteration and dead ends there; that's
  normal for this problem, not a failure.
- The **Detector Lab and the adb oracle are prerequisites**, not afterthoughts — they gate everything.

## What NOT to do (carried from the research)

- Don't invent crypto or a distinctive wire signature "to be clever" — it *reduces* stealth
  ([README](README.md) thesis).
- Don't rely on domain fronting on the majors, or on "random-looking" bytes, as a foundation.
- Don't ship a UDP-only transport (fragile under allow-listing) — always keep a TCP/TLS twin.
- Don't promise the customer that anything survives a **total** blackout from the data plane — be honest
  that gear 4 is a bearer/rendezvous story.
- Don't let one config be assumed nationally valid — per-operator/region pinning is mandatory.
- Don't trust any "undetectable" result that the Detector Lab and an external reviewer haven't seen.

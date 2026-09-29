# 03 — Atlas Transport: protocol & transport-framework spec

> **Status: design draft for review.** No wire format here is final until it survives the adversarial
> tests in [05-build-roadmap.md](05-build-roadmap.md). Internal codename **"Nardebān"** (نردبان — a
> ladder over the wall); **the on-wire traffic carries no such name, magic bytes, or version tag** —
> by design there is nothing to fingerprint (see [README](README.md) thesis).

## 1. What Atlas is (and is not)

Atlas is **not "a new protocol"** in the sense of a new wire signature. It is a **transport
framework**: a small, reused secure-channel core, wrapped by interchangeable **carriers** that each
make the channel *be* a common, high-anonymity-set traffic type on the wire, plus the **agility,
rotation, shaping and rendezvous** machinery that the research says actually determines survival.

- **Novel (our work):** carrier agility + per-operator auto-selection, built-in clean-IP scanner,
  polymorphic framing + first-packet shaping, adaptive TLS-in-TLS flattening, the four gear-matched
  modes, and the rendezvous layer.
- **Reused (never rolled ourselves):** Noise_IK handshake, ChaCha20-Poly1305 / AES-256-GCM AEAD with a
  mandatory replay window, uTLS, a mature QUIC library, Elligator2, real TLS 1.3.

Non-goals: inventing crypto; beating a total blackout from the data plane alone (that is a rendezvous
+ bearer problem, §7 mode 4, §9); being the *fastest* transport (we optimize for *staying connected*).

## 2. Layered architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ L5  Control / agility                                                  │
│     carrier selection · clean-IP scanner · per-operator pinning ·      │
│     rotation · rendezvous (fresh endpoints/keys under blockade)         │
├─────────────────────────────────────────────────────────────────────┤
│ L4  Framing (polymorphic)                                              │
│     variable records · first-packet shaping (Ex1–Ex5) · adaptive       │
│     inner-handshake flattening (Vision-equivalent) · padding/timing     │
├─────────────────────────────────────────────────────────────────────┤
│ L3  Secure channel core  (identical across carriers)                   │
│     Noise_IK handshake · AEAD records · replay window · resumption      │
├─────────────────────────────────────────────────────────────────────┤
│ L2  Carrier  (how it looks on the wire — pick per network)             │
│   ┌───────────┬───────────────┬──────────────┬───────────────────┐    │
│   │ Direct    │ Fronted        │ Masquerade   │ Bearer (blackout) │    │
│   │ borrowed  │ WS/XHTTP behind│ genuine H3/  │ satellite / mesh  │    │
│   │ TLS 1.3   │ CDN (CF/Arvan) │ HTTPS origin │ / refraction hook │    │
│   └───────────┴───────────────┴──────────────┴───────────────────┘    │
├─────────────────────────────────────────────────────────────────────┤
│ L1  Bearer network: TCP · QUIC/UDP · out-of-band                       │
└─────────────────────────────────────────────────────────────────────┘
```

Two channel constructions, chosen by carrier, both avoiding a self-inflicted TLS-in-TLS:

- **TLS-native carriers (Direct, Masquerade):** the secure channel *is* real TLS 1.3. Our handshake is
  a genuine browser handshake (uTLS / REALITY-style borrowing), so *our* first packet passes the
  entropy heuristic trivially (it matches Ex5) and JA3/JA4 sits in a huge anonymity set.
- **CDN-fronted carrier:** Cloudflare/ArvanCloud already terminates TLS. Inside it we run the **Noise**
  channel, **not a second TLS handshake** — running another full TLS inside the CDN's TLS would *itself*
  create the TLS-in-TLS signature we are trying to avoid. Noise's handshake is short, non-TLS-shaped,
  and paddable.

In every case the **user's own** TLS handshakes to their destinations still ride inside our tunnel;
that residual TLS-in-TLS is handled per-stream by the flattening layer (§4.3).

## 3. Secure channel core (L3) — all reused primitives

### 3.1 Handshake: Noise_IK (as WireGuard)
The client knows the server's long-term static public key in advance (delivered in the subscription /
rendezvous blob). **Noise_IK** fits exactly:

- `I` — initiator (client) static key is transmitted, encrypted, to the responder ⇒ **mutual auth**.
- `K` — responder (server) static key is **known to the initiator beforehand** ⇒ **1-RTT**, and the
  responder's identity is never exposed to a prober.

```
Noise_IK, Curve25519, ChaCha20-Poly1305, BLAKE2s
  -> e, es, s, ss        (client → server: ephemeral, static-encrypted, 0-RTT-capable payload)
  <- e, ee, se           (server → client)
  [transport messages: AEAD records both directions]
```

Rationale (from [02](02-circumvention-sota.md) §5): Noise is rigorously analyzed and misuse-resistant;
Noise_IK is the WireGuard construction, so we inherit a widely-reviewed design instead of authoring a
handshake. **No clock-coupled auth field** (VMess's mistake); freshness comes from the ephemeral +
replay window, not wall-clock.

### 3.2 Records: AEAD with a mandatory replay window (from day one)
- AEAD = **ChaCha20-Poly1305** (default; fast in software on the ARM mobile CPUs most clients run) or
  **AES-256-GCM** (when both ends have AES-NI). Negotiated in the handshake payload, not on the wire in
  cleartext.
- Per-message **64-bit counter nonce**; receiver keeps a **sliding replay window** (SIP022 / WireGuard
  style). This is the specific hole that sank Shadowsocks-2017 — it is non-optional here.
- **Rekey** by message count / bytes / time to bound key usage (WireGuard's approach).

### 3.3 Key material on the wire looks random: Elligator2
Any raw Curve25519 public key that appears *before* an enclosing TLS/CDN layer (i.e. only the bare/UDP
carriers) is **Elligator2-encoded** so it is uniform-random and can't be flagged as a curve point
(obfs4's technique). For TLS-native and CDN-fronted carriers the keys are already inside TLS, so this
only matters for §5.4.

### 3.4 Resumption
A **session ticket** (server-sealed, opaque, replay-protected) lets a rotated/roamed client resume
without a fresh full handshake — important for mobile IP churn and for keeping handshakes (the most
fingerprintable moment) rare.

## 4. Framing (L4) — where real novelty lives

### 4.1 Polymorphic records
- **No fixed magic, no constant offsets, no fixed-length handshake.** Record lengths drawn from a
  distribution that matches the carrier's cover traffic (TLS record sizes for TLS carriers; H2/H3 frame
  sizes for H-carriers).
- Length obfuscation: each record carries an AEAD-encrypted length prefix; optional padding records are
  legal and indistinguishable from data.

### 4.2 First-packet shaping (defeat the entropy heuristic Ex1–Ex5)
For **TLS-native / CDN-fronted** carriers this is free: the first packet is a real TLS ClientHello or a
real HTTP/WS request — it matches **Ex5** (known-protocol fingerprint). For the **bare/UDP carrier**
(§5.4) the first packet is explicitly shaped to satisfy an exemption (printable-ASCII prefix, or a
protocol-looking header) so it is never flagged as fully-random. This is a hard requirement checked by
a test in [05](05-build-roadmap.md).

### 4.3 Adaptive inner-handshake flattening (our Vision-equivalent) — the sharp edge
The residual TLS-in-TLS risk is the **user's** TLS handshakes to their destinations, visible as a
record-size/timing shape inside our tunnel (USENIX '24). Mitigation, applied per proxied stream:

1. **Detect** the inner TLS 1.3 handshake in the first records of a new stream.
2. **Pad + re-segment** those records so the encapsulated-handshake burst sizes and round-trip counts
   no longer match the classifier's features (the paper is explicit that padding *alone* is limited —
   so we also…).
3. **Splice**: after the inner handshake completes, stop adding our own record layer around the inner
   TLS records where possible (avoid double-framing), the way XTLS-Vision does.
4. **Budget-cap** the shaping to the first *N* records (the classifier keys on flow start), to bound
   overhead.

This is a research-grade problem and an explicit **arms-race** item: the flattening policy must be
data-driven and measured against a local re-implementation of the USENIX '24 detector before we trust
it (test in [05](05-build-roadmap.md)).

### 4.4 Padding & timing
Length padding is on by default (targets length + TLS-in-TLS classifiers). Timing shaping is *opt-in
and modest* — the Parrot lesson is that timing mimicry is expensive and imperfect shaping creates its
own anomalies. We shape toward the carrier's natural distribution, we do not try to perfectly imitate.

## 5. Carriers (L2) — one per censor gear

### 5.1 Direct carrier (borrowed TLS 1.3) — gear 1 (normal filtering)
The REALITY pattern, re-implemented as ours:
- Client sends a genuine uTLS ClientHello to a configured **reputationally-consistent, low-profile,
  ideally domestic `dest`/SNI** (e.g. a real domain hosted on an Iranian CDN, not `www.google.com`).
- Server holds an X25519 static key; the client's authenticator is carried in the ClientHello (SessionID
  or a suitable extension). Authorized ⇒ server splices its own temp cert inside the encrypted channel;
  unauthorized/probe ⇒ **transparently forwarded to the real `dest`**, which returns its genuine cert
  and content (§6 fallback).
- Weak point (from [01](01-iran-threat-model.md)): **IP reputation, not protocol shape.** ⇒ rotation
  (§8) and modest per-IP volume are mandatory, not optional.

### 5.2 Fronted carrier (WS / XHTTP behind a CDN) — gears 2–4 (throttling, whitelist, stealth-blackout)
- Runs over **WebSocket or XHTTP** behind **a domestic CDN (ArvanCloud, Derak…) or Cloudflare**. The CDN
  provides the outer TLS; inside we run the **Noise** channel (§2, avoids self-inflicted TLS-in-TLS).
- **This is the wartime survival core, not a footnote** — validated by the June 2025 stealth blackout
  ([01](01-iran-threat-model.md)). During a whitelist/throttle regime, a **domestic CDN whose edges are
  inside Iran and whose international backhaul is exempt** (ArvanCloud AS205585 was measured ~99.7% up)
  is the one path that stays reachable: WS rides the surviving TCP/443, the dialed hop is domestic, and
  REALITY/direct-to-foreign are dead. It also survives ordinary throttling (the censor can only shape
  *subsets* of a big CDN). Pairs with the clean-IP scanner (§8.2), no-DNS bootstrap (§8.5) and adaptive FEC (§7).
- **The CDN edge is adversary-observable and state-aligned** (ArvanCloud hosts state infra and terminates
  the outer TLS). This is *why* the **Noise channel runs inside** (§2): the edge sees only an opaque
  WebSocket carrying ciphertext, never the user's traffic. **Never let confidentiality depend on the CDN's TLS.**
- **Dial a raw, pinned domestic edge IP with `address` separated from `SNI`/`Host`** (§8.2, §8.5) — never
  depend on DNS. Generalizes what AtlasBot already does (`connect_host`, CF-fronted ws inbounds), extended
  to domestic CDNs + edge rotation.

### 5.3 Masquerade carrier (genuine H3/HTTPS origin) — gear 3 (protocol allow-list)
- Under a strict allow-list only DNS/HTTP/HTTPS pass. This carrier makes Atlas **be** an HTTP/3 (or
  HTTP/2) session to a real-looking origin with a real ACME cert — a NaiveProxy/Hysteria2-class
  masquerade — so it *is* permitted traffic. Probes get normal web responses (§6).
- QUIC path uses a mature QUIC lib; **but** because Iran periodically throttles/drops UDP/QUIC, this
  carrier always has a **TCP/HTTPS twin** and the agility layer fails over between them.

### 5.4 Bare obfuscated UDP (AmneziaWG-class) — secondary, gear 2 fallback
- A featureless UDP carrier (junk-padded, timing-randomized, Elligator2 keys) for networks where UDP is
  merely lossy, not blocked. **Must not look like QUIC** (QUIC is blanket-blockable) and **must** shape
  its first packet (§4.2). Secondary because "random-looking" is fragile post-2021.

### 5.5 Bearer hook (hard blackout only) — the rare extreme
Not a wire carrier but an **interface** for out-of-band transport when even domestic-CDN egress is cut
(the ~4-day *hard* window, not the typical wartime weeks): satellite (Starlink) uplink, *audited*
mesh/DTN, or a future refraction station. See §9 — this is being *ready* for the extreme, not the
everyday wartime path (that's §5.2). Not a scalable product; last resort.

### 5.6 Chaining: domestic relay → foreign exit — a first-class survival topology
When only *some* domestic ASNs retain egress, the winning shape is: client → **in-country relay** (always
reachable domestically, low latency) → foreign exit over the relay's surviving egress. Documented working
in June 2025. The panel schedules this as a two-hop `InboundSpec`; the relay runs an Atlas node-agent like
any other node, and composes with §5.2 (front the *relay* through the domestic CDN). The relay only ever
sees the inner Noise ciphertext, same as the CDN edge.

## 6. Probe-resistant fallback — the single most important property

Every surviving design shares it, and NDSS '20 shows the *way you reject* must not itself be a
fingerprint. State machine on the server for any inbound connection:

```
accept TCP/QUIC
  │
  ├─ carrier handshake bytes valid AND client authenticator opens?  ── no ──┐
  │                                                                          │
  yes                                                                        ▼
  │                                                          transparently proxy the WHOLE
  ▼                                                          connection to the real backing
  splice temp cert / establish Noise channel                origin (Direct: the real `dest`;
  → serve proxy                                              Fronted/Masquerade: the real site
                                                             this origin actually hosts)
```

Hard requirements (each a test in [05](05-build-roadmap.md)):
- The backing origin is a **real, plausible site with real content and a valid cert**, hosted
  consistently with the impersonated identity (reverse-DNS/WHOIS/SOA) to survive Iran's suspected
  reputation-based probing.
- **Timing and close/timeout behavior of the reject path must match a real server** — no distinctive
  RST, no anomalous timeout when fed the wrong byte count (the obfs4/SS tell).
- A prober that replays or sends garbage must receive exactly what the real backing origin would.

## 7. The four modes (gear-matched) and the policy that switches them

| Mode | Censor gear | Carrier | CC / FEC | Notes |
|---|---|---|---|---|
| **NORMAL** | 1 filtering | Direct (borrowed TLS) | BBR, no FEC | Best latency; rotate IPs on reputation triggers |
| **THROTTLE** | 2 shaping/loss | Fronted (domestic CDN) + bare-UDP twin | BBR→aggressive; **adaptive FEC** on | Loss-tolerant, "slow but connected"; clean-IP scan active |
| **ALLOWLIST** | 3 protocol allow-list | Masquerade (H3/HTTPS) + TCP twin | BBR | *Be* permitted HTTPS/H3; UDP twin drops if QUIC blocked |
| **SURVIVAL** | 3–4 whitelist / stealth-blackout | **Fronted carrier on a domestic exempt CDN** (§5.2) + no-DNS bootstrap (§8.5) + chaining (§5.6); bearer (§5.5) only as last resort | BBR, **TCP-only (no UDP)** | The wartime workhorse: domestic-CDN fronting survives the whitelist/throttle weeks; bearer only for the rare ~4-day hard cut. See §9 |

**Mode selection is per-network and automatic** (§8). The client probes, scores each carrier against
the *current* operator/region, pins the winner, and demotes/promotes modes as conditions change — never
assuming one config is nationally valid (the MCI≠Irancell≠Rightel, Tehran≠Tabriz reality).

## 8. Agility, rotation, and the built-in clean-IP scanner (L5) — decisive for survival

### 8.1 Per-operator, per-region carrier selection
The client maintains a small table keyed by **detected network** (operator + rough region, inferred
from the assigned IP/ASN and latency signature). For each network it stores which (carrier, endpoint,
SNI, CC/FEC) tuple last worked, A/B-tests candidates in the background, and **pins the winner**. This is
the automation of what Iranian users do by hand today.

### 8.2 Clean-IP scanner (automate "proxy scanning")
Built into the client, because ICMP is blocked and reachability must be tested at the data plane
([01](01-iran-threat-model.md) §6):
- Probe a pool of **CDN edge IPs** (and candidate `dest`s) with a **real carrier handshake**, measuring
  TCP/TLS-handshake success, latency, jitter, loss, and colo.
- **Score for "anti-drop", not just handshake success.** Iran's DPI does a **post-handshake kill** — TLS
  completes, then the flow is dropped seconds later. So the scanner must **hold each candidate under
  sustained traffic for ~15–20s** and rank by DPI-endurance, not "did TLS connect?" (this is what
  in-country scanners like Cloud-Scanner do). Scan **domestic CDN/provider ranges** (ArvanCloud e.g.
  `185.143.232.0/22`, plus IranServer/Parspack/…) for the survival carrier, and foreign CDN ranges for
  normal times.
- Rank by usability, **rebuild the dial address onto the winning edge** while the real host stays
  hidden, self-heal when an edge degrades.
- The **panel/control plane** feeds the client a curated, rotating edge/endpoint pool and can push a
  fresh pool via rendezvous (§8.4).

### 8.3 Rotation as a first-class assumption
- Treat every endpoint IP as **dead on a 48h–2-week horizon**; rotate *before* volume thresholds trip.
- Keep **per-IP traffic modest**; spread customers; retire IPs proactively (the REALITY-IP-dies-in-hours
  reality). The panel's node/rotation policy owns this (§ [04](04-panel-architecture.md)).

### 8.4 Rendezvous (get the first bit through under blockade)
A control channel **separate from the data plane** to deliver fresh endpoints/keys when defaults are
blocked. Layered, use whatever is reachable:
- **The Telegram bot you already run** — Telegram is a natural, often-reachable bootstrap channel;
  AtlasBot can hand a client a signed fresh-config blob.
- **Fronted mirrors** — a signed config blob mirrored behind Cloudflare Workers / domestic CDNs / DoH
  TXT records; the client tries many, needs one.
- **Refraction/Snowflake-style signaling** as a future option.
- All rendezvous payloads are **signed** by the control plane; the client trusts only signed blobs.

### 8.5 Operate with no reliable DNS (a first-class requirement)
During the cut, DNS was poisoned (→ `10.10.34.36`) and UDP/53 lossy — the weak link operators hit in
practice ("DNS was very slow"). The client must **never gate connect on DNS**:
- Dial **raw pinned edge IPs** (the `address`↔`SNI` split, §5.2); the subscription descriptor carries
  IPs, not just hostnames.
- Ship the **DoH resolver IP hardcoded**, and apply **first-flight fragmentation** (MahsaNG-style) to the
  DoH/TLS ClientHello so it clears SNI-DPI.
- Support **static host maps / pinning**; treat name resolution as best-effort over 443, never a
  precondition and never a UDP/53 dependency.

## 9. Honest limits — especially "connected during war"

- **The wartime cut is mostly a *selective whitelist/throttle*, not a total severance — and a
  domestic-CDN-fronted carrier survives it.** This is the corrected, evidence-backed position (June 2025;
  [01](01-iran-threat-model.md)): for most of the ~weeks of "blackout," fronting through a domestic CDN
  whose edges are in-country and whose backhaul is exempt (ArvanCloud AS205585, measured ~99.7% up) kept
  VLESS+WS alive when REALITY and direct-to-foreign died. **This is genuinely sellable**, and it is
  Atlas's SURVIVAL workhorse (§5.2). "Not fast but connected" is achievable across gears 1–3 and the
  stealth-blackout weeks.
- **Only the brief *hard* window is a true bearer problem.** During the ~4-day near-total phase
  (Jun 18–21 2025) even domestic-CDN egress narrowed toward only whitelisted destinations (Google/GitHub)
  + fully-domestic services; there the honest answer is a bearer (Starlink / audited mesh) — a physical
  play that is **not a scalable product**. **Don't promise the customer that the *hard* cut is covered.**
- **The domestic CDN is a state-aligned intermediary.** It terminates the outer TLS and can observe/log
  the edge connection. Our end-to-end inner Noise channel (§2, §5.2) keeps it seeing only ciphertext, but
  treat the edge as adversary-observable in all threat-modeling — never route anything in a form the edge
  can read.
- **Small-anonymity-set risk early on.** Until Atlas has many users, its safety comes entirely from
  looking *exactly* like the most common TLS/H3 — never from a clever distinct shape. Do not add any
  distinguishing quirk "for convenience."
- **TLS-in-TLS is an arms race.** §4.3 is our current answer; assume it must evolve.
- **Every claim here is provisional** until measured (§ [05](05-build-roadmap.md)).

## 10. Integration with the panel (EngineAdapter)

The Atlas server runs on a node beside (or instead of) Xray, fronted by a **node-agent** that implements
the same interface as the Xray adapter ([04](04-panel-architecture.md) §5.3):

- `Capabilities()` → declares `atlas/1` + supported carriers (`direct-tls`, `fronted-ws`, `masq-h3`,
  `bare-udp`) so the control plane only schedules Atlas inbounds onto Atlas-capable nodes.
- `Reconcile(DesiredState)` → idempotently makes the local Atlas server match: the set of authorized
  **client static public keys** (identity), per-user quota/expiry, and the active carriers/SNIs/edges.
  "Add a client" = register a pubkey; "remove" = drop it. No inbound-wide restart to add one user
  (contrast Xray/3x-ui, where a client write reloads xray and drops every live connection — a pain point
  documented all over [PROJECT_MAP](../../PROJECT_MAP.md)). **Atlas can make per-user changes hot** — an
  explicit design win to bake in.
- `StreamStats()` → per-user up/down byte counters, pushed continuously (feeds the same accounting the
  IP-guard and quotas already use).
- `HealthCheck()` → reachability + which carriers are currently serving.

### Client & subscription
A brand-new transport has **no existing client ecosystem** (v2rayNG/Streisand won't speak `atlas/1`).
Two realistic paths, decided in [05](05-build-roadmap.md):
1. **Build the Atlas core as a Go library** and expose it as a **sing-box-compatible outbound** (sing-box
   is pluggable and already powers Hiddify/NekoBox), so existing sing-box front-ends can carry it.
2. Ship a **thin custom client** (Go core + gomobile bindings) for Android/desktop.

Either way the panel's subscription service ([04](04-panel-architecture.md) §5) renders an **Atlas
subscription entry** — a signed JSON descriptor of carriers, endpoints, SNIs, the server static key,
and rendezvous mirrors — while continuing to serve **Xray/REALITY** to the existing client base
unchanged. The transports coexist; customers migrate gradually.

## 11. What we reuse vs. what we build (summary)

| Layer | Decision |
|---|---|
| Handshake | **Reuse** Noise_IK (Curve25519, ChaCha20-Poly1305, BLAKE2s) |
| Record crypto | **Reuse** AEAD + mandatory replay window (SIP022/WireGuard-style) |
| TLS fingerprint | **Reuse** uTLS, matching a current popular browser |
| QUIC | **Reuse** a mature library (quic-go) |
| Uniform keys | **Reuse** Elligator2 |
| Real-TLS carrier | **Adapt** the REALITY pattern (borrowed handshake + temp-cert splice + real-site fallback) |
| Inner-handshake flattening | **Build** (Vision-equivalent, data-driven, measured) |
| Polymorphic framing + first-packet shaping | **Build** |
| Carrier agility + per-operator pinning + clean-IP scanner | **Build** (the decisive part) |
| Four gear-matched modes | **Build** |
| Rendezvous | **Build** (leveraging the existing Telegram bot + fronted mirrors) |
| Panel integration | **Build** the Atlas EngineAdapter/node-agent; **reuse** the existing subscription/accounting engine |

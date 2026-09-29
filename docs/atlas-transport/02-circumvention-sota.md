# 02 — Circumvention transports: state of the art & detection

> The engineering prior art the Atlas design builds on. What each transport does, how it looks on
> the wire, how it gets detected, and the design principles that fall out. Cited inline.

Most detection research targets China's GFW — the most capable public adversary and the leading
indicator for Iran, which adopts GFW techniques later. So **GFW research is the right design
target**, and everything here is read through the Iran threat model in [01](01-iran-threat-model.md).

## 1. The transport landscape (threat model → wire appearance → detection)

### Shadowsocks / Shadowsocks-2022
- **Idea.** SOCKS-like proxy; the whole stream is one AEAD blob with **no headers** — the
  "look like nothing" school.
- **Wire.** High-entropy from the first packet, no handshake, no plaintext.
- **Detection.** *How China Detects and Blocks Shadowsocks* (IMC 2020): passively flag high-entropy
  first packets of certain lengths, then **actively probe** (replay/random payloads R1–R4); the
  server's *response to garbage* confirms it. ([gfw.report/imc20](https://gfw.report/publications/imc20/en/))
- **SS-2022 (SIP022).** BLAKE3 KDF, real random PSK (not a password), **mandatory replay protection**
  (timestamp + sliding window), session UDP, identity headers. Closes the replay-probe hole — **but
  is still high-entropy**, so still exposed to the fully-encrypted heuristic unless prefixed/wrapped.
  ([SIP022](https://shadowsocks.org/doc/sip022.html))

### VMess vs VLESS
- **VMess.** Built-in AEAD + a **time-based auth field** (clock-coupled — a liability); caught by the
  fully-encrypted heuristic.
- **VLESS.** Stateless, **no built-in encryption, no clock dependence**; delegates confidentiality to
  the outer transport (TLS/REALITY), so it has **no protocol-level entropy signature of its own**. The
  inner protocol of choice for VLESS+Vision+REALITY. ([Project X](https://xtls.github.io/en/config/outbounds/vless.html))

### Trojan
- **Idea.** *Be* a real TLS server with a real cert; authed clients tunnel, everyone else is served a
  real website. Relies on the censor not blocking all of 443.
- **Detection.** Outer TLS is genuine, but browsing HTTPS *through* it creates the **TLS-in-TLS**
  signature (§2). Non-browser TLS stacks also stand out by fingerprint.

### REALITY (the key modern design)
Sources: [XTLS/REALITY](https://github.com/XTLS/REALITY), [README.en](https://github.com/XTLS/REALITY/blob/main/README.en.md), [Project X docs](https://xtls.github.io/en/config/transports/reality.html).
- **Core trick.** Does **not** own or forge the target's cert. The client sends a genuine TLS 1.3
  ClientHello (via **uTLS**, matching a real browser) to a configured real SNI (e.g.
  `www.microsoft.com`), hiding an authenticator inside the **32-byte SessionID**: X25519 ECDH against
  the server's long-term public key → HKDF-SHA256 → AES-GCM-sealed token bound to a `shortId`.
- **Server decision.** Holding the private key, it redoes ECDH and tries to open the SessionID:
  - **Authorized →** the server terminates TLS with its **own on-the-fly temp cert** inside the
    already-encrypted channel; the client (which can tell temp from real) proceeds to proxy.
  - **Anything else (probe/scanner/browser) →** the whole TLS stream is **transparently forwarded to
    the real target**, so the prober completes a real handshake and gets the *genuine* cert/content.
- **Why it resists probing.** A prober gets microsoft.com's real cert and content — indistinguishable
  from an innocent reverse proxy. No target private key ⇒ censor can't MITM; probers never see the
  temp cert ⇒ no forged-cert catch.
- **Candid limits (from the project).** Target must support TLS 1.3 + HTTP/2 and sit outside the
  censor's country; and the README **warns against combining REALITY with non-XTLS inner protocols**
  because of "obvious and already targeted TLS-in-TLS characteristics." REALITY hides the *handshake*;
  tunneling your own HTTPS through it still creates an encapsulated handshake unless flattened.

### XTLS-Vision (the length-signature flattener)
`xtls-rprx-vision` detects the inner TLS 1.3 handshake and, once it completes, **stops re-wrapping the
inner TLS records** in its own record/encryption layer — so the tell-tale inner record-size pattern is
not re-emitted. A direct engineering response to TLS-in-TLS detection. **Atlas needs an equivalent.**

### NaiveProxy
- **Idea.** *Be a real Chrome.* Reuses **Chromium's actual network stack**, so TLS fingerprint +
  HTTP/2/3 frame patterns are byte-for-byte Chrome's; rides a real reverse proxy (Caddy `forwardproxy`)
  that routes by auth header, so **probes without the header get normal web responses**. Adds
  **length padding**. ([klzgrad/naiveproxy](https://github.com/klzgrad/naiveproxy))
- **Thesis.** "Improvised, expendable" configs impose more cost on the censor than one clever bespoke
  protocol — the **operational-diversity** argument.

### Cloak / obfs4 / meek / Snowflake / Conjure (briefly)
- **Cloak** — disguises arbitrary proxies as HTTPS, reverse-proxies probes to a real site, multiplexes
  over a fixed TCP pool. ([cbeuw/Cloak](https://github.com/cbeuw/Cloak))
- **obfs4** — Elligator2 over ntor so keys look uniform-random; padded handshakes; **per-bridge shared
  secret** defeats naïve probing. Detected as (a) fully-random traffic by the entropy heuristic, and
  (b) *Detecting Probe-resistant Proxies* (NDSS 2020) via **distinctive timeout/close behavior** when
  fed the wrong byte count. ([obfs4-spec](https://github.com/Yawning/obfs4/blob/master/doc/obfs4-spec.txt), [NDSS'20](https://www.ndss-symposium.org/ndss-paper/detecting-probe-resistant-proxies/))
- **meek** — domain fronting; mostly dead on majors since 2018; survives for low-bandwidth signaling.
- **Snowflake** — ephemeral volunteer **WebRTC** proxies + domain-fronted broker; huge IP churn defeats
  IP blocking; DTLS/STUN fingerprint + fronted signaling are the chokepoints.
- **Conjure / refraction** — proxy lives **in the network core** at friendly ISPs (client connects to
  an unused "phantom" IP; an on-path station recognizes a tagged flow). Survives IP-allowlisting, but
  **needs ISP partners** — not deployable by a small team alone. Measured under Iranian censorship in
  *Proxies as Sensors* (AsiaCCS 2025). ([refraction.network](https://refraction.network/))

### Hysteria2 / TUIC (QUIC-based)
- **Hysteria2.** QUIC/HTTP-3; masquerades as an HTTP/3 server with a real cert (probes get normal
  responses); optional **Salamander** XOR-obfuscation so it doesn't even look like QUIC; **Brutal** CC
  sends at a declared fixed rate ignoring loss — powerful on throttled links, but unfair and somewhat
  anomalous. ([Hysteria2 protocol](https://v2.hysteria.network/docs/developers/Protocol/))
- **TUIC v5.** QUIC, 0-RTT, TCP+UDP relay, connection migration, mux, user-space BBR.
- **Iran risk.** Both are UDP/QUIC — **fast under loss, but fragile under protocol-allowlisting**: if
  the censor throttles/drops UDP/443 QUIC (as Iran periodically does), a UDP-only transport dies
  regardless of stealth. ⇒ **dual TCP-TLS + QUIC with failover.**

## 2. How modern DPI/ML detects proxies

### Byte-entropy / randomness (the "look like nothing" killer)
- *Seeing through Network-Protocol Obfuscation* (CCS 2015): entropy tests over a small window of the
  first messages detect randomized obfuscators at low false-positive rates.
- *Fully Encrypted Traffic* (USENIX '23): the **deployed** version. The GFW **exempts** non-random
  traffic and blocks the rest via ~5 first-packet heuristics ([gfw.report](https://gfw.report/publications/usenixsecurity23/en/)):
  - **Ex1 (popcount):** average set-bits/byte in **[3.4, 4.6]** (≈ half — random-looking) ⇒ *not*
    exempted ⇒ candidate to block.
  - **Ex2:** exempt if first ≥6 bytes are printable ASCII (0x20–0x7e).
  - **Ex3:** exempt if >50% of bytes are printable ASCII.
  - **Ex4:** exempt if a run of >20 contiguous printable-ASCII bytes.
  - **Ex5:** exempt if it matches a known fingerprint (TLS record `\x16\x03…`, `GET `, `POST `…).
  - Blocked only if it fails **all** exemptions. **Countermeasure:** prepend a printable/TLS-looking
    prefix, or shape popcount out of [3.4,4.6]. Cost measured up to ~17% worst case.
  - **Lesson: pure high-entropy "random" transports are now a liability, and Iran can copy this cheaply.**

### TLS ClientHello fingerprinting — and why uTLS matters
JA3/JA4 fingerprint the cipher list, extension order, curves, ALPN, GREASE. A bespoke TLS stack (Go
`crypto/tls`, custom client) is a **distinctive minority fingerprint**. *The use of TLS in Censorship
Circumvention* (NDSS 2019) motivated **[uTLS](https://github.com/refraction-networking/utls)** — exact
reproduction of a popular browser's ClientHello, rotated as browsers update. **Any Atlas TLS must use
uTLS and blend into a large anonymity set — and a fingerprint no real browser currently ships is
itself a tell.**

### TLS-in-TLS detection (the current frontier)
*Fingerprinting Obfuscated Proxy Traffic with Encapsulated TLS Handshakes* (Xue et al., USENIX '24,
[PDF](https://ensa.fi/papers/sec24-xue.pdf)):
- **Insight.** Browsing HTTPS *through* a TLS proxy encapsulates the destination's handshake inside the
  proxy's TLS, producing a characteristic **record-size / direction / inter-packet-timing** shape early
  in the flow — common in proxied flows, rare in direct.
- **Danger.** **Protocol-agnostic** (doesn't care which obfuscation), builds classifiers on the first
  packets, practical for real-time in-network use.
- **Related.** Cross-layer RTT discrepancies (transport vs application session) also fingerprint proxies.
- **Response.** Exactly why XTLS-Vision exists. Any TLS-tunneling design must assume the censor can see
  "a handshake inside your handshake" unless you actively flatten it.

### Active probing & probe-resistance
Passive suspicion → the censor connects to confirm. NDSS '20 showed even *probe-resistant* proxies
(obfs4, SS) are confirmable via divergent **timeout/close behavior**. **The only robust defense is a
genuine, timing-matched fallback** — serve a real site to anyone who fails auth, and make the *way you
reject* indistinguishable from a real server (the absence of a tell must not itself be a tell).

### Flow/statistical/first-few-packets ML
Censors train on packet-size distributions, bursts, directionality, timing, duration — especially the
**first N packets** (cheap, early, real-time). Even mature encrypted VPNs get fingerprinted (*OpenVPN
is Open to VPN Fingerprinting*, USENIX '22, via opcode patterns + probe responses). Padding/timing
shaping targets these but **cannot fully erase them**.

## 3. Design principles (distilled → these become the spec)

1. **"Be, don't imitate" (Parrot is Dead, S&P 2013).** Don't half-imitate a protocol you don't fully
   implement — partial mimicry is worse than nothing. Two viable strategies: **(A) genuinely random +
   dodge the entropy heuristic**, or **(B) be the real thing** (real Chromium / real TLS-1.3-to-real-
   site). B is the modern winner in high-censorship environments.
2. **Polymorphic framing, no fixed signature.** No magic bytes, no fixed-length handshake, no constant
   field offsets, no clock-coupled tokens. If AEAD-blob, **shape the first packet** against Ex1–Ex5.
   Raw key material uniform-random via **Elligator2**.
3. **uTLS ClientHello mimicry, kept fresh**, matching a currently-popular browser with a large real
   anonymity set.
4. **Application-layer camouflage.** Terminate on a real web origin with a real ACME cert and real
   content, ideally behind a CDN / plausible domain. The transport is one behavior of an otherwise
   ordinary origin. Riding H2/H3 makes your mux/framing already match browsers.
5. **Padding + timing shaping — necessary but limited.** Do length/record shaping (targets length &
   TLS-in-TLS classifiers); treat timing mimicry as *raising cost*, not achieving invisibility; measure
   overhead.
6. **Graceful, timing-matched fallback — the single most important property.** Every surviving design
   shares it: an unauthenticated connection is indistinguishable from a real service.

## 4. Resilience over speed (for throttling/loss/shutdown)

- **QUIC/UDP under loss.** No cross-stream head-of-line blocking, modern loss recovery, **connection
  migration** (survive IP/NAT change) — real wins on lossy mobile. Hysteria claims 2–5× TCP on lossy
  links. **But UDP is fragile under allow-listing** ⇒ dual-stack + failover.
- **Congestion control.** Brutal (fixed-rate, ignore loss) beats artificial throttling but is
  anomalous; BBR is a balanced default. **Selectable CC**, default BBR, aggressive mode for known-
  throttled conditions.
- **FEC.** Trades bandwidth for loss-resilience; valuable on high-loss Iranian mobile — but fixed-rate
  FEC is another signature ⇒ **adaptive**.
- **Multiplexing.** Fixed-pool mux cuts handshakes and per-connection fingerprints, mitigates HoL — but
  the mux pattern is observable; keep it browser-like.
- **Rendezvous/bootstrapping.** Under shutdown/allowlisting, getting the *first bit* through is the hard
  part. Fronted/CDN signaling (Snowflake-style) and refraction survive allowlisting — **design a
  pluggable rendezvous layer even if the data plane is our own.**

## 5. Honest roll-your-own vs. compose guidance

**Reuse the crypto core; innovate only in obfuscation / camouflage / transport-selection.** The
Shadowsocks history is the object lesson: the 2017 AEAD lacked mandatory replay protection and used a
weak KDF → broken by replay probing → fixed only by adopting BLAKE3 + real PSKs + replay windows.

Compose:
- **AEAD** (ChaCha20-Poly1305 / AES-256-GCM) with careful nonces and **replay protection from day one**.
- **Noise Protocol Framework** for the handshake (rigorously analyzed; WireGuard's Noise_IK is the
  canonical "got it right by reuse"). ([noiseprotocol.org](https://noiseprotocol.org/noise.html), [WireGuard paper](https://www.wireguard.com/papers/wireguard.pdf))
- **uTLS** for any TLS fingerprinting.
- **A mature QUIC lib** (quic-go) rather than hand-rolled reliable-UDP.
- **Elligator2** for uniform-looking public keys.

**Where genuinely new contribution is realistic and valuable:** the polymorphic framing / first-packet
shaping layer; the fallback/camouflage strategy (matching *timing*, not just content); TLS-in-TLS
flattening + adaptive padding informed by the USENIX '24 features; transport agility + hard-to-block
rendezvous; operational diversity (many cheap disposable deployments).

**Then get it reviewed and measured** against the known detectors *before* relying on it.

## 6. Candid trade-offs & unknowns

- **No transport beats allow-listing or full shutdown by itself.** Survivors are things that *are*
  permitted traffic (real HTTPS/H3 to real origins) or live in the network core (refraction — needs ISP
  partners). **Plan a rendezvous story, not just a data plane.**
- **TLS-in-TLS is the current sharp edge** — even REALITY's authors flag it. Assume the censor can run
  the USENIX '24 detector; design flattening/padding accordingly; expect an arms race.
- **UDP/QUIC is fast but politically fragile in Iran** ⇒ dual-stack with failover.
- **"Random-looking" is no longer safe on its own** post-2021; Iran can copy the heuristic cheaply.
- **Anonymity-set risk.** A unique fingerprint — even "perfect random," even a browser fingerprint no
  one else currently uses — is a fingerprint. Blend into large, real populations and rotate.
- **Detection research moves fast, and much censor capability is unpublished.** Every "undetectable"
  claim, including ours, is provisional; instrument for rapid iteration and diverse deployment.

### One-line synthesis carried into the spec
Build on **audited primitives (Noise + AEAD-with-replay + uTLS + mature QUIC)**; make the transport
**be a real HTTPS/H3 origin** with a genuine timing-matched fallback (REALITY/Naive pattern) rather
than imitating one; **flatten TLS-in-TLS** and **shape the first packet** vs the entropy heuristic; run
**dual TCP-TLS + QUIC with hard-to-block fronted rendezvous**; prioritize **loss/throttle resilience**
over peak speed. Reserve novelty for obfuscation, camouflage, shaping, and agility — **not the crypto**.

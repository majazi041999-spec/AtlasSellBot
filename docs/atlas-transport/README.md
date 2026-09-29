# Atlas Transport & Independent Panel — Design Dossier

> Status: **design only** (no executable code yet). This directory is the research +
> architecture deliverable for building (a) an independent management panel to replace our
> dependence on 3x-ui / MHSanaei, and (b) our own censorship-circumvention transport tuned
> for Iran under everyday filtering *and* wartime shutdown conditions.
>
> This is anti-censorship engineering in the tradition of Tor pluggable transports,
> Xray/REALITY, NaiveProxy and Psiphon: the goal is keeping ordinary people in Iran connected
> to the open internet. Every design choice below is grounded in primary measurement research,
> cited inline in the sub-documents.

## خلاصه‌ی فارسی (برای صاحبِ پروژه)

هدف: یه **پنلِ مستقل** (جایگزینِ 3x-ui) که به یه یا چند **موتورِ ترنسپورت** وصل شه — هم Xray فعلی، هم
ترنسپورتِ خودمون — و یه **ترنسپورتِ اختصاصیِ Atlas** که برای شرایطِ ایران ساخته شده.

سه یافته‌ی اصلی که کلِ طراحی رو شکل می‌ده:

1. **«دیرتر لو رفتن» = بی‌الگو بودن، نه پروتکلِ تازه.** هر امضای متمایزی بالاخره یاد گرفته می‌شه
   (مرجع: *The Parrot is Dead*، و کشته‌شدنِ REALITY/Shadowsocks در ایران). پس Atlas روی سیم باید
   **رایج‌ترین/بی‌شباهت‌ترین چیز** باشه (TLSِ مرورگرِ واقعی / HTTP‑3)، و نوآوری‌اش در **چابکی و چرخش و
   شکل‌دهی** باشه، نه در یه شکلِ تازه‌ی قابل‌تشخیص.
2. **ایران به «اعتبار و رفتار» حمله می‌کنه، نه فقط بایت‌ها.** IP تو چند ساعت/روز graylist می‌شه.
   پس **چرخشِ IP و کشفِ خودکارِ edgeهای تمیز باید قابلیتِ درجه‌یک باشه**، نه وصله‌ی بعدی.
3. **ایران ۴ دنده داره** (فیلترِ عادی ← throttle ← allow‑list پروتکل ← بلک‌اوتِ کامل). هیچ پروتکلی
   به‌تنهایی از بلک‌اوت رد نمی‌شه؛ پس Atlas باید **۴ حالتِ متناظر** + یه **لایه‌ی rendezvous** برای
   بوت‌استرپ در سخت‌ترین شرایط داشته باشه.

رمزنگاری از صفر نمی‌نویسیم (ریسکِ فاجعه‌بار). روی primitiveهای اثبات‌شده سوار می‌شیم:
**Noise Framework (هندشیک) + ChaCha20‑Poly1305 (AEAD) + uTLS (اثرانگشتِ TLS) + quic‑go (مسیرِ QUIC) +
Elligator2 (پنهان‌کردنِ کلیدها).**

پنل هم روی همون انتزاعی که الان با `XUIClient` داری سوار می‌شه: یه **EngineAdapter** مشترک، که هم Xray و
هم Atlas پشتش می‌شینن، بدون این‌که کاربر/صورت‌حساب/subscription به Xray گره بخوره.

---

## The central thesis (read this first)

The request was "a protocol stealthier than V2Ray, whose pattern is detected and filtered
*later*." The research makes the correct form of that goal precise, and it is counter-intuitive:

**A brand-new, distinctive protocol is easier to fingerprint over time, not harder.** Two
independent lines of evidence:

- *The Parrot is Dead* (IEEE S&P 2013) — systems that **imitate** a protocol fail, because you
  must reproduce its entire stack, side-channels and error behavior; a censor finds the
  discrepancies from a single session.
- China's **fully-encrypted-traffic heuristic** (USENIX Security 2023) turned "looks like random
  bytes" from an asset into a liability — a cheap first-packet entropy test that Iran can copy.

So the only two wire strategies that survive are: **(A) be genuinely featureless *and* dodge the
entropy heuristic**, or **(B) be the real thing** — ride a genuine TLS 1.3 / HTTP-3 session to a
real-looking origin so there is nothing to imitate and your anonymity set is "every browser."
Strategy B is what REALITY and NaiveProxy do, and it is what currently survives longest in Iran.

**Design consequence:** Atlas's novelty lives *above and around* the wire, never in a new wire
signature:

| Where we innovate (our own work) | Where we reuse audited primitives (never roll our own) |
|---|---|
| Polymorphic framing + first-packet shaping (dodge entropy heuristic, no fixed magic) | Handshake: **Noise_IK** (WireGuard's approach) |
| Adaptive TLS-in-TLS flattening + padding policy | Record crypto: **ChaCha20-Poly1305 / AES-256-GCM AEAD** + mandatory replay window |
| Carrier agility + per-operator auto-selection + built-in clean-IP scanner | TLS fingerprint: **uTLS** (mimic a current popular browser) |
| Gear-matched operating modes (normal / throttle / allowlist / blackout) | QUIC path: a **mature QUIC library** (quic-go), not hand-rolled reliable-UDP |
| Rendezvous layer (fronted config delivery, bootstrap under blackout) | Uniform-random key encoding: **Elligator2** (as obfs4) |

This reframing is the single most important output of the research. It means the "independent
protocol" you asked for is real and worth building — but its independence is in the **control,
camouflage, and agility layers**, while its bytes deliberately look like the most common,
highest-anonymity-set traffic on the wire.

## The four gears (our operating modes must match the censor's)

Iran dials censorship through four regimes at a single TCI data-plane chokepoint. Atlas defines one
mode per gear (detailed in [03-atlas-protocol-spec.md](03-atlas-protocol-spec.md) §7):

| Censor gear | What survives (from measurement) | Atlas mode |
|---|---|---|
| 1. Normal SNI/IP filtering | REALITY-class camouflage; clean CDN edges | **Direct carrier** — borrowed-TLS over TCP, uTLS ClientHello, probe→real-site fallback |
| 2. Throttling / packet loss | Domestic-CDN fronting; loss-tolerant transports | **Fronted carrier** — WS/XHTTP behind Cloudflare/ArvanCloud + clean-IP rotation + FEC |
| 3. Protocol allow-list (only DNS/HTTP/HTTPS) | Traffic that *is* permitted HTTPS/H3 | **Masquerade carrier** — genuine H3/HTTPS to a whitelisted-class origin |
| 4. Near-total blackout (domestic whitelist) | Out-of-band bearers; fronted rendezvous | **Survival mode** — fronted/refraction rendezvous, satellite/mesh bearer, minimal keep-alive |

An honest limit, stated up front (expanded in §9 of the spec): **no data-plane transport defeats a
full blackout by itself.** Gear 4 is a rendezvous-and-bearer problem, not a protocol problem. Atlas
can be *ready* for it (pluggable bearer, fronted bootstrap) but cannot manufacture connectivity the
censor has physically severed.

## How this plugs into the existing AtlasBot

The current stack (see [PROJECT_MAP.md](../../PROJECT_MAP.md)) already has the right seams:

- **`core/xui_api.py::XUIClient`** is, in effect, today's single engine adapter. The panel design
  generalizes it into an **`EngineAdapter`** interface (`Capabilities / Reconcile / StreamStats /
  HealthCheck`) that both an Xray node-agent and an Atlas node-agent implement — so adding Atlas is
  "a new adapter," never a change to users, billing, resellers, or subscriptions.
- **`core/multi_subscription.py`** already fans a subscription across heterogeneous nodes. Atlas
  nodes become another node kind in that engine; the per-node `connect_host` override and the
  Cloudflare-fronting you already run are the seed of the clean-IP rotation the transport formalizes.
- Your operational knowledge is a moat: MCI weekly-Tuesday waves, Irancell 50% loss, carrier-NAT
  learning, CF-edge realities, PMTU blackholes, per-node routes to Iran — all already recorded in
  PROJECT_MAP and memory. The transport design leans on it directly.

## Documents in this dossier

1. **[01-iran-threat-model.md](01-iran-threat-model.md)** — how Iran filters (the four gears, the
   DPI stack, fingerprinting/probing, TLS-in-TLS), a 2022→2026 timeline of what broke and what
   survived, what kept people connected, and "proxy scanning" as practiced. The adversary spec.
2. **[02-circumvention-sota.md](02-circumvention-sota.md)** — the transport landscape
   (Shadowsocks-2022, VLESS, Trojan, REALITY/Vision, NaiveProxy, Cloak, obfs4, Hysteria2/TUIC,
   Snowflake, Conjure), how modern DPI/ML detects each, and the distilled design principles.
3. **[03-atlas-protocol-spec.md](03-atlas-protocol-spec.md)** — the Atlas Transport: secure-channel
   core, carriers, polymorphic framing, probe-resistant fallback state machine, the four modes,
   carrier agility + clean-IP scanner, rendezvous, and the EngineAdapter mapping. The crown jewel.
4. **[04-panel-architecture.md](04-panel-architecture.md)** — the independent, transport-agnostic
   panel: control plane, node agent, subscription service, accounting, data model, and the exact
   seam that lets Xray and Atlas coexist. Mapped onto the current Python/SQLite stack.
5. **[05-build-roadmap.md](05-build-roadmap.md)** — phased plan from PoC to limited rollout, with
   the adversarial tests each phase must pass before we trust it.

## Non-negotiable honesty rules for this project

Carried from the research and from how this repo already documents hard truths:

- **Every "undetectable" claim is provisional**, including our own. Instrument for fast iteration;
  measure against the known detectors (entropy heuristic, probe-timing, encapsulated-handshake
  classifier) *before* relying on anything.
- **Get the design adversarially reviewed** (net4people/bbs, academic groups routinely break new
  tools) before it carries real customers.
- **Rotation and disposability are assumptions, not features.** Any endpoint IP is dead on a
  ~48h–2-week horizon; design as if that is normal.
- **The crypto is not ours to invent.** If a change touches the handshake or record format, it must
  be a composition of reviewed primitives, or it does not ship.

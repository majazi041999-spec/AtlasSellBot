# 01 — Iran Threat Model: how the censor actually works (2022–2026)

> The adversary specification for the Atlas transport. Sourced from primary/technical work: OONI,
> IODA/Georgia Tech, GFW.report, net4people/bbs, XTLS/Xray-core issues, USENIX, and two detailed
> 2025–26 measurement preprints. Confidence and contested points are flagged.

## 0. The one-paragraph model

Iran does **not** run a monolithic Great Firewall. It runs a **centralized, TCI-operated DPI
chokepoint** at the international border, layered on the **National Information Network (NIN /
شبکه ملی اطلاعات)**, **tuned per-operator and per-region**, and dialed between four regimes:
normal filtering → protocol throttling → protocol allow-listing → near-total blackout with a
domestic-only whitelist. The censor attacks **reputation and behavior at least as much as bytes**.
A transport that (1) shows no proxy fingerprint, (2) rides reputationally-clean, rotatable,
CDN-fronted IPs, (3) can masquerade fully as an allow-listed HTTPS/H3 flow, and (4) has an
out-of-band bearer for total blackout — with per-operator fallback throughout — matches this
threat model best.

## 1. The National Information Network is the enabling substrate

NIN is a domestically-hosted parallel backbone (national CDNs, DNS, messengers Rubika/Eitaa/Bale,
banking, government) that lets the state **decouple domestic reachability from international
transit**. Because everyday life keeps working "inside," the state can throttle or sever the
international gateway and still function — which is what makes shutdowns politically survivable.

Architecturally decisive finding: during the **June 2025** and **January 2026** shutdowns,
**Iranian prefixes stayed announced in global BGP** (~98.14% still routed in Jan 2026) **while
traffic nearly ceased** — "all observed interference occurred at the same network hop across all
tested ISPs," i.e. a **single common chokepoint** enforced in the **data plane**, not at routing.
([arXiv 2507.14183](https://arxiv.org/pdf/2507.14183), [arXiv 2603.28753](https://arxiv.org/html/2603.28753v1))

> **Design takeaway:** route-level reachability tells you *nothing* about whether a transport will
> pass. Health-check at the data plane, from inside the target networks.

## 2. The DPI stack (concrete mechanisms)

Converging across [OONI](https://ooni.org/post/iran-internet-censorship),
[arXiv 2507.14183](https://arxiv.org/pdf/2507.14183), [arXiv 2603.28753](https://arxiv.org/html/2603.28753v1):

- **DNS poisoning/injection.** >90% of blocked domains resolve to the block-page IP **10.10.34.34**,
  injected in-path with low TTL. DoH/DoT to 1.1.1.1 / 8.8.8.8 is itself tampered with.
- **HTTP filtering.** Inspects `Host` and URL path, injects HTTP 403 or TCP RST; historically
  **case-sensitive** (allowed header-case evasion for a time).
- **SNI-based TLS filtering.** For forbidden SNIs, an **RST is injected right after the ClientHello,
  before any certificate exchange**. On MCI, Cloudflare-hosted proxies get "the SNI blocked if it
  detects a proxy," independent of transport (gRPC/WS). ([net4people #253](https://github.com/net4people/bbs/issues/253))
- **IP/subnet blocking + graylisting.** Large IP graylists; IPs "with no traffic for 3 months" have
  been blocked, and year-old ranges persist on lists. ([Xray-core #3269](https://github.com/XTLS/Xray-core/discussions/3269))
- **Protocol allow-listing.** In the harshest gears, **only DNS/HTTP/HTTPS is forwarded and
  everything else silently dropped.** Irancell/MTN "blackholes the TCP connection based on the first
  few packets if they don't match HTTP or TLS" — a **positive first-packet allow-list**.
- **Throttling / shaping.** Degrade rather than block: MCI throttles **upload to <1 Mbps** by
  whitelisted SNI/IP; MTN applies **~50% packet loss regardless of protocol**; **QUIC/HTTP3 zeroed
  wholesale** (first seen 22 Sep 2022). ([net4people #253](https://github.com/net4people/bbs/issues/253), [IODA/OONI 2022](https://ioda.inetintel.cc.gatech.edu/reports/technical-multi-stakeholder-report-on-internet-shutdowns-the-case-of-iran-amid-autumn-2022-protests/))

## 3. Fingerprinting, active probing, TLS-in-TLS

- **Fully-encrypted-traffic / entropy detection.** Flag connections whose **first packet is
  high-entropy with no printable-ASCII prefix**; catches Shadowsocks, VMess, obfs4. Iran exhibits the
  same first-packet-classification family (the MTN "must be HTTP/TLS" rule is its allow-list dual).
  ([GFW.report / USENIX '23](https://gfw.report/publications/usenixsecurity23/en/)) — see
  [02](02-circumvention-sota.md) §2 for the exact Ex1–Ex5 heuristics.
- **Active probing.** After passive suspicion, the censor connects to confirm. In Iran this is
  inferred (100% CPU spikes coinciding with blocking; "strange IPs with many requests"); the strong
  community hypothesis is **reverse-DNS/SOA verification** — a Hetzner VPS claiming to be Microsoft is
  detectable. *Confidence: medium (community reverse-engineering).* ([Xray-core #3269](https://github.com/XTLS/Xray-core/discussions/3269))
- **TLS-in-TLS detection.** The strongest protocol-agnostic attack: a TLS session carrying another
  TLS handshake has a distinctive **record-size / burst / round-trip** fingerprint that survives
  padding and multiplexing (Xue et al., USENIX Security 2024). Community telemetry claims Iran/GFW
  reached **~80% TLS-in-TLS detection since ~Sep 2025** — *mechanism sound, exact number soft.* This is
  why XTLS-Vision stops double-wrapping inner TLS. ([USENIX '24](https://ensa.fi/papers/sec24-xue.pdf))

## 4. Timeline — what broke, what survived (2019 → 2026)

| Date | Event | Broke | Survived |
|---|---|---|---|
| Nov 2019 | "Bloody November" | ~week national shutdown (routing-level) | NIN domestic |
| Sep–Oct 2022 | Mahsa Amini "digital curfew" | Nightly mobile shutdown ~4PM–midnight (MCI/Irancell/Rightel); QUIC zeroed; Instagram/WhatsApp blocked | Psiphon, Tor **Snowflake** spikes; some fixed-line |
| Dec 2022 | v2ray/SS "limiting" | VMess-WS-TLS, SS+Cloak limited **on one or two ISPs** | Same configs on other operators — selective |
| Aug 2023 | MCCI protocol wave | **REALITY blocked in hours at low traffic**; relayed WS+TLS degraded | Same protocols still worked on Irancell |
| Apr 2024 | REALITY graylisting (MCI) | Plain vless-tcp-tls + Vision blocked once IP graylisted; high-traffic REALITY IPs die in hours–2 days | **Fresh, low-traffic IPs with low-profile SNI survived weeks** |
| Oct 2024 | Tunnel-transport wave | **VLESS/VMess+TCP+header "fully detected"**, MCI + Irancell simultaneously | **Shadowsocks and REALITY in tunnels still unblocked** |
| 2024–25 | MCI weekly cadence | MCI updates filters **~every Tuesday**; VLESS-TLS needs whitelisted SNI | REALITY was "the only protocol functioning across both ISPs" for a window |
| **Jun 13–25 2025** | **Israel–Iran war "stealth blackout"** (4 phases: 2 drills → **~4-day near-total Jun 18–21** → tiered recovery; app-block tail to ~mid-July ≈ the "40-day" *felt* window) | **~90–97% drop**; **selective whitelist filter at the TCI gateway (AS49666), NOT a severance**; BGP kept up; UDP/QUIC killed (UDP/53 only) | NIN up; **ArvanCloud AS205585 measured "unaffected" (~99.7% hosts)**; **domestic-CDN-fronted VLESS+WS survived**; Psiphon ~1.5M; Lantern fronting ~40% |
| ~Sep 2025 | TLS-in-TLS wave | Naïve nested-TLS proxies degrade (~80% claim) | Vision, fragmentation, AmneziaWG |
| Jan 8 2026 | **Most severe shutdown to date** | IPv4 traffic ceased; TIC cut from Rostelecom & Gulf Bridge; **Tor/Psiphon blocked *before* the cut** | **Domestic-only whitelist** (Google, Bing, Play/App Store, Apple, ChatGPT, GitHub…); Starlink (heavily jammed); mesh apps |
| Feb 2026 → | "Tiered / selective internet" | Restoration to only ~25–50% of pre-shutdown; **tiered access needing in-person ID, fixed-IP registration, written pledges** | Whitelisted services; registered users |

**Pattern to internalize:** waves target **transport signatures**, roll out **per-operator first**,
and each is "solved" in turn (TCP+header → plain TLS → REALITY-by-reputation → TLS-in-TLS). A
protocol's survival is a **moving target measured in weeks**, and the same config often works on
Irancell after it dies on MCI.

## 5. What kept people connected under severe conditions

- **Starlink** — the only thing that works during a *total* transit cut (bypasses TCI). ~50k–100k
  terminals smuggled in. **Not a clean win:** nationwide RF jamming (Tehran loss 30%→>80% from Jan
  2026), GPS jamming/spoofing, a formal ban, and RF direction-finding to locate users. *Contested:
  "neutralised" (state-aligned) vs "resilient" (researchers). Honest read: degraded, not dead, and
  physically risky to the user.*
- **Domestic "inside" (داخل) configs.** The dominant everyday technique: put the proxy behind
  **Iranian CDN IPs** (ArvanCloud 185.143.x.x, Derak, IranServer, ParsPack) so the user-facing address
  is domestic and mostly un-blockable (blocking it breaks Iranian business), paired with
  **geosite:ir/geoip:ir** routing so only foreign traffic is proxied. **This is why "inside" configs
  survive throttling that kills foreign-hosted ones.** *(We already do this — CF-fronting +
  per-node `connect_host`.)*
- **Clean-IP hunting + Cloudflare scanning.** Censors *throttle* rather than block Cloudflare (can't
  kill all of it), so users **scan ~1.5M CF IPs for un-throttled edges** and rebuild configs (see §6).
- **Cloudflare WARP / WARP-on-server** — gives the proxy a clean CF egress IP instead of a flaggable
  datacenter IP.
- **Domain fronting** — mostly dead on the majors (Google/Amazon 2018, Azure Jan 2024, Fastly 2024)
  but not extinct (~22 smaller CDNs; a few high-value fronts survive). Treat as **bonus, not
  foundation.**
- **Protocol survival, ranked:** REALITY longest (attacked now by IP reputation + volume heuristics +
  reverse-DNS, **not** protocol fingerprint); Shadowsocks/Trojan+obfs in tunnels; **AmneziaWG**
  (junk-padded, timing-randomized WireGuard) effective in 2026. **Killed fast:** VLESS/VMess+TCP+header,
  plain vless-tcp-tls on graylisted IPs, QUIC/HTTP3 (blanket), well-known proxy SNIs.

### The June 2025 "stealth blackout" — the mechanism that kept Iran-fronted VPNs alive
The case that matters most for a sellable wartime product. Firsthand operator reports + in-country
measurement converge ([WWW '26 / Cui et al.](https://www.liumx.net/publications/WWW26-Internet_Shutdown.pdf),
[arXiv 2507.14183](https://arxiv.org/html/2507.14183), [Miaan](https://miaan.org/report-on-irans-blackout-of-the-global-internet/),
[Nym](https://nym.com/blog/nym-iran-report-2025), [net4people #484](https://github.com/net4people/bbs/issues/484)):

- **It was a selective filter at the TCI gateway (AS49666), not a physical severance.** BGP stayed
  announced (80–88% of prefixes still globally visible); the border forwarded **only DNS/HTTP/HTTPS on
  TCP** and **silently dropped UDP** (WireGuard/OpenVPN/QUIC/WebRTC dead; **UDP/53 the sole, lossy
  exception**). A surviving **~3–10%** of international traffic was reserved for state/NIN-critical needs.
- **The domestic sphere stayed fully up, and ArvanCloud (AS205585) was measured "unaffected" — ~99.7% of
  its hosts retained** while Irancell/TCI/MCI collapsed 95–97%. Its edges are **inside Iran**
  (Tehran/Isfahan/Mashhad/Tabriz/Shiraz) and its **international egress survives via Dubai-registered
  bridge ASNs (AS200315 / AS208006)** + domestic AS202468 — not the filtered consumer TIC path. It is the
  state's own critical-infra CDN (banks, e-gov, state nameservers), so it sits inside the surviving remainder.
- **So the surviving path was:** user → **domestic ArvanCloud edge** (reachable; looks like ordinary
  domestic HTTPS) → **CDN backhaul that stayed up** → foreign origin. **VLESS+WS survived** here;
  **REALITY and direct-to-foreign died** (foreign IPs blocked; ServerHello injected on direct foreign TLS;
  REALITY cannot ride a CDN). Survival was **per-operator/per-phase** — in the **~4-day hard window
  (Jun 18–21)** even this narrowed toward only whitelisted Google/GitHub + fully-domestic services.
- **Critical caveat for us:** ArvanCloud is **state-aligned** and **terminates the outer TLS at its edge**
  — treat that edge as an **adversary-observable point**. Any design fronting through it must keep an
  **end-to-end inner channel** so the edge sees only ciphertext (see [03](03-atlas-protocol-spec.md) §2, §5.2).

### Per-operator / per-region (design-critical)

| Operator | Behavior |
|---|---|
| **MCI / Hamrah-e-Aval** (state-linked) | Most aggressive: IP-block + SNI filter + upload throttle <1 Mbps; **updates ~weekly, Tuesdays** |
| **Irancell (MTN)** | First-packet protocol allow-list + **~50% packet loss** shaping |
| **Rightel** | Shares MTN filtering, historically **more stable** than MCI |

Regional: Tehran worst on MCI/Irancell; **East Azerbaijan noticeably freer**; even Irancell prefix
`0918-` blocked more than `0914-`. **Most IPs blocked on MCI still work on Irancell and vice-versa.**

## 6. "Proxy scanning" as practiced (what our client should automate)

In Iran, "config/proxy scanning" almost always means **clean-IP hunting for CDN-fronted (usually
Cloudflare) configs**. The workflow, which Atlas should build in and self-heal on:

1. Start from a working CDN-fronted config template (VLESS/VMess + WS/gRPC + TLS behind Cloudflare).
2. **Scan Cloudflare's ranges.** ICMP is blocked, so scanners use **TCP/TLS-handshake timing**, tag
   by colo (FRA/DXB/IST), latency, jitter, loss — often building a real proxy handshake so a
   "reachable" IP is actually *usable*. (Tools in the wild: `cfray`, `CFScanner`, CF clean-IP scanners.)
3. **Auto-generate ready-to-import configs** from winning IPs; the dialed "server address" becomes
   the clean CF IP while the real host stays hidden.
4. **Layer TLS fragmentation + SNI variation.** *But by ~2026 Iranian DPI does stateful reassembly
   before SNI inspection*, so plain fragmentation is fading → users move to **TCP sequence injection /
   fake-ClientHello decoys / TTL-limited decoy packets**. ([Xray #2000](https://github.com/XTLS/Xray-core/issues/2000), [#5969](https://github.com/XTLS/Xray-core/discussions/5969))

The same mindset applies to self-hosted REALITY: rotate to fresh VPS IPs, pick **low-profile,
reputationally-consistent, ideally domestic `dest`/SNI**, keep per-IP volume modest.

## 7. Evidence-based requirements handed to the transport design

**Avoid / defend explicitly (detected fast):**
1. TLS-in-TLS / nested handshakes — padding+mux alone won't save you.
2. First-packet high entropy with no ASCII prefix.
3. TCP+header obfuscation transports (already fully detected).
4. Reputation signals: datacenter IPs with mismatched reverse-DNS/SOA; high per-IP volume; well-known
   proxy SNIs.

**Lean on (survives longest):**
1. REALITY-class camouflage (borrow a real ServerHello; weak point = IP reputation, not shape).
2. CDN fronting + clean-IP rotation; domestic CDNs for throttle-stickiness.
3. Obfuscated UDP (AmneziaWG-style) with randomized junk/timing — **but don't look like QUIC**
   (QUIC is blanket-blockable).
4. ClientHello fragmentation / decoy tricks — with the caveat that reassembly is catching up.

**Operational patterns to design *in*, not bolt on:**
- **Rotation as a first-class feature** (assume 48h–2-week IP lifetime; rotate before volume trips).
- **Clean-IP discovery in the client** (real-handshake timing probes; self-heal onto working edges).
- **Per-operator, per-region fallback** (carry multiple carriers; A/B; pin the winner per network).
- **Host/identity consistency** (reverse-DNS/WHOIS matching the impersonated identity).
- **Gears matching the censor's gears** (§ four modes in the spec).
- **An out-of-band bearer for total blackout** (satellite / *audited* mesh — note Bitchat shipped two
  zero-days, so audited-mesh is the requirement, not mesh per se).

## Source reliability & gaps

- **Highest confidence (primary/technical):** OONI 2022, IODA/Georgia Tech, GFW.report + Geneva,
  USENIX '24 (TLS-in-TLS), net4people/bbs #142/#166/#231/#253/#277/#359/#410, Xray-core
  #2000/#3269/#5969.
- **Recent, largely single-source (corroborate before betting):** arXiv 2507.14183 (Jun 2025) and
  2603.28753 (Jan 2026) — most detailed 2025–26 measurements, but preprints.
- **Contested:** exact active-probing method (reverse-DNS/SOA is hypothesis); Starlink jamming
  efficacy; the "~80% TLS-in-TLS since Sep 2025" figure (commercial blog; mechanism sound, number soft).

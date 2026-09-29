# 04 — Independent, transport-agnostic panel

> How to replace our dependence on 3x-ui / MHSanaei with our own panel that drives **both** Xray
> (today) and the Atlas transport (later) as equal citizens — as an **evolution of the current
> AtlasBot stack**, not a rewrite. Prior-art details (3x-ui, Xray-core config model, Marzban/
> Marzneshin, subscription formats) are in the research appendix at the end.

## 1. Why our own panel

- **Independence from a third party.** 3x-ui's release cadence, breaking changes, and any future
  telemetry/backdoor risk are outside our control; the panel is our core business system.
- **A per-user hot-update engine.** 3x-ui rewrites an inbound and reloads xray on almost every client
  write, dropping every live connection on that server — the single most painful constraint documented
  throughout [PROJECT_MAP](../../PROJECT_MAP.md) (§6, §6c, §6d). An Atlas-native server can add/remove a
  user without touching anyone else's connection. Our own panel lets us exploit that.
- **A real transport seam.** To run Atlas at all we need a control layer that isn't wired to Xray's JSON
  shape. Building that seam *is* building the independent panel.

## 2. The precedent to generalize

From the research: **3x-ui is single-node-per-instance** (one binary ⇄ one local xray; "multi-node"
only means several instances sharing a Postgres for *reporting*). **Marzban / Marzneshin** are the right
precedent — a central **panel** (source of truth for users/plans/resellers) + a thin **node agent** on
each VPS, over mTLS. **Marzneshin's `marznode` goes further**: it is decoupled from any single backend
(drives xray / sing-box / hysteria) via gRPC. **We push that one level higher**: the abstraction is about
*capabilities*, not "which VPN engine," so a genuinely non-VPN-shaped transport (Atlas) is a first-class
backend, not a special case.

## 3. Components

```
                       ┌─────────────────────────────┐
                       │        Control plane          │  (the current bot+FastAPI, evolved)
                       │  auth/RBAC · resellers ·       │  = single writer of truth
                       │  plans/quotas · node registry ·│
                       │  orchestration API · bot API   │
                       └───────────────┬────────────────┘
                                       │ mTLS + gRPC (versioned)   ← replaces per-panel HTTP login
             ┌─────────────────────────┼─────────────────────────┐
             ▼                         ▼                         ▼
      ┌──────────────┐         ┌──────────────┐          ┌──────────────┐
      │  Node agent    │        │  Node agent    │         │  Node agent    │   (1 per VPS; we have
      │  Xray adapter  │        │  Xray adapter  │         │  Atlas adapter │    SSH to all 5 already)
      └──────────────┘         └──────────────┘          └──────────────┘
             │                         │                         │
       xray-core                 xray-core                 Atlas server

      ┌─────────────────────┐          ┌─────────────────────┐
      │ Subscription service  │◄────────┤ Accounting/telemetry  │
      │ b64 · Clash · sing-box│          │ traffic ingest ·      │
      │ · Atlas descriptor    │          │ quota · aggregation   │
      └─────────────────────┘          └─────────────────────┘
```

- **Control plane** — the *only* writer of truth (users, resellers/campaigns, plans, node inventory,
  inbound templates). Today this is the aiogram bot + FastAPI + SQLite in AtlasBot; it stays, and grows
  a node-registry + orchestration API. Exposes the admin API and the bot/reseller API it already has.
- **Node agent** — one small process per VPS. It **never decides policy**; it receives a declarative
  **desired-state** document and reconciles the local engine(s), then streams back health/traffic. It's
  engine-pluggable (Xray adapter today, Atlas adapter next). Runs at **low trust** on leased VPSes.
- **Subscription service** — stateless renderer: reads "what does user X currently have access to" and
  emits base64 / Clash / sing-box for existing clients, **and the signed Atlas descriptor** for the
  Atlas client. Pure presentation, no provisioning logic. (Today: `render_subscription` in
  `multi_subscription.py` + `/sub/{token}`.)
- **Accounting/telemetry** — ingests per-node traffic deltas from the agent stream (not by scraping each
  engine differently), attributes to users/resellers, enforces quota/expiry. (Today: the usage sweeps,
  `PanelSessions` bulk snapshots, IP-guard — all of which become *consumers of the agent stream* instead
  of HTTP-polling 3x-ui.)

## 4. Data model (engine-agnostic)

Keep the transport out of the core tables so `User`/`Plan`/`Reseller`/`TrafficRecord` never reference
Xray specifics — this is what lets one row set drive an Xray node or an Atlas node:

```
Node            { id, name, region, endpoint, agent_cert_fingerprint, capabilities[], status }
Engine          { id, node_id, kind ("xray"|"atlas"), version, health }
InboundTemplate { id, protocol, transport, tls_mode ("none"|"tls"|"reality"|"atlas-*"),
                  params(json), engine_kind }        -- engine-agnostic "what to expose"
NodeInbound     { id, node_id, inbound_template_id, listen_port, tag, rendered_config(json) }
Plan            { id, name, quota_bytes, duration_days, reseller_price, concurrent_ip_limit }
Reseller        { id, parent_reseller_id?, pricing_overrides(json) }  -- grandfathering (see memory)
User            { id, owner_reseller_id, plan_id, secret_or_pubkey, expires_at, enabled }
UserAccess      { user_id, node_inbound_id }         -- which nodes/inbounds this user may use
TrafficRecord   { user_id, node_id, period_start, up_bytes, down_bytes }  -- append-only, aggregated
Subscription    { user_id, token, format_hint }
```

This maps cleanly onto the existing schema in `core/database.py` (`servers`,
`subscription_node_configs`, `subscription_profiles`, `subscription_nodes`, `packages`, `users`) — the
migration is mostly **renaming/generalizing "server = 3x-ui panel" into "node + engine + agent,"** and
adding a `capabilities`/`engine_kind` dimension. Reseller grandfathering, custom pricing, and the
per-profile `ip_limit` all survive unchanged because they never touched Xray internals.

## 5. The transport seam (the whole point)

### 5.1 One adapter interface — the generalization of `XUIClient`
`core/xui_api.py::XUIClient` is already, in effect, our single engine adapter (add/update/del client,
get_inbound, online counts, bulk enable/disable, traffic snapshot). Generalize it into an interface
every engine adapter implements — running inside the node agent:

```protobuf
service EngineAdapter {
  rpc Capabilities(Empty)        returns (CapabilitySet);        // protocols/transports/tls_modes supported
  rpc Reconcile(DesiredState)    returns (ReconcileResult);      // idempotent: make local engine match
  rpc StreamStats(Empty)         returns (stream UsageDelta);    // per-user byte counters, pushed
  rpc HealthCheck(Empty)         returns (HealthStatus);
}
message DesiredState { repeated InboundSpec inbounds = 1; }       // engine-agnostic: protocol, transport,
                                                                  // tls_mode, listen, users[]
```

- `CapabilitySet` lets each node self-declare (`vless/reality/xhttp` for an Xray node; `atlas/1` +
  carriers for an Atlas node). The control plane only schedules an `InboundTemplate` onto a node whose
  capabilities satisfy it. **Adding Atlas = writing one adapter**; nothing in the control plane,
  subscription service, data model, billing, or reseller logic changes.
- **Xray adapter** = a thin wrapper translating `InboundSpec` → Xray inbound/streamSettings JSON,
  reconciled either via the node-local xray (endgame) or, during migration, via the **existing 3x-ui
  HTTP API** (wrap today's `XUIClient` verbatim so nothing breaks on day one).
- **Atlas adapter** = translates `InboundSpec` → the Atlas server's config (authorized pubkeys, carriers,
  SNIs, quotas) and, crucially, applies **per-user changes hot** ([03](03-atlas-protocol-spec.md) §10).

### 5.2 `UsageDelta` is uniform
`{user_id, up_bytes, down_bytes}` looks identical whether it came from Xray's Stats API, 3x-ui's bulk
`clientStats`, or an Atlas counter — so quota enforcement, resets, reseller billing, and the IP-guard are
written once and never per-engine.

### 5.3 Migration path (no big-bang)
1. Wrap the current `XUIClient` as the **Xray-over-3x-ui adapter** behind the new interface. Behavior
   identical; the control plane now talks "adapter," not "3x-ui."
2. Stand up the **node agent** on the nodes we control by SSH, first as a thin gRPC front over that same
   Xray adapter (still driving 3x-ui or the local xray). Now we own the control channel.
3. Add the **Atlas adapter** on one node; run Atlas beside Xray. Serve Atlas to a pilot cohort via the
   subscription descriptor while everyone else stays on Xray/REALITY.
4. As Atlas proves out, retire 3x-ui per node. The panel never noticed which engine was underneath.

## 6. Subscription & clients

- Existing clients (v2rayNG, Streisand, Hiddify, sing-box, Clash) are served exactly as today — the
  service content-negotiates by `User-Agent` (base64 / Clash YAML / sing-box JSON). **No change for the
  current customer base.**
- Atlas gets a **signed JSON descriptor** (carriers, endpoints, SNIs, server static key, rendezvous
  mirrors) consumed by the Atlas client ([03](03-atlas-protocol-spec.md) §10). Because Atlas has no
  existing client ecosystem, the client is either a **sing-box-compatible outbound** or a **thin custom
  client** — decided in [05](05-build-roadmap.md).

## 7. Security posture

- **mTLS per node**, capability-negotiated: a compromised or leased-out node can't impersonate another
  or pull the user table — it only ever receives the `DesiredState` for inbounds explicitly scheduled
  onto it (Marzban/Marzneshin precedent). This is strictly better than today, where each node is a full
  3x-ui with the whole client list and a bcrypt login.
- The control plane keeps the hardening already built (login guard, `client_ip()` trust boundary, JWT
  cred-versioning — [PROJECT_MAP](../../PROJECT_MAP.md) §4b) and the reseller-API idempotency/serialization.
- Node agent holds **no billing logic** and minimal secrets (its own cert + the pubkeys/quotas for its
  own inbounds).

---

## Appendix — prior-art reference (condensed)

**3x-ui** (Go; SQLite default, Postgres optional): models an **Inbound** (protocol + `settings` /
`streamSettings` / `sniffing` JSON) owning an array of **Clients** (uuid/password + `email` accounting
key); embeds xray-core as a **Go library** and reloads it in-process on change; built-in subscription
server auto-selects base64 / JSON / Clash by `User-Agent`; per-client traffic from xray's Stats API;
Bearer-token REST API (Swagger at `/panel/api-docs`). Lineage: `vaxilu/x-ui` → `alireza0/x-ui` →
`MHSanaei/3x-ui`.

**Xray-core config model** every panel generates: top-level `{log, api, dns, routing, policy, inbounds,
outbounds, stats, …}`; inbounds/outbounds are `{tag, protocol, settings, streamSettings, sniffing?}`;
`security ∈ {none, tls, reality}`; transports `tcp/raw, ws, grpc, httpupgrade, xhttp, kcp`; REALITY only
rides `raw/xhttp/grpc` (not ws/httpupgrade — those sit behind a CDN's own TLS). Routing rules match
domain/geosite/geoip/port/network/inboundTag/user → outboundTag, which is what "ad-block / bypass-Iran"
toggles compile to.

**Subscription formats:** base64 line-list of `vless://`/`vmess://`/`trojan://`/`ss://` URIs (v2rayNG et
al.); Clash/mihomo YAML (`proxies:`/`proxy-groups:`/`rules:`); sing-box JSON outbounds; raw Xray JSON.
De-facto content negotiation is by `User-Agent`, not `Accept`.

**Multi-node:** Marzban = FastAPI + React, SQLAlchemy, panel ⇄ `marzban-node` over RPyC/REST + mTLS,
**push-everything single-source-of-truth**, panel sums per-node usage against one quota. Marzneshin =
scalability rewrite, `marznode` over **gRPC**, **backend-decoupled** (xray/sing-box/hysteria). 3x-ui has
no node agent, no cross-node identity, no aggregation — the exact gap this design closes natively.

Sources: [MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui) · [XTLS/Xray-core](https://github.com/XTLS/Xray-core) · [Config docs](https://xtls.github.io/en/config/) · [Gozargah/Marzban](https://github.com/Gozargah/Marzban) · [marzban-node](https://github.com/Gozargah/Marzban-node) · [marzneshin](https://github.com/marzneshin/marzneshin) · [marznode](https://github.com/marzneshin/marznode) · [Hiddify-Manager](https://github.com/hiddify/Hiddify-Manager) · [sing-box config](https://sing-box.sagernet.org/configuration/) · [mihomo VLESS](https://wiki.metacubex.one/config/proxies/vless/)

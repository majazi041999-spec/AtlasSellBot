# Iran to Turkey tunnel research — 2026-10-15

Scope: an additional Iran entry for the owned Turkey VLESS service, with existing subscriber quota and expiry preserved. This note is primary-source research plus explicitly identified engineering judgments. No deployment, SSH, scanning, or traffic tests were performed by this research task.

## Recommended first candidate

**Test an isolated HAProxy TCP passthrough in Iran to Turkey's reachable HTTPS port, with an exact WS location in Turkey nginx forwarding to the existing Turkey Xray inbound.** The coordinating agent's read-only tests found TCP attempts from Iran to Turkey's WS port 2096 timing out, while Turkey port 443 completed TCP and verified TLS. Its existing HTTP root timed out; a TLS handshake alone does not prove the proposed service works. HAProxy is already installed in Iran, according to that audit.

Proposed path: customer → Iran:2053 TCP relay → Turkey:443 TLS/WS → Turkey loopback:2096 existing TLS/WS inbound → Internet. The subscription connects to the Iran hostname but uses Turkey's HTTPS certificate name for SNI, its WS Host, and the new exact path. The relay adds no shared stream across customers and keeps TLS keys and termination in Turkey. This is a fixed relay initiated from Iran, not a conventional reverse-tunnel daemon. This architecture was subsequently deployed as a private trial; the observations below do not establish production capacity.

HAProxy implementation points:

- Use `mode tcp`, one fixed backend destination, and no `ssl` on the frontend bind or backend server. The client verifies Turkey's certificate; HAProxy passes the original TLS bytes.
- Set finite `timeout connect`, consistent client/server inactivity allowances, and deliberate `timeout tunnel` if used. Check the installed version's semantics. `option tcpka` enables keepalive on both TCP legs; it is not an application health check.
- Bound aggregate `maxconn` against measured capacity and file descriptors. Excess frontend connections queue; an undersized limit creates latency. Basic TCP health checks prove only connectivity, so retain an authenticated end-to-end test.

These controls are documented in the [HAProxy configuration manual](https://docs.haproxy.org/3.2/configuration.html#4.2-mode).

Turkey nginx requirements:

- Exact WS location and fixed proxy destination/path/Host; no user-selected upstream. VLESS authentication remains in the existing Xray inbound. The WS path alone is not authentication.
- Explicit HTTP/1.1 and forwarded `Upgrade`/`Connection`. WS upgrades create dedicated bidirectional tunnels. Its default closes a connection after 60 seconds without upstream data: choose a longer explicit inactivity timeout or proven WS pings and test idle recovery. [nginx WebSocket proxying](https://nginx.org/en/docs/http/websocket.html)
- When proxying HTTPS to loopback:2096, enable `proxy_ssl_verify`, configure the CA bundle, enable `proxy_ssl_server_name`, and set `proxy_ssl_name` to the existing WS certificate hostname. In the deployed trial this is `atlas.anacotig.com`; the WS Host remains `trws.anacotig.com` with upstream path `/perfix/`. These names are deliberately different. Verification and SNI default off. Disable response buffering for this location. [nginx proxy directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)

Original customer IP is lost at the relays; Turkey sees relay/loopback addresses. User UUID accounting survives, but IP-based limits and online-IP displays can change. Do not inject PROXY headers into an unchanged TLS listener unless receiver support is explicitly configured and tested. A small per-IP cap also penalizes unrelated mobile users sharing NAT. Prefer capacity-based aggregate bounds and measured, generous per-source limits. [HAProxy PROXY protocol](https://www.haproxy.com/documentation/haproxy-configuration-tutorials/proxying-essentials/client-ip-preservation/enable-proxy-protocol/), [nginx connection limits](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html)

If direct Turkey WS becomes reachable, a fixed TCP relay directly to that port is simpler. An Iran nginx TLS/WS relay is another option, but it terminates TLS in Iran; that adds an Iran plaintext trust boundary and TLS work. [nginx stream proxy](https://nginx.org/en/docs/stream/ngx_stream_proxy_module.html)

## Other practical candidates

| Method | Connection direction and exposure | Concurrency and suitability |
| --- | --- | --- |
| SSH local forwarding | Iran initiates SSH to Turkey; `-L` exposes the Iran listener and forwards to a fixed Turkey service. Turkey exposes SSH, Iran exposes only the customer listener. | Simple baseline. Forwarded channels share an SSH connection, creating cross-channel loss coupling. Separate processes can distribute that coupling, with more operational overhead. Restrict the tunnel key/account to the destination using `PermitOpen`; add supervision and encrypted keepalives. [OpenSSH forwarding](https://man.openbsd.org/ssh.1#L), [channel specification](https://datatracker.ietf.org/doc/html/rfc4254#section-5), [restrictions](https://man.openbsd.org/sshd_config#PermitOpen), [keepalives](https://man.openbsd.org/ssh_config#ServerAliveInterval) |
| WireGuard | Iran initiates UDP to Turkey; forward only the required service across a private tunnel. Keep default routing unchanged. | Good performance candidate if this specific datacenter path carries UDP reliably; no outer reliable TCP stream. WireGuard does not obfuscate its protocol. Keepalive can retain NAT state, not repair filtering. Test MTU and idle recovery. [protocol](https://www.wireguard.com/protocol/), [limitations](https://www.wireguard.com/known-limitations/), [keepalive](https://www.wireguard.com/quickstart/) |
| frp over verified TLS/TCP | Conventional frp with its public listener in Iran requires Turkey's client to connect to Iran. For Iran-initiated traffic, place an STCP visitor in Iran and both frps and the STCP service provider in Turkey. | Configurable TCP multiplexing and connection pooling; compare mux on/off under load. Multiplexing saves setup/resource costs but shares loss stalls. Extra components are difficult to justify if the fixed relay already works. TLS encryption defaults do not establish server identity: configure verification. [STCP roles](https://gofrp.org/en/docs/examples/stcp/), [mux/pooling](https://gofrp.org/en/docs/features/common/network/network/), [TLS](https://gofrp.org/en/docs/features/common/network/network-tls/) |
| rathole over TLS | Its ordinary topology exposes the customer listener on the server, hence Iran server and Turkey client for this service direction. This depends on Turkey-to-Iran reachability. Reversing those roles publishes an Iran service in Turkey instead. | v0.5.0 creates separate TCP data connections, rather than one shared multiplexed data stream. More handshakes/descriptors; reduced cross-flow TCP coupling. The project's benchmark is local-loopback evidence, not an Iran speed prediction. [topology/benchmark caveat](https://github.com/rathole-org/rathole), [versioned data-channel code](https://github.com/rathole-org/rathole/blob/v0.5.0/src/client.rs) |

frp also supports QUIC. If UDP proves usable and TCP mux suffers, QUIC is an optional comparison: independent streams avoid connection-wide delivery blocking, although congestion remains shared. It is not an answer to a blocked UDP path. [frp transports](https://gofrp.org/en/docs/reference/client-configures/), [QUIC stream behavior](https://datatracker.ietf.org/doc/html/rfc9000#section-13)

**TCP-over-TCP terminology matters.** Forwarding TCP application bytes through SSH/frp/HAProxy/nginx terminates and recreates sockets; it does not necessarily encapsulate complete TCP packets with nested retransmission timers. Nevertheless, an ordered outer TCP stream can stall every multiplexed logical stream on loss. A TCP-based IP tunnel has the additional classic nested-TCP problem. These are different failure mechanisms. [TCP ordering](https://datatracker.ietf.org/doc/html/rfc9293#section-2.2), [WireGuard TCP limitation](https://www.wireguard.com/known-limitations/)

## Preserve one accounting authority

Keep subscriber authentication and usage measurement at the existing Turkey Xray inbound. Xray user counters are keyed by email, require the corresponding policy settings, and expose uplink/downlink bytes. Relay or tunnel interface totals aggregate users and include different protocol overhead; they are unsuitable as subscriber quota counters. [Xray statistics](https://xtls.github.io/en/config/stats.html), [policy](https://xtls.github.io/en/config/policy.html)

Treat the Iran entry as a transport variant of the same parent customer record. Do not provision a second entitlement or add the same Turkey counter again when aggregating variants. Keep UUID, email, expiry, remaining quota, unlimited semantics, and renewal behavior unchanged. Record the Iran relay dependency so disabling Iran hides this variant without hiding the direct Turkey entry. This follows the repository's [variant contract](subscription-server-state.md), [renewal contract](RENEWAL_REP_ACCOUNTING.md), and [existing relay dependency precedent](transport-trials-20261005.md).

Quota/expiry enforcement belongs to the panel/control plane, not the tunnel binary. Validate both new connections and already-open transfers at exhaustion/expiry; polling delay and active-session behavior depend on the installed versions. Upstream 3x-ui lists quotas/expiry but explicitly describes itself as personal-use software, so its feature list alone is not production assurance. [3x-ui upstream](https://github.com/MHSanaei/3x-ui)

## Private trial observations — 2026-10-15

The coordinating agent deployed and tested Iran HAProxy:2053 → Turkey:443 → Turkey loopback:2096. Client TLS verified `atlasapp.anacotig.com`; the loopback TLS leg separately verified `atlas.anacotig.com`. Valid VLESS connections succeeded and the observed exit matched the owned Turkey server. No TLS keys were placed on the Iran relay.

| Laptop trial | Observed result |
| --- | --- |
| Three downloads, 8 MiB each | 21.75–27.56 Mbps |
| Three uploads, 2 MiB each | 3.91–4.04 Mbps |
| Four simultaneous downloads, 1 MiB each | All completed |
| Invalid UUID | Denied |
| Expired trial account | Disabled and denied |

These are bounded application-transfer observations, not maximum capacity, packet-loss measurements, or coverage of every Iranian ISP. Long-running session expiry behavior is not established by a denied new connection. The subsequent [deployment record](turkey-iran-tunnel-20261015.md) covers quota exhaustion, idle recovery, additional measurements and publication controls.

## Further tests and unresolved facts

1. Continue validating independent user counters and shared quota across direct/relay entry. Quota exhaustion and denied new connections passed in the subsequent deployment tests, with the existing panel's polling delay. Check ongoing-session enforcement and renewal without counter duplication. Do not reset real subscriber counters for validation.
2. Compare direct Turkey with the relay in supported apps and intended Iranian mobile/fixed networks at multiple times. Verify imports preserve connection address, TLS name, WS Host and path. Test idle recovery beyond 60 seconds and reconnection after a controlled relay restart.
3. Extend bounded concurrency and soak tests, including interactive requests during bulk transfers. Record median/tail latency, failures, CPU, memory and sockets. If failure occurs, isolate client→Iran, Iran→Turkey, and Turkey→destination before adding another tunnel method.

No method guarantees prevention of “Iran-access” or future IP/ASN restriction. An Iran-initiated path removes dependence on unsolicited foreign inbound connections; replies still must traverse the cross-border path. TLS, changing port, multiplexing or a quiet daemon does not prove resistance to filtering. The coordinating agent reports foreign inbound HTTPS impairment predating this work; that is baseline evidence, not proof of cause. Keep separate timestamps for domestic reachability, outbound reachability and external management, with provider console recovery available. Protocol documentation cannot establish today's carrier-specific filtering or long-term availability.

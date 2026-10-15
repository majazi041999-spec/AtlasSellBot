"""Attribute shared-account relay users without inventing per-variant counts.

Only configured, unique ingress source IPs identify a relay. UUIDs, source IPs
and client emails are never persisted in this dashboard sample. Other variants
sharing the same account/ingress remain explicitly grouped.
"""
import ipaddress
import re

from core.subscription_variants import describe_variants

_SUFFIX = re.compile(r"_n(\d+)$")


def relay_observers(configs, options, server_id):
    result = {}
    for node in configs:
        if int(node.get('server_id') or 0) != server_id:
            continue
        target = f"{server_id}:{node.get('inbound_id')}"
        relay = options.get('subscription_ws_relays', {}).get(target, {})
        if not isinstance(relay, dict):
            continue
        sources = relay.get('source_ips')
        if not isinstance(sources, list) or not sources:
            continue
        try:
            ips = {str(ipaddress.ip_address(ip)) for ip in sources}
        except (ValueError, TypeError):
            continue
        result[str(node['id'])] = dict(ips=ips, label=relay.get('label') or 'Plus')
    return result


def sample_routes(emails, ip_map, observers, now_s, max_age=90):
    """One user may use both routes. Missing/old sightings mean unknown, not 0."""
    out = {cid: dict(label=spec['label'], relay=0, other=0, unknown=0, overlap=0)
           for cid, spec in observers.items()}
    for email in set(emails or []):
        match = _SUFFIX.search(email)
        cid = match.group(1) if match else None
        if cid not in out:
            continue
        fresh = set()
        for ip, ts in ((ip_map or {}).get(email) or {}).items():
            try:
                if 0 <= now_s - float(ts) <= max_age:
                    fresh.add(str(ipaddress.ip_address(ip)))
            except (ValueError, TypeError):
                continue
        bucket = out[cid]
        if not fresh:
            bucket['unknown'] += 1
            continue
        relay = bool(fresh & observers[cid]['ips'])
        other = bool(fresh - observers[cid]['ips'])
        bucket['relay'] += int(relay)
        bucket['other'] += int(other)
        bucket['overlap'] += int(relay and other)
    return out


def dashboard_nodes(split, configs, server_id, options, routes=None):
    if split is None:
        return None
    configs = {int(n['id']): n for n in configs}
    counts = {str(k): int(v) for k, v in split.items()}
    for cid, node in configs.items():
        if int(node.get('server_id') or 0) == server_id and node.get('is_active'):
            counts.setdefault(str(cid), 0)
    rows, other = [], 0
    for key, count in counts.items():
        if not key.isdigit():
            other += count
            continue
        cid = int(key)
        node = configs.get(cid, {})
        target = f"{server_id}:{node.get('inbound_id')}"
        label = (node.get('label') or '').strip() or f'نود #{cid}' + (' (حذف‌شده)' if not node else '')
        row = dict(id=cid, label=label, online=count, is_active=bool(int(node.get('is_active') or 0)))
        variants = describe_variants(options, target)
        relay = next((v for v in variants if v['id'] == 'relay'), None)
        if len(variants) > 1:
            row['shared'] = True
        if relay:
            sample = (routes or {}).get(key)
            unknown = sample['unknown'] if sample else count
            row['unattributed'] = unknown
            row['overlap'] = sample['overlap'] if sample else 0
            row['routes'] = [
                dict(id='relay', label=relay['label'], is_active=row['is_active'] and relay['is_active'],
                     online=(sample['relay'] if sample else 0) if not unknown else None,
                     observed=sample['relay'] if sample else 0),
                dict(id='other', label='مسیرهای دیگر همین نود',
                     online=(sample['other'] if sample else 0) if not unknown else None,
                     observed=sample['other'] if sample else 0),
            ]
        rows.append(row)
    if other:
        rows.append(dict(id=None, label='سایر (کانفیگ تکی)', online=other))
    rows.sort(key=lambda row: (-row['online'], row['label']))
    return rows

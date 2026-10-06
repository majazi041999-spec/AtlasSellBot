"""Client transport tuning applied at render time, independent of panel sync."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

VERIFIED_ECH_LOOKUPS = {'trws.anacotig.com', 'blogfa.com', 'www.tgju.org', 'mihanblockchain.com'}
VERIFIED_EDGE_DOMAINS = {'www.technolife.com', 'virgool.io', 'ok-ex.io', 'mihanblockchain.com'}


def apply_ws_tls_frontend(link: str, options) -> str:
    """Export the public TLS endpoint of a WS inbound behind a reverse proxy.

    An explicitly configured but invalid frontend is omitted, never published
    as a plaintext/internal endpoint. Identity, WS path and label are retained.
    """
    if not isinstance(options, dict):
        return ''
    port, host = options.get('port'), options.get('server_name')
    if (type(port) is not int or not 1 <= port <= 65535 or not isinstance(host,str)
            or len(host)>253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label)
                                       for label in host.split('.'))):
        return ''
    try:
        parts=urlsplit(link)
        query=parse_qsl(parts.query,keep_blank_values=True)
        values=dict(query)
        if (parts.scheme!='vless' or values.get('type')!='ws' or values.get('security')!='none'
                or not parts.username or not parts.hostname or not values.get('path')):
            return ''
        address=parts.hostname
        if ':' in address:address='['+address+']'
        changed={'security':'tls','sni':host,'host':host,'fp':'chrome','alpn':'http/1.1'}
        query=[(k,v) for k,v in query if k not in changed]+list(changed.items())
        return urlunsplit(parts._replace(netloc=f'{parts.username}@{address}:{port}',query=urlencode(query)))
    except (TypeError,ValueError):
        return ''


def apply_ws_backup(link: str, options) -> str:
    """Add only tested shared-edge variants while preserving origin identity."""
    if not isinstance(options, dict) or not isinstance(options.get('address'), str):
        return link
    if options['address'] not in VERIFIED_EDGE_DOMAINS:
        return link
    if not isinstance(options.get('no_ed', False), bool):
        return link
    try:
        parts = urlsplit(link)
        values = dict(parse_qsl(parts.query, keep_blank_values=True))
        if parts.scheme != 'vless' or values.get('type') != 'ws' or values.get('security') != 'tls':
            return link
        if not parts.username or not parts.port:
            return link
        candidate = urlunsplit(parts._replace(netloc=f"{parts.username}@{options['address']}:{parts.port}"))
        if options.get('no_ed'):
            candidate = without_ws_early_data(candidate)
        ech = options.get('ech', '')
        if not isinstance(ech, str):
            return link
        if ech:
            candidate = apply_ws_ech(candidate, ech)
            if dict(parse_qsl(urlsplit(candidate).query)).get('ech') != ech:
                return link
        return candidate
    except (TypeError, ValueError):
        return link


def without_ws_early_data(link: str) -> str:
    """Drop only WS early data on an additional operator-specific variant."""
    try:
        parts = urlsplit(link)
        query = parse_qsl(parts.query, keep_blank_values=True)
        values = dict(query)
        if parts.scheme != 'vless' or values.get('type') != 'ws' or values.get('security') != 'tls':
            return link
        path = urlsplit(values.get('path') or '/')
        parameters = parse_qsl(path.query, keep_blank_values=True)
        if not any(k == 'ed' for k, _ in parameters):
            return link
        path = urlunsplit(path._replace(query=urlencode([(k, v) for k, v in parameters if k != 'ed'])))
        query = [(k, v) for k, v in query if k != 'path'] + [('path', path)]
        return urlunsplit(parts._replace(query=urlencode(query)))
    except (TypeError, ValueError):
        return link


def apply_ws_ech(link: str, ech_config) -> str:
    """Create an opt-in WS/TLS variant with automatically refreshed ECH keys."""
    if not isinstance(ech_config, str) or any(c.isspace() for c in ech_config):
        return link
    try:
        lookup, separator, doh_url = ech_config.partition('+')
        # These are the two verified DoH endpoints. Keep resolver credentials
        # and arbitrary HTTP destinations out of subscription settings.
        if separator != '+' or lookup not in VERIFIED_ECH_LOOKUPS or doh_url not in (
            'https://8.8.8.8/dns-query', 'https://8.8.4.4/dns-query'
        ):
            return link
        parts = urlsplit(link)
        query = parse_qsl(parts.query, keep_blank_values=True)
        values = dict(query)
        if parts.scheme != 'vless' or values.get('type') != 'ws' or values.get('security') != 'tls':
            return link
        query = [(k, v) for k, v in query if k != 'ech'] + [('ech', ech_config)]
        return urlunsplit(parts._replace(query=urlencode(query)))
    except (TypeError, ValueError):
        return link


def apply_ws_early_data(link: str, early_data) -> str:
    """Opt a VLESS WS/TLS link into early data without changing its identity."""
    if isinstance(early_data, bool) or not isinstance(early_data, (int, str)):
        return link
    try:
        threshold = int(early_data)
        parts = urlsplit(link)
        query = parse_qsl(parts.query, keep_blank_values=True)
        values = dict(query)
        if not 1 <= threshold <= 8192 or parts.scheme != 'vless':
            return link
        if values.get('type') != 'ws' or values.get('security') != 'tls':
            return link
        path = urlsplit(values.get('path') or '/')
        path_query = [(k, v) for k, v in parse_qsl(path.query, keep_blank_values=True) if k != 'ed']
        path_query.append(('ed', str(threshold)))
        tuned_path = urlunsplit(path._replace(query=urlencode(path_query)))
        query = [(k, v) for k, v in query if k != 'path'] + [('path', tuned_path)]
        return urlunsplit(parts._replace(query=urlencode(query)))
    except (TypeError, ValueError):
        return link

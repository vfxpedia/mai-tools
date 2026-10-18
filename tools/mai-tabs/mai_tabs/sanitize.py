"""URL sanitizer. Behaviorally identical to extension/export.js (tests/test_conformance.py runs both on the same cases).

Removes userinfo, query and fragment. Output is at most scheme, host, port (when not the scheme default) and path.
"""
import re
from urllib.parse import quote, urlsplit

HIERARCHICAL = {'http': 80, 'https': 443, 'ftp': 21, 'ws': 80, 'wss': 443}
BROWSER_INTERNAL = ('chrome', 'chrome-extension', 'edge', 'brave', 'vivaldi', 'opera', 'moz-extension')
REDACTED = '_redacted_'
SEGMENT_RE = re.compile('^[A-Za-z0-9_-]+$')
PATH_SAFE = "/%:@!$&'()*+,;=~-._[]|^"


def redact_segment(seg):
    if len(seg) >= 32 and SEGMENT_RE.match(seg) and any(c.isdigit() for c in seg) and any(c.isalpha() for c in seg):
        return REDACTED
    return seg


def clean_path(path, redact):
    if not redact:
        return path
    return '/'.join(redact_segment(s) for s in path.split('/'))


def sanitize_url(url, redact_long_segments=True):
    s = str(url)
    try:
        u = urlsplit(s)
        scheme = u.scheme.lower()
        if not scheme:
            return ''
        if scheme in HIERARCHICAL:
            if not u.netloc:
                return ''
            host = u.hostname or ''
            if ':' in host:
                host = '[' + host + ']'
            port = u.port
            port_s = ':%d' % port if port is not None and port != HIERARCHICAL[scheme] else ''
            path = quote(u.path, safe=PATH_SAFE) or '/'
            return '%s://%s%s%s' % (scheme, host, port_s, clean_path(path, redact_long_segments))
        if scheme == 'file':
            return 'file:///.../' + quote(u.path, safe=PATH_SAFE).split('/')[-1]
        if scheme in BROWSER_INTERNAL:
            host = u.netloc.rsplit('@', 1)[-1].split(':')[0] if u.netloc else ''
            return '%s://%s%s' % (scheme, host, quote(u.path, safe=PATH_SAFE))
        if scheme == 'about':
            return 'about:' + u.path
        return scheme + ':'
    except ValueError:
        return ''

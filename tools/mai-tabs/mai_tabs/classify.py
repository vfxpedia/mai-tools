"""Rule-based classification. Categories and rules are configuration (rules file), not code. No model call.

Rules file (mai-tabs-rules-v1):
  {"schema": "mai-tabs-rules-v1", "default": "uncategorized",
   "categories": [{"name": "dev", "match": [{"host": "github.com"}, {"host_suffix": ".github.io"}, {"url_prefix": "https://x/y"}, {"title_contains": "pull request"}]}]}
Categories are tried in file order, and the first category with any matching rule wins.
"""
import json
from urllib.parse import urlsplit

KEYS = ('host', 'host_suffix', 'url_prefix', 'title_contains')


class RulesError(Exception):
    pass


def load_rules(path):
    with open(path, encoding='utf-8') as f:
        return check_rules(json.load(f))


def check_rules(rules):
    if not isinstance(rules, dict) or rules.get('schema') != 'mai-tabs-rules-v1':
        raise RulesError('rules file must declare schema mai-tabs-rules-v1')
    cats = rules.get('categories')
    if not isinstance(cats, list) or not cats:
        raise RulesError('categories must be a non-empty list')
    seen = set()
    for c in cats:
        if not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name'].strip():
            raise RulesError('every category needs a non-empty name')
        if c['name'] in seen:
            raise RulesError('duplicate category name: %s' % c['name'])
        seen.add(c['name'])
        m = c.get('match')
        if not isinstance(m, list) or not m:
            raise RulesError('category %s needs a non-empty match list' % c['name'])
        for r in m:
            if not (isinstance(r, dict) and len(r) == 1 and next(iter(r)) in KEYS and isinstance(next(iter(r.values())), str) and next(iter(r.values()))):
                raise RulesError('category %s has a rule that is not exactly one of %s with a non-empty string' % (c['name'], ', '.join(KEYS)))
    if not isinstance(rules.get('default', 'uncategorized'), str):
        raise RulesError('default must be a string')
    return rules


def _host(url):
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


def _rule_matches(rule, url, title):
    (k, v), = rule.items()
    if k == 'host':
        return _host(url) == v.lower()
    if k == 'host_suffix':
        return _host(url).endswith(v.lower())
    if k == 'url_prefix':
        return url.startswith(v)
    return v.lower() in (title or '').lower()


def classify(rules, url, title):
    for c in rules['categories']:
        if any(_rule_matches(r, url, title) for r in c['match']):
            return c['name']
    return rules.get('default', 'uncategorized')

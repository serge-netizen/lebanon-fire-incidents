from crawler.fetch import parse_robots, robots_allows

NNA = """User-Agent: *
Allow: /
Disallow: /api/
Disallow: /admin/
"""

GOOGLE_NEWS = """User-agent: *
Disallow: /
Allow: /$
Allow: /topics/

User-agent: ClaudeBot
Disallow: /
"""


def test_longest_rule_wins_not_the_first():
    rules = parse_robots(NNA)
    assert robots_allows(rules, "/ar/sitemap/n/1?date=2026-10-20")
    assert not robots_allows(rules, "/api/news")  # Python's robotparser gets this one wrong


def test_star_group_only_and_end_anchor():
    rules = parse_robots(GOOGLE_NEWS)
    assert not robots_allows(rules, "/rss/search?q=fire")
    assert robots_allows(rules, "/")
    assert not robots_allows(rules, "/home2")
    assert robots_allows(rules, "/topics/abc")


def test_no_rules_means_allowed():
    assert robots_allows([], "/anything")
    assert robots_allows(parse_robots("User-agent: *\nDisallow:\n"), "/anything")

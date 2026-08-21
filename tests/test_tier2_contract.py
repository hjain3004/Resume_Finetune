"""M9F-0 defect 7: exactly one canonical Tier2Page/Tier2Client definition.

The tree previously carried three copies (src/resolve/base.py,
src/resolve/tier2.py, src/firecrawl/client.py) plus a placeholder PoliteSession
in tier2.py. Duplicate structural types silently pass isinstance-free Protocol
checks while diverging field by field, so this pins the single definition.
"""

import src.firecrawl.client as fc_client
import src.resolve.base as resolve_base
import src.resolve.browser as browser
import src.resolve.tier2 as tier2


def test_canonical_types_live_in_resolve_tier2():
    assert tier2.Tier2Page.__module__ == "src.resolve.tier2"
    assert tier2.Tier2Client.__module__ == "src.resolve.tier2"


def test_browser_uses_the_canonical_page_type():
    assert browser.Tier2Page is tier2.Tier2Page
    assert browser.Tier2Client is tier2.Tier2Client


def test_firecrawl_client_uses_the_canonical_page_type():
    assert fc_client.Tier2Page is tier2.Tier2Page
    assert fc_client.Tier2Client is tier2.Tier2Client


def test_resolve_base_no_longer_defines_a_duplicate():
    """base.py owns PoliteSession and html_to_text, not the tier-2 contract."""
    for name in ("Tier2Page", "Tier2Client"):
        if hasattr(resolve_base, name):
            assert getattr(resolve_base, name) is getattr(tier2, name)


def test_tier2_has_no_placeholder_polite_session():
    assert not hasattr(tier2, "PoliteSession")


def test_polite_session_has_exactly_one_definition():
    assert resolve_base.PoliteSession.__module__ == "src.resolve.base"

"""Unit tests for :func:`render_email_template`.

Assertions are done against the raw rendered string via :mod:`re` —
emails have no live DOM, so ``data-testid`` attributes survive as
literal substrings in the markup. That's enough for Gmail / Outlook
compatibility regression: if a marker disappears, the test fails.
"""

from __future__ import annotations

import re

from iguanatrader.shared.channel_dispatch import render_email_template

_BODY_HTML = "<p>Please review the proposal and confirm.</p>"
_KWARGS = {
    "subject": "[iguanatrader] Approve trade",
    "preheader": "Trade approval needed",
    "headline": "Approve trade proposal",
    "body_html": _BODY_HTML,
}


def test_template_contains_all_data_testid_markers() -> None:
    """Every required ``data-testid`` marker is present in the rendered HTML."""
    html, _ = render_email_template(
        **_KWARGS, cta_label="Open dashboard", cta_url="https://iguanatrader.palafitofood.com/"
    )
    for marker in ("brand-mark", "headline", "body", "disclaimer", "preheader", "cta"):
        assert f'data-testid="{marker}"' in html, f"missing data-testid={marker}"


def test_template_omits_cta_marker_when_not_provided() -> None:
    """The CTA marker is absent when ``cta_label``/``cta_url`` aren't passed."""
    html, _ = render_email_template(**_KWARGS)
    assert 'data-testid="cta"' not in html
    # But the other markers are still all there.
    for marker in ("brand-mark", "headline", "body", "disclaimer"):
        assert f'data-testid="{marker}"' in html


def test_disclaimer_contains_sender_address_in_both_languages() -> None:
    """The no-reply disclaimer surfaces the sender + support URL in ES + EN."""
    html, plain_text = render_email_template(**_KWARGS)
    assert "iguanatrader@palafitofood.com" in html
    assert "https://iguanatrader.palafitofood.com" in html
    # Spanish wording.
    assert "no recibe respuestas" in html
    # English wording.
    assert "does not accept replies" in html
    # The plain text alternative carries the disclaimer too — text-only
    # mail clients still see the no-reply notice.
    assert "iguanatrader@palafitofood.com" in plain_text
    assert "no recibe respuestas" in plain_text
    assert "does not accept replies" in plain_text


def test_template_has_no_style_blocks() -> None:
    """Gmail strips ``<style>``; all CSS must be inline on each element."""
    html, _ = render_email_template(
        **_KWARGS, cta_label="Open", cta_url="https://iguanatrader.palafitofood.com/"
    )
    # Case-insensitive search for ``<style`` to catch ``<STYLE>`` variants.
    assert not re.search(
        r"<style\b", html, flags=re.IGNORECASE
    ), "<style> blocks are not allowed — Gmail strips them. Inline every CSS rule."
    # And every visible cell carries at least one inline style attribute.
    assert 'style="' in html


def test_plain_text_fallback_from_paragraph_body() -> None:
    """``body_html`` containing only a ``<p>`` collapses to its text content."""
    _, plain_text = render_email_template(
        subject="[iguanatrader] hello",
        preheader="just saying hi",
        headline="Hello",
        body_html="<p>Hello there, friend.</p>",
    )
    # The headline appears at the top of the plain text.
    assert plain_text.startswith("Hello")
    # The body is present verbatim, tags stripped.
    assert "Hello there, friend." in plain_text
    assert "<p>" not in plain_text and "</p>" not in plain_text


def test_plain_text_includes_cta_when_provided() -> None:
    """``cta_label: cta_url`` is appended to the plain text fallback."""
    _, plain_text = render_email_template(
        **_KWARGS,
        cta_label="Open dashboard",
        cta_url="https://iguanatrader.palafitofood.com/proposals",
    )
    assert "Open dashboard: https://iguanatrader.palafitofood.com/proposals" in plain_text


def test_template_uses_brand_accent_color() -> None:
    """The accent teal ``#11b9c5`` is used on the brand mark + CTA + links."""
    html, _ = render_email_template(
        **_KWARGS, cta_label="Open", cta_url="https://iguanatrader.palafitofood.com/"
    )
    # The accent colour appears (background of brand mark + CTA + link colour).
    assert html.lower().count("#11b9c5") >= 2

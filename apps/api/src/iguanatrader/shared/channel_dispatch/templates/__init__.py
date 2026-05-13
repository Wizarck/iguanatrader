"""Branded email template rendering helpers.

Renders ``email_base.html`` (Jinja, all CSS inline) and derives a plain-text
fallback by stripping HTML tags via :mod:`html.parser` (stdlib — no extra
dependency on bleach / beautifulsoup).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR: Path = Path(__file__).resolve().parent
_TEMPLATE_NAME: str = "email_base.html"

_jinja_env: Environment = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html",)),
    keep_trailing_newline=False,
    trim_blocks=False,
    lstrip_blocks=False,
)


class _PlainTextExtractor(HTMLParser):
    """Strip tags from an HTML fragment, preserving block boundaries.

    Each block-level element produces a newline so list items / paragraphs /
    line breaks do not collapse together. ``data-testid`` and other
    attributes are ignored — only character content is captured.
    """

    _BLOCK_TAGS = frozenset(
        {
            "p",
            "div",
            "section",
            "article",
            "header",
            "footer",
            "br",
            "li",
            "tr",
            "td",
            "th",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        # Collapse runs of whitespace, then trim each line.
        lines: Iterator[str] = (re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.splitlines())
        # Drop empty lines + collapse 2+ consecutive blanks.
        compact: list[str] = []
        prev_blank = True
        for ln in lines:
            if not ln:
                if not prev_blank:
                    compact.append("")
                prev_blank = True
            else:
                compact.append(ln)
                prev_blank = False
        return "\n".join(compact).strip()


def _html_to_plain_text(html: str) -> str:
    parser = _PlainTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def render_email_template(
    *,
    subject: str,
    preheader: str,
    headline: str,
    body_html: str,
    cta_label: str | None = None,
    cta_url: str | None = None,
) -> tuple[str, str]:
    """Render the branded email template + derive a plain-text alternative.

    Returns ``(html, plain_text)``. The HTML carries all CSS inline so Gmail
    + Outlook web clients (which strip ``<style>`` blocks) preserve the
    layout. The plain text is derived from ``body_html`` plus the disclaimer
    footer so even text-only mail clients see the no-reply notice.
    """
    template = _jinja_env.get_template(_TEMPLATE_NAME)
    html = template.render(
        subject=subject,
        preheader=preheader,
        headline=headline,
        body_html=body_html,
        cta_label=cta_label,
        cta_url=cta_url,
    )
    body_text = _html_to_plain_text(body_html)
    cta_text = f"\n\n{cta_label}: {cta_url}" if cta_label and cta_url else ""
    disclaimer = (
        "Este correo se envía desde una dirección no monitorizada: "
        "iguanatrader@palafitofood.com no recibe respuestas. "
        "Para soporte, accede a la app en https://iguanatrader.palafitofood.com.\n"
        "This email is sent from an unmonitored address: "
        "iguanatrader@palafitofood.com does not accept replies. "
        "For support, visit https://iguanatrader.palafitofood.com."
    )
    plain_text = f"{headline}\n\n{body_text}{cta_text}\n\n--\n{disclaimer}".strip() + "\n"
    return html, plain_text


__all__ = ["render_email_template"]

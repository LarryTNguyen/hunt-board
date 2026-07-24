from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

from lxml import etree, html


ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
}
DROP_WITH_CONTENT = {
    "audio",
    "canvas",
    "embed",
    "form",
    "iframe",
    "math",
    "noscript",
    "object",
    "script",
    "style",
    "svg",
    "template",
    "video",
}
SAFE_LINK_SCHEMES = {"http", "https", "mailto"}
TEXT_BOUNDARY_TAGS = {
    "blockquote",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "pre",
    "ul",
}


def sanitize_html(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    try:
        root = html.fragment_fromstring(value, create_parent="div")
    except (etree.ParserError, ValueError):
        return None

    for comment in root.xpath("//comment()"):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)

    for element in list(root.iterdescendants()):
        if not isinstance(element.tag, str):
            continue
        tag = element.tag.casefold()
        if tag in DROP_WITH_CONTENT:
            element.drop_tree()
            continue
        if tag not in ALLOWED_TAGS:
            element.drop_tag()
            continue

        attributes = dict(element.attrib)
        element.attrib.clear()
        if tag == "a":
            href = attributes.get("href", "").strip()
            if _safe_link(href):
                element.set("href", href)
                title = attributes.get("title", "").strip()
                if title:
                    element.set("title", title)
                element.set("rel", "noopener noreferrer")

    serialized = (escape(root.text) if root.text else "") + "".join(
        html.tostring(child, encoding="unicode", method="html") for child in root
    )
    return serialized.strip() or None


def sanitized_description(
    description_html: str | None,
    description_text: str | None = None,
) -> tuple[str | None, str | None]:
    clean_html = sanitize_html(description_html)
    if description_text and description_text.strip():
        clean_text = html_to_text(sanitize_html(description_text))
    else:
        clean_text = html_to_text(clean_html)
    return clean_html, clean_text


def html_to_text(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    try:
        root = html.fragment_fromstring(value, create_parent="div")
        for element in root.iterdescendants():
            if isinstance(element.tag, str) and element.tag.casefold() in TEXT_BOUNDARY_TAGS:
                element.tail = f" {element.tail or ''}"
        text = root.text_content()
    except (etree.ParserError, ValueError):
        text = value
    normalized = " ".join(text.split())
    return normalized or None


def _safe_link(value: str) -> bool:
    if not value:
        return False
    try:
        return urlsplit(value).scheme.casefold() in SAFE_LINK_SCHEMES
    except ValueError:
        return False

from sovushka.safe_markup import sanitize_svg


def test_sanitize_svg_keeps_basic_diagram_markup():
    svg = '<svg viewBox="0 0 100 40"><rect x="1" y="2" width="30" height="10" fill="url(#g)" /><text>OK</text></svg>'

    cleaned = sanitize_svg(svg)

    assert cleaned is not None
    assert "<rect" in cleaned
    assert 'fill="url(#g)"' in cleaned
    assert "<text>OK</text>" in cleaned


def test_sanitize_svg_removes_script_and_event_handlers():
    svg = '<svg viewBox="0 0 10 10" onclick="alert(1)"><script>alert(1)</script><circle onload="x()" r="4" /></svg>'

    cleaned = sanitize_svg(svg)

    assert cleaned == '<svg viewBox="0 0 10 10"><circle r="4" /></svg>'


def test_sanitize_svg_drops_dangerous_urls_and_unsupported_tags():
    svg = '<svg><foreignObject><body>bad</body></foreignObject><path d="M0 0" href="javascript:alert(1)" style="fill:url(http://x)" /></svg>'

    cleaned = sanitize_svg(svg)

    assert cleaned == '<svg><path d="M0 0" /></svg>'


def test_sanitize_svg_rejects_invalid_markup():
    assert sanitize_svg("<svg><g></svg>") is None
    assert sanitize_svg("<div></div>") is None

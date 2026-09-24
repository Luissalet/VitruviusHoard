from vitruvius_hoard.ingest.markdown import chunk_markdown


def test_title_from_frontmatter():
    r = chunk_markdown("---\ntitle: My Doc\n---\nBody text.")
    assert r["title"] == "My Doc"


def test_title_from_first_h1_when_no_frontmatter():
    r = chunk_markdown("# Hello World\nSome text.")
    assert r["title"] == "Hello World"


def test_default_title_used_when_nothing_found():
    r = chunk_markdown("Just a paragraph, no headings.", default_title="fallback")
    assert r["title"] == "fallback"


def test_splits_by_heading_with_breadcrumb():
    md = "# Top\n## Section A\nText A.\n## Section B\nText B."
    r = chunk_markdown(md)
    headings = [c["heading"] for c in r["chunks"]]
    assert any("Section A" in h for h in headings)
    assert any("Section B" in h for h in headings)


def test_breadcrumb_includes_ancestors():
    md = "# Top\n## Mid\n### Leaf\nDeep text."
    r = chunk_markdown(md)
    assert any("Top" in c["heading"] and "Mid" in c["heading"] and "Leaf" in c["heading"] for c in r["chunks"])


def test_long_section_is_split_under_max_chars():
    md = "# Doc\n## Big\n" + ("word " * 2000)
    r = chunk_markdown(md)
    assert len(r["chunks"]) > 1
    assert all(len(c["text"]) <= 1200 for c in r["chunks"])


def test_ordinal_increments():
    md = "# Doc\n## A\ntext a\n## B\ntext b\n## C\ntext c"
    r = chunk_markdown(md)
    ordinals = [c["ordinal"] for c in r["chunks"]]
    assert ordinals == sorted(ordinals)
    assert ordinals == list(range(len(ordinals)))


def test_empty_input_returns_no_chunks():
    r = chunk_markdown("")
    assert r["chunks"] == []


def test_tokens_estimate_is_positive():
    r = chunk_markdown("# Doc\nSome real content here.")
    assert all(c["tokens"] >= 1 for c in r["chunks"])


def test_plain_text_without_headings_becomes_one_section():
    r = chunk_markdown("Just plain text without any heading at all.")
    assert len(r["chunks"]) == 1



def test_fts_query_keeps_accented_words_whole():
    from vitruvius_hoard.library import _fts_query

    q = "cuánto debe durar la animación de un cajón lateral"
    assert '"animación"' in _fts_query(q, "and")
    assert '"n"' not in _fts_query(q, "and")  # the old ASCII regex split «animación» into «animaci» + «n»
    assert _fts_query(q, "or") == '"durar" OR "animación" OR "cajón" OR "lateral"'
    assert _fts_query("de la", "or") == '"de" OR "la"'  # only function words: keep them rather than search nothing

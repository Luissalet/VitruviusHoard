from vitruvius_hoard import library




def test_fts_query_keeps_accented_words_whole():
    from vitruvius_hoard.library import _fts_query

    q = "cuánto debe durar la animación de un cajón lateral"
    assert '"animación"' in _fts_query(q, "and")
    assert '"n"' not in _fts_query(q, "and")  # the old ASCII regex split «animación» into «animaci» + «n»
    assert _fts_query(q, "or") == '"durar"* OR "animación"* OR "cajón"* OR "lateral"*'  # question words out, topic words as prefixes
    assert _fts_query("de la", "or") == '"de" OR "la"'  # only function words: keep them rather than search nothing


def test_a_question_finds_plural_and_prefix_forms_of_the_topic(tmp_path):
    from test_library import seeded_db

    db = seeded_db(tmp_path)
    # «motions» is not a word in the library, its stem is: the shared word rules reach it through the wider or-net
    assert library.search(db, "motions")
    assert library.search(db, "how should I use motion")  # question words do not hide the topic


def test_stopword_only_questions_still_search_for_something():
    from vitruvius_hoard.library import _fts_query

    assert _fts_query("de la", "and") == '"de" AND "la"'

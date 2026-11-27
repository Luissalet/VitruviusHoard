"""Source files for a page without a records interface."""

TEMPLATE = {
    "id": "static-page",
    "name": "Static page",
    "name_es": "Página estática",
    "accent": "#315a54",
    "fields": [],
}


def page_files(name, accent, lang, description):
    language = "es" if lang.lower().startswith("es") else "en"
    layout = f'<!doctype html><html lang="{language}">' + """<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{name}}</title>
<link rel="stylesheet" href="/assets/style.css">
</head>
<body><main>{{content}}</main></body>
</html>
"""
    css = f":root {{ --surface: #faf8f1; --ink: #253332; --accent: {accent}; }}\n" + """* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--ink); font: 1rem/1.6 system-ui, sans-serif; }
main { max-width: 70ch; margin-inline: auto; padding: clamp(24px, 6vw, 80px) clamp(16px, 4vw, 32px); }
h1 { font: 500 clamp(2rem, 6vw, 4rem)/1.1 Georgia, serif; margin: 0 0 .5em; overflow-wrap: anywhere; }
a { color: var(--accent); text-underline-offset: .2em; }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
"""
    readme = (
        f"# {name}\n\nEdit `pages/index.html` for the page content, `layout.html` for the document "
        "and `assets/style.css` for its appearance. Open the project preview to see the page.\n\n"
        "The export includes the standard standalone Python runtime.\n"
    )
    return {
        "layout.html": layout,
        "pages/index.html": "<h1>{{name}}</h1>\n" + ("<p>{{description}}</p>\n" if description else ""),
        "assets/style.css": css,
        "README.md": readme,
    }

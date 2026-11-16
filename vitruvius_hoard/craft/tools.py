"""Cold craft-library controls on the software host and the MCP catalogue (available with every module OFF)."""
from __future__ import annotations

NAMES = {"craft_search", "craft_read", "craft_page", "craft_model_site"}


def catalog(control):
    string = {"type": "string"}
    kind = {"enum": ["texture", "hero", "scene", "dashboard-rule", "model-site", "threeui"]}
    view = {"type": "object", "properties": {"name": string, "azimuth": {"type": "number"}, "elevation": {"type": "number"},
                                             "distance": {"type": "number"}, "lens": {"type": "number"}}, "required": ["name"]}
    return [
        control("craft_search", "Search the design reference library: texture recipes (thermal gradients, blueprint grid, waves, speckled graphite, fluted glass, contour lines, grain, monochrome landscape, grass, soft shadow), "
                "hero layouts that are not boring, native 3D scenes with controls, rules against generic dashboards, the 3D-model-to-showcase-site recipe and the ThreeUI Community catalogue (MIT). "
                "Buscar texturas, heroes, escenas 3D y reglas de panel. Returns cites like [vitruvius: craft/texture/thermal]. Available with modules OFF.",
                {"query": string, "kind": kind, "limit": {"type": "integer", "minimum": 1, "maximum": 60}}, read=True),
        control("craft_read", "Read one reference in full: working CSS and its controls (textures), decisions and interaction (heroes, scenes), do/check (dashboard rules), steps (model-site) or catalogue entry (threeui).",
                {"kind": kind, "id": string}, ("kind", "id"), True),
        control("craft_page", "Generate a complete HTML page from a texture, hero, scene or the calm dashboard (kind dashboard-rule), with optional params (title, subtitle, texture, hue, items, CSS variable values). "
                "The result goes straight to design_critique or to a file. Generar una página a partir de una receta.",
                {"kind": {"enum": ["texture", "hero", "scene", "dashboard-rule"]}, "id": string, "params": {"type": "object"}}, ("kind", "id"), True),
        control("craft_model_site", "Showcase site from a 3D model: returns the Blender script (views you choose + a section-cut video), the command to run it and the page that assembles the rendered files. "
                "Web de escaparate desde un modelo 3D (Blender en lugar de Revit). Does not run Blender or write files: run the script, look at every still, adjust the views, then build the page.",
                {"model": string, "out_dir": string, "views": {"type": "array", "items": view, "minItems": 1, "maxItems": 12}, "section": {"type": "boolean"},
                 "section_axis": {"enum": ["x", "y", "z"]}, "section_view": {"type": "integer", "minimum": 0}, "engine": {"enum": ["CYCLES", "EEVEE", "WORKBENCH"]},
                 "samples": {"type": "integer", "minimum": 1, "maximum": 512}, "width": {"type": "integer", "minimum": 320, "maximum": 4096},
                 "height": {"type": "integer", "minimum": 240, "maximum": 4096}, "fps": {"type": "integer", "minimum": 8, "maximum": 60},
                 "seconds": {"type": "integer", "minimum": 2, "maximum": 30}, "title": string, "subtitle": string}, ("model", "out_dir"), True),
    ]


async def execute(runtime, name, arguments):
    from . import model_site, page, read, search
    if name == "craft_search":
        return search(arguments.get("query", ""), arguments.get("kind"), arguments.get("limit", 10))
    if name == "craft_read":
        return read(arguments["kind"], arguments["id"])
    if name == "craft_page":
        return page(arguments["kind"], arguments["id"], arguments.get("params"))
    views = arguments.get("views") or model_site.DEFAULT_VIEWS
    script = model_site.blender_script(arguments["model"], arguments["out_dir"], views, section_axis=arguments.get("section_axis", "z"),
                                       section_view=arguments.get("section_view", 0), engine=arguments.get("engine", "CYCLES"),
                                       samples=arguments.get("samples", 24), width=arguments.get("width", 1600), height=arguments.get("height", 900),
                                       fps=arguments.get("fps", 24), seconds=arguments.get("seconds", 8), section=arguments.get("section", True))
    site = model_site.site_page(arguments.get("title") or "Proyecto", arguments.get("subtitle") or "Vistas y corte de sección del modelo.", views,
                                "corte-de-seccion.mp4" if arguments.get("section", True) else None)
    return {"recipe": model_site.RECIPE, "script": script, "command": 'blender --background --factory-startup --python "<script.py>"',
            "outputs": [v["name"] + ".png" for v in views] + (["corte-de-seccion.mp4"] if arguments.get("section", True) else []),
            "page": site, "next": "Run the script, open every still, change the views that fail, then save page.html next to the outputs and critique it."}

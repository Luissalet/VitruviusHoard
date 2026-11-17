"""Cold craft-library controls on the software host and the MCP catalogue (available with every module OFF)."""
from __future__ import annotations

NAMES = {"craft_search", "craft_read", "craft_page", "craft_model_site", "ui_set_install", "ui_set_fetch"}


def catalog(control):
    string = {"type": "string"}
    kind = {"enum": ["texture", "hero", "scene", "dashboard-rule", "model-site", "threeui", "ui-set", "ui-control"]}
    view = {"type": "object", "properties": {"name": string, "azimuth": {"type": "number"}, "elevation": {"type": "number"},
                                             "distance": {"type": "number"}, "lens": {"type": "number"}}, "required": ["name"]}
    return [
        control("craft_search", "Search the design reference library: texture recipes (thermal gradients, blueprint grid, waves, speckled graphite, fluted glass, contour lines, grain, monochrome landscape, grass, soft shadow), "
                "hero layouts that are not boring, native 3D scenes with controls, rules against generic dashboards, the 3D-model-to-showcase-site recipe the ThreeUI Community catalogue (MIT) and style sets for controls (kind ui-set / ui-control: anime Sakuga VFX, 1930s Rubber Hose UI, pixel-art Pixel Worlds; each with a preview and when to use it). "
                "Buscar texturas, heroes, escenas 3D y reglas de panel. Returns cites like [vitruvius: craft/texture/thermal]. Available with modules OFF.",
                {"query": string, "kind": kind, "limit": {"type": "integer", "minimum": 1, "maximum": 60}}, read=True),
        control("craft_read", "Read one reference in full: working CSS and its controls (textures), decisions and interaction (heroes, scenes), do/check (dashboard rules), steps (model-site) or catalogue entry (threeui).",
                {"kind": kind, "id": string}, ("kind", "id"), True),
        control("craft_page", "Generate a complete HTML page from a texture, hero, scene, the calm dashboard (kind dashboard-rule), a style set board (ui-set) or one control of a set with its script inline (ui-control, id set/control), with optional params (title, subtitle, texture, hue, items, CSS variable values). "
                "The result goes straight to design_critique or to a file. Generar una página a partir de una receta.",
                {"kind": {"enum": ["texture", "hero", "scene", "dashboard-rule", "ui-set", "ui-control"]}, "id": string, "params": {"type": "object"}}, ("kind", "id"), True),
        control("craft_model_site", "Showcase site from a 3D model: returns the Blender script (views you choose + a section-cut video), the command to run it and the page that assembles the rendered files. "
                "Web de escaparate desde un modelo 3D (Blender en lugar de Revit). Does not run Blender or write files: run the script, look at every still, adjust the views, then build the page.",
                {"model": string, "out_dir": string, "views": {"type": "array", "items": view, "minItems": 1, "maxItems": 12}, "section": {"type": "boolean"},
                 "section_axis": {"enum": ["x", "y", "z"]}, "section_view": {"type": "integer", "minimum": 0}, "engine": {"enum": ["CYCLES", "EEVEE", "WORKBENCH"]},
                 "samples": {"type": "integer", "minimum": 1, "maximum": 512}, "width": {"type": "integer", "minimum": 320, "maximum": 4096},
                 "height": {"type": "integer", "minimum": 240, "maximum": 4096}, "fps": {"type": "integer", "minimum": 8, "maximum": 60},
                 "seconds": {"type": "integer", "minimum": 2, "maximum": 30}, "title": string, "subtitle": string}, ("model", "out_dir"), True),
        control("ui_set_install", "Copy the controls of a bundled style set (Sakuga VFX anime, Rubber Hose UI, Pixel Worlds) into a project folder with its licence file and return the script tags and markup to paste. "
                "Instalar un paquete de estilo de controles en el proyecto. Writes only inside out_dir/<set id>/.",
                {"set": string, "out_dir": string, "controls": {"type": "array", "items": string, "maxItems": 12}}, ("set", "out_dir"), False),
        control("ui_set_fetch", "Download one effect of an on-demand set (KanaWorks Sakuga VFX flipbooks, licence with a required credit) into out_dir/<set id>/ and write its credit line beside it. "
                "The effects are never copied into the library; the credit must be shown wherever they are used. Descargar un efecto bajo demanda con su aviso de crédito.",
                {"set": string, "effect": string, "out_dir": string}, ("set", "effect", "out_dir"), False),
    ]


async def execute(runtime, name, arguments):
    from . import model_site, page, read, search, ui_sets
    if name == "craft_search":
        return search(arguments.get("query", ""), arguments.get("kind"), arguments.get("limit", 10))
    if name == "craft_read":
        return read(arguments["kind"], arguments["id"])
    if name == "craft_page":
        return page(arguments["kind"], arguments["id"], arguments.get("params"))
    if name == "ui_set_install":
        return ui_sets.install(arguments["set"], arguments["out_dir"], arguments.get("controls"))
    if name == "ui_set_fetch":
        return ui_sets.fetch(arguments["set"], arguments["effect"], arguments["out_dir"])
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

"""Cold library controls on the normal software host and MCP catalogue."""
from __future__ import annotations


def catalog(control):
    string = {"type": "string"}
    identity = {"id": {"type": "string", "enum": ["book", "glitch", "gallery", "city", "rock"]}}
    return [
        control("showcase_recipes", "Find working showcase references and reproduction recipes. Buscar recetas de webs, cinematográfico, libro, retrato glitch, galería 3D, ciudad, producto sobre roca. Available with modules OFF.",
                {"query": string}, read=True),
        control("showcase_recipe", "Read a reference/recipe pair with observed source frames, light, rhythm, typography, interaction, why, reproduction prompt, specific agent skill and parity checkpoints.", identity, ("id",), True),
        control("showcase_source", "Read the actual runnable source of a showcase reference. All assets also ship in its independent ZIP.",
                {**identity, "path": string}, ("id",), True),
        control("showcase_remake", "Start a retained Rehacer parity run from a bundled showcase and its recipe. Enable Design explicitly first. Copy defaults to one stable composition round. Rebuild uses the configured global model. Inspect the recipe's interaction states separately.",
                {**identity, "mode": {"enum": ["copy", "rebuild"]},
                 "widths": {"type": "array", "items": {"type": "integer", "minimum": 200, "maximum": 3000}, "minItems": 1, "maxItems": 3},
                 "max_rounds": {"type": "integer", "minimum": 1, "maximum": 20}}, ("id",)),
    ]


async def execute(runtime, name, arguments):
    from . import library
    if name == "showcase_recipes":
        return library.search(arguments.get("query", ""))
    if name == "showcase_recipe":
        return library.read(arguments["id"])
    if name == "showcase_source":
        return library.source(arguments["id"], arguments.get("path", "index.html"))
    recipe = library.read(arguments["id"])
    remake = {**recipe["remake_arguments"], **{key: value for key, value in arguments.items() if key != "id"}}
    if remake["mode"] == "rebuild" and "max_rounds" not in arguments:
        remake["max_rounds"] = 6
    result = await runtime.call("remake_start", remake)
    return {"recipe_id": recipe["id"], "reference_url": recipe["reference_url"], "remake": result,
            "checkpoints": recipe["checkpoints"], "parity_states": recipe["parity_states"]}

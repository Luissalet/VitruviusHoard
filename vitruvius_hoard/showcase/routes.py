"""Executable bundled references, source exports and recipes."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from . import library

router = APIRouter()


@router.get("/api/showcase")
def recipes(query: str = Query("", max_length=500)):
    return library.search(query)


@router.get("/api/showcase/{recipe_id}")
def recipe(recipe_id: str):
    try:
        return library.read(recipe_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/api/showcase/{recipe_id}/source")
def source(recipe_id: str, path: str = Query("index.html", max_length=300)):
    try:
        return library.source(recipe_id, path)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/api/showcase/{recipe_id}/download")
def download(recipe_id: str):
    try:
        data = library.archive(recipe_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{recipe_id}-showcase.zip"'})


@router.get("/showcase/")
def home():
    return FileResponse(library.ROOT / "library.html")


@router.get("/showcase/{path:path}")
def resource(path: str):
    try:
        data, kind = library.resource(path)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return Response(data, media_type=kind)

"""The Mini App's files as the API serves them at `/app/`.

Two things a plain static mount would get wrong:

* caching — without a Cache-Control header a WebView keeps a page by heuristics (a tenth of the
  file's age, hours for a release installed in the morning), so a phone went on showing a release
  that had already been replaced; every file here is `no-cache` ("ask first"), and with the ETag
  that is a 304, not a download;
* the language — the page opens in the installation's `app.default_language` (the `<html lang>`
  the page reads on start), not in whatever the client's phone is set to; the switch in the header
  remembers the visitor's own choice on the device.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.responses import HTMLResponse, Response

PAGE = "mvp.html"
BUILT_LANG = '<html lang="ru">'  # what scripts/build_prototypes.py writes


class AppFiles(StaticFiles):
    def __init__(self, *args, default_language: str = "ru", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.default_language = default_language

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response

    async def get_response(self, path: str, scope) -> Response:
        if path == PAGE and self.default_language != "ru":
            full_path, stat_result = self.lookup_path(path)
            if stat_result is not None:
                body = Path(full_path).read_text(encoding="utf-8").replace(BUILT_LANG, f'<html lang="{self.default_language}">', 1)
                etag = '"' + hashlib.md5(body.encode("utf-8")).hexdigest() + '"'  # noqa: S324 - a cache key, not a secret
                headers = {"Cache-Control": "no-cache", "ETag": etag}
                if Headers(scope=scope).get("if-none-match") == etag:
                    return Response(status_code=304, headers=headers)
                if scope["method"] == "HEAD":
                    return Response(headers=headers, media_type="text/html")
                return HTMLResponse(body, headers=headers)
        return await super().get_response(path, scope)

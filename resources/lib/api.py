# coding: utf-8
# Copyright © 2020 melmorabity

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# This module is partly inspired by the allocine-api project developed by
# gromez (https://github.com/gromez/allocine-api/)

import base64
from collections import OrderedDict
from datetime import date
import hashlib

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

try:
    from typing import Any
    from typing import Dict
    from typing import List
    from typing import Optional
    from typing import Union
except ImportError:
    pass

from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util import Retry


class AlloCineException(Exception):
    pass


class AlloCine:
    _ALLOCINE_API_URL = "https://api.allocine.fr/rest/v3"
    _ALLOCINE_USER_AGENT = (
        "Mozilla/5.0 (Linux; Android 10; SM-G975U) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/79.0.3945.93 Mobile Safari/537.36"
    )
    _ALLOCINE_PARTNER_KEY = "100ED1DA33EB"
    _ALLOCINE_SECRET_KEY = "1a1ed8c1bed24d60ae3472eed1da33eb"  # nosec

    _WIKIDATA_API_URL = (
        "https://query.wikidata.org/bigdata/namespace/wdq/sparql"
    )

    _TMDB_API_URL = "https://api.themoviedb.org/3"
    _TMDB_API_KEY = "e9398d6bf0e3664b8e27dab81adda961"

    _REQUESTS_RETRIES = 10
    _REQUESTS_BACKOFF_FACTOR = 5

    def __init__(self):
        # type: () -> None

        self._session = Session()

        retry_strategy = Retry(
            total=self._REQUESTS_RETRIES,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=self._REQUESTS_BACKOFF_FACTOR,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self._session:
            self._session.close()

    def _query_allocine_api(self, path, payload):
        # type: (str, OrderedDict[str, Any])-> Dict[str, Any]

        payload["sed"] = date.today().strftime("%Y%m%d")

        signature = hashlib.sha1(  # nosec
            (path + urlencode(payload) + self._ALLOCINE_SECRET_KEY).encode(
                "ascii"
            )
        ).digest()
        payload["sig"] = base64.b64encode(signature)

        try:
            data = self._session.get(
                "{}/{}".format(self._ALLOCINE_API_URL, path),
                params=payload,
                headers={"User-Agent": self._ALLOCINE_USER_AGENT},
            ).json()
        except RequestException as ex:
            raise AlloCineException(ex)

        if "error" in data:
            raise AlloCineException(data["error"].get("$"))

        return data

    def search_movies(self, title):
        # type: (str) -> List[Dict[str, Any]]

        payload = OrderedDict()  # type: OrderedDict[str, Union[int, str]]
        payload["count"] = 9999
        payload["filter"] = "movie"
        payload["format"] = "json"
        payload["partner"] = self._ALLOCINE_PARTNER_KEY
        payload["q"] = title

        return (
            self._query_allocine_api("search", payload)
            .get("feed", {})
            .get("movie", {})
        )

    def get_movie(self, movie_id):
        # type: (int) -> Dict[str, Any]

        payload = OrderedDict()  # type: OrderedDict[str, Union[int, str]]
        payload["code"] = movie_id
        payload["format"] = "json"
        payload["partner"] = self._ALLOCINE_PARTNER_KEY
        payload["profile"] = "large"
        payload["striptags"] = "synopsis,synopsisshort"

        return self._query_allocine_api("movie", payload).get("movie", {})

    def get_media(self, media_id):
        # type: (int) -> Dict[str, Any]

        payload = OrderedDict()  # type: OrderedDict[str, Union[int, str]]
        payload["code"] = media_id
        payload["format"] = "json"
        payload["partner"] = self._ALLOCINE_PARTNER_KEY
        payload["profile"] = "large"

        return self._query_allocine_api("media", payload).get("media", {})

    def _get_imdb_id(self, movie_id):
        # type: (int) -> Optional[str]

        # Use Wikidata to get the IMDB ID from the Allociné movie ID
        sparql_query = (
            'SELECT DISTINCT ?imdb WHERE {{ ?item wdt:P1265 "{}"; '
            "wdt:P345 ?imdb. }}".format(movie_id)
        )

        try:
            response = self._session.get(
                self._WIKIDATA_API_URL,
                params={"query": sparql_query},
                headers={"Accept": "application/json"},
            )
        except RequestException as ex:
            raise AlloCineException(ex)

        result = response.json().get("results", {}).get("bindings")
        if not result:
            return None

        return result[0].get("imdb", {}).get("value")

    def _query_tmdb_api(self, path, params=None):
        # type: (str, Optional[Dict]) -> Dict[str, Any]

        if not params:
            params = {}
        params["api_key"] = self._TMDB_API_KEY

        try:
            response = self._session.get(
                self._TMDB_API_URL + "/" + path.lstrip("/"), params=params,
            )
        except RequestException as ex:
            raise AlloCineException(ex)

        data = response.json()
        if not data.get("success", True):
            raise AlloCineException(data.get("status_message"))

        return data

    def _get_tmdb_id(self, movie_id):
        # type: (int) -> Optional[int]

        imdb_movie_id = self._get_imdb_id(movie_id)
        if not imdb_movie_id:
            return None

        result = self._query_tmdb_api(
            "find/" + imdb_movie_id, params={"external_source": "imdb_id"},
        ).get("movie_results")
        if not result:
            return None
        return result[0].get("id")

    def get_tmdb_movie_from_allocine_id(self, movie_id):
        # type: (int) -> Dict[str, Any]

        tmdb_movie_id = self._get_tmdb_id(movie_id)
        if not tmdb_movie_id:
            return {}

        movie_data = self._query_tmdb_api(
            "movie/{}".format(tmdb_movie_id),
            params={
                # "append_to_response": "images",
                "language": "fr",
                # "include_image_language": "fr,null,en",
            },
        )

        image_languages = ["fr", "null"]
        original_language = movie_data.get("original_language") or "null"
        if original_language not in image_languages:
            image_languages.append(original_language)

        movie_data["images"] = self._query_tmdb_api(
            "movie/{}/images".format(tmdb_movie_id),
            params={"language": ",".join(image_languages)},
        )

        # Sort images by language
        for image_kind in ("posters", "backdrops"):
            if image_kind not in movie_data["images"]:
                continue
            try:
                movie_data["images"][image_kind].sort(
                    key=lambda k: image_languages.index(
                        k.get("iso_639_1")
                        if k.get("iso_639_1") in image_languages
                        else "null"
                    )
                )
            except ValueError as ex:
                raise Exception(
                    "ID = %i (%s) [%s]"
                    % (tmdb_movie_id, str(image_languages), str(ex))
                )

        return movie_data

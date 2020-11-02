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

import os
import re

try:
    from typing import Any
    from typing import Dict
    from typing import List
    from typing import Optional
except ImportError:
    pass

try:
    from urllib.parse import parse_qsl
except ImportError:
    from urlparse import parse_qsl

import xbmc  # pylint: disable=E0401
from xbmcaddon import Addon  # pylint: disable=E0401
from xbmcgui import Dialog  # pylint: disable=E0401
from xbmcgui import ListItem  # pylint: disable=E0401
import xbmcplugin  # pylint: disable=E0401

from .api import AlloCine
from .api import AlloCineException


class AlloCineAddon:
    _ADDON_ID = "metadata.allocine.fr.python"
    _ADDON = Addon(id=_ADDON_ID)
    _ADDON_NAME = _ADDON.getAddonInfo("name")
    _ADDON_DIR = xbmc.translatePath(_ADDON.getAddonInfo("path"))
    _ADDON_ICON = os.path.join(_ADDON_DIR, "resources", "icon.png")

    _NFO_URL_RE = re.compile(
        r"https?://(?:www)?\.allocine\.fr/film/fichefilm_gen_cfilm="
        r"(?P<id>\d+)\.html"
    )

    # HQ, MQ, SQ, LQ
    _TRAILER_QUALITY_IDS = [104004, 104003, 104002, 104001]

    _TMDB_IMAGE_URL_TEMPLATE = "https://image.tmdb.org/t/p/{}{}"

    def __init__(self, handle, params):
        # type: (int, str) -> None

        self._handle = handle
        self._params = self._params_to_dict(params)

        self._trailer_quality_id = self._TRAILER_QUALITY_IDS[
            int(self._ADDON.getSetting("trailer_quality"))
        ]
        self._get_tmdb_data = self._ADDON.getSetting("tmdb_data") == "true"
        self._get_tmdb_artwork = (
            self._ADDON.getSetting("tmdb_artwork") == "true"
        )

        self._api = AlloCine()

    @staticmethod
    def _params_to_dict(params):
        # type: (Optional[str]) -> Dict[str, str]

        # Parameter string starts with a '?'
        return dict(parse_qsl(params[1:])) if params else {}

    def _log(self, message, level=xbmc.LOGDEBUG):
        # type: (str, int) -> None

        xbmc.log(msg="[{}]: {}".format(self._ADDON_ID, message), level=level)

    def _notification(self, message):
        # type: (str) -> None

        Dialog().notification(
            self._ADDON_NAME, message, icon=self._ADDON_ICON,
        )

    def _get_trailer(self, media_id):
        # type: (int) -> Optional[str]

        result = None

        for rendition in self._api.get_media(media_id).get("rendition", []):
            url = rendition.get("href")
            quality = rendition.get("bandwidth", {}).get("code")
            if url and quality and quality <= self._trailer_quality_id:
                result = url

        return result

    def _parse_movie_listitem_info(self, movie_data, tmdb_movie_data):
        # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]

        info = {}

        info["title"] = movie_data.get("title")
        info["originaltitle"] = movie_data.get("originalTitle")

        rank_top_movie = movie_data.get("statistics", {}).get("rankTopMovie")
        info["top250"] = (
            rank_top_movie
            if rank_top_movie and rank_top_movie >= 250
            else None
        )

        info["plotoutline"] = movie_data.get("synopsisShort")
        info["plot"] = movie_data.get("synopsis")

        runtime = movie_data.get("runtime")
        info["duration"] = round(runtime / 60.0) if runtime else None

        info["mpaa"] = (
            movie_data.get("movieCertificate", {})
            .get("certificate", {})
            .get("$")
        )
        info["genre"] = [
            t["$"].capitalize()
            for t in movie_data.get("genre", {})
            if "$" in t
        ]
        info["country"] = [
            n["$"] for n in movie_data.get("nationality", {}) if "$" in n
        ]
        info["tag"] = [
            t["$"].capitalize() for t in movie_data.get("tag", {}) if "$" in t
        ]
        info["credits"] = [
            m.get("person", {}).get("name")
            for m in movie_data.get("castMember", [])
            if m.get("activity", {}).get("code") in [8004, 8085]
        ]
        info["director"] = [
            m.get("person", {}).get("name")
            for m in movie_data.get("castMember", [])
            if m.get("activity", {}).get("code") == 8002
        ]
        info["premiered"] = movie_data.get("release", {}).get("releaseDate")
        info["year"] = movie_data.get("productionYear")

        trailer_code = movie_data.get("trailer", {}).get("code") or next(
            (
                m.get("code")
                for m in movie_data.get("media", [])
                if m.get("type", {}).get("code") == 30005
            ),
            None,
        )
        info["trailer"] = (
            self._get_trailer(trailer_code) if trailer_code else None
        )

        # Take missing information from TMDB
        info["tagline"] = tmdb_movie_data.get("tagline")
        info["studio"] = [
            p.get("name")
            for p in tmdb_movie_data.get("production_companies", [])
            if "name" in p
        ]
        # belongs_to_collection can have None as value
        info["set"] = (tmdb_movie_data.get("belongs_to_collection") or {}).get(
            "name"
        )

        return info

    @staticmethod
    def _parse_movie_listitem_cast(movie_data):
        # type: (Dict[str, Any]) -> List[Dict[str, str]]

        return [
            {
                "name": c.get("person", {}).get("name"),
                "role": c.get("role"),
                "thumbnail": c.get("picture", {}).get("href"),
            }
            for c in movie_data.get("castMember", [])
            if c.get("activity", {}).get("code") == 8001
        ]

    @staticmethod
    def _is_valid_poster(width, height):
        # type: (Optional[int], Optional[int]) -> bool

        if not width or not height:
            return False

        return 400 <= width <= height

    def _parse_movie_listitem_posters(self, movie_data, tmdb_movie_data):
        # type: (Dict[str, Any], Dict[str, Any]) -> List[str]

        main_poster_href = movie_data.get("poster", {}).get("href")

        posters = []  # type: List[str]
        for media in movie_data.get("media", []):
            if media.get("type", {}).get("code") != 31001:
                continue
            if not self._is_valid_poster(
                media.get("width"), media.get("height")
            ):
                continue

            href = media.get("thumbnail", {}).get("href")
            if href == main_poster_href:
                posters.insert(0, href)
            else:
                posters.append(href)

        tmdb_posters = [
            self._TMDB_IMAGE_URL_TEMPLATE.format(
                "original", p.get("file_path")
            )
            for p in tmdb_movie_data.get("images", {}).get("posters", [])
        ]

        return posters + tmdb_posters

    @staticmethod
    def _is_valid_fanart(width, height):
        # type: (Optional[int], Optional[int]) -> bool

        if not width or not height:
            return False

        # Use TheMovieDB rules to filter fanarts by quality
        return (
            720 <= height < width
            and width >= 1280
            and round(float(width) / float(height), 2) == 1.78
        )

    def _parse_movie_listitem_fanarts(self, movie_data, tmdb_movie_data):
        # type: (Dict[str, Any], Dict[str, Any]) -> List[Dict[str, str]]

        fanarts = [
            {
                "image": m.get("thumbnail", {}).get("href"),
                "preview": m.get("thumbnail", {})
                .get("href")
                .replace("/pictures/", "/r_780_0/pictures/"),
            }
            for m in movie_data.get("media", [])
            if m.get("type", {}).get("code") == 31006
            # Only keep HD images
            and self._is_valid_fanart(m.get("width"), m.get("height"))
        ]

        tmdb_fanarts = [
            {
                "image": self._TMDB_IMAGE_URL_TEMPLATE.format(
                    "original", b.get("file_path")
                ),
                "preview": self._TMDB_IMAGE_URL_TEMPLATE.format(
                    "w780", b.get("file_path")
                ),
            }
            for b in tmdb_movie_data.get("images", {}).get("backdrops", [])
        ]

        return fanarts + tmdb_fanarts

    def _get_movie_listitem(self, movie_id):
        # type: (int) -> Optional[ListItem]

        movie_data = self._api.get_movie(movie_id)
        tmdb_movie_data = {}
        unique_ids = {"allocine": movie_id}

        if self._get_tmdb_data or self._get_tmdb_artwork:
            tmdb_movie_data = self._api.get_tmdb_movie_from_allocine_id(
                movie_id
            )

            if not tmdb_movie_data:
                self._log(
                    "Unable to find TMDB ID for movie {}".format(movie_id),
                    xbmc.LOGWARNING,
                )
            else:
                if self._get_tmdb_data:
                    tmdb_id = tmdb_movie_data.get("id")
                    if tmdb_id:
                        unique_ids.update({"tmdb": tmdb_id})
                    imdb_id = tmdb_movie_data.get("imdb_id")
                    if imdb_id:
                        unique_ids.update({"imdb": imdb_id})

        info = self._parse_movie_listitem_info(movie_data, tmdb_movie_data)

        listitem = ListItem(info.get("title"), offscreen=True)
        listitem.setUniqueIDs(unique_ids, "allocine")
        listitem.setInfo("video", info)
        listitem.setCast(self._parse_movie_listitem_cast(movie_data))

        for poster in self._parse_movie_listitem_posters(
            movie_data, tmdb_movie_data
        ):
            listitem.addAvailableArtwork(poster, "poster")

        listitem.setAvailableFanart(
            self._parse_movie_listitem_fanarts(movie_data, tmdb_movie_data)
        )

        statistics = movie_data.get("statistics", {})
        user_rating = statistics.get("userRating")
        if user_rating:
            listitem.setRating(
                "allocine",
                user_rating * 2,
                votes=statistics.get("userRatingCount", 0),
                defaultt=True,
            )

        return listitem

    def _movie_id_from_nfo_url(self):
        # type: () -> Optional[int]

        nfo_url = self._params.get("nfo")
        if not nfo_url:
            return None

        match = self._NFO_URL_RE.search(nfo_url)
        if not match:
            return None

        return int(match.group("id"))

    def _action_nfourl(self):
        # () -> None
        movie_id = self._movie_id_from_nfo_url()
        if not movie_id:
            return

        self._log(
            "Getting information for movie with ID {} from NFO file".format(
                movie_id
            ),
            xbmc.LOGINFO,
        )

        listitem = ListItem(offscreen=True)
        xbmcplugin.addDirectoryItem(
            handle=self._handle,
            url=str(movie_id),
            listitem=listitem,
            isFolder=True,
        )

    def _action_getdetails(self):
        # type: () -> None

        try:
            movie_id = int(self._params.get("url", ""))
        except ValueError:
            return

        self._log(
            "Getting information for movie with ID {}".format(movie_id),
            xbmc.LOGINFO,
        )

        listitem = self._get_movie_listitem(movie_id)

        xbmcplugin.setResolvedUrl(
            handle=self._handle, succeeded=True, listitem=listitem
        )

    def _action_find(self):
        # type: () -> None

        title = self._params.get("title")
        if not title:
            return

        self._log(
            'Searching movies with title "{}"'.format(title), xbmc.LOGINFO,
        )

        data = self._api.search_movies(title)

        for movie in data:
            movie_id = movie.get("code")
            title = movie.get("title") or movie.get("originalTitle")
            if not movie_id or not title:
                continue
            year = movie.get("productionYear")

            info = {"title": title, "year": year}

            label = title
            if year:
                label += " ({})".format(year)

            listitem = ListItem(label, offscreen=True)
            listitem.setInfo("video", info)
            listitem.setArt({"thumb": movie.get("poster", {}).get("href")})

            xbmcplugin.addDirectoryItem(
                handle=self._handle,
                url=str(movie_id),
                listitem=listitem,
                isFolder=True,
            )

    def run(self):
        # type: () -> None

        action = self._params.get("action")
        succeeded = True

        try:
            if action == "NfoUrl":
                self._action_nfourl()
            elif action == "getdetails":
                self._action_getdetails()
            elif action == "find":
                self._action_find()
        except AlloCineException as ex:
            self._log(str(ex), xbmc.LOGERROR)
            self._notification(self._ADDON.getLocalizedString(30400))
            succeeded = False
        finally:
            xbmcplugin.endOfDirectory(self._handle, succeeded=succeeded)

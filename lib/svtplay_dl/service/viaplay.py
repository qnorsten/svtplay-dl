# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-

# pylint has issues with urlparse: "some types could not be inferred"
# pylint: disable=E1103

from __future__ import absolute_import
import re
import json
import copy
import os

from svtplay_dl.utils import filenamify
from svtplay_dl.utils.urllib import urlparse
from svtplay_dl.service import Service, OpenGraphThumbMixin
from svtplay_dl.log import log
from svtplay_dl.fetcher.rtmp import RTMP
from svtplay_dl.fetcher.hds import hdsparse
from svtplay_dl.fetcher.hls import hlsparse
from svtplay_dl.subtitle import subtitle
from svtplay_dl.info import info
from svtplay_dl.error import ServiceError
from math import ceil


class Viaplay(Service, OpenGraphThumbMixin):
    supported_domains = [
        'tv3play.se', 'tv6play.se', 'tv8play.se', 'tv10play.se',
        'tv3play.no', 'tv3play.dk', 'tv6play.no', 'viasat4play.no',
        'tv3play.ee', 'tv3play.lv', 'tv3play.lt', 'tvplay.lv', 'viagame.com',
        'juicyplay.se', 'viafree.se', 'viafree.dk', 'viafree.no',
        'play.tv3.lt', 'tv3play.tv3.ee', 'tvplay.skaties.lv'
    ]
    # List of json keys used in application 
    # Should only need to update this function on json update
    # Format is key_used_in_script: key_from_webpage
    json_keys = {
        "ID":"id",
        "SEASONNUMBERORVIDEOID":"seasonNumberOrVideoId",
        "VIDEOIDOREPISODENUMBER":"videoIdOrEpisodeNumber",
        "FORMAT":"format",
        "VIDEOS":"videos",
        "PROGRAM":"program",
        "EPISODENUMBER":"episodeNumber",
        "SEASONNUMBER":"seasonNumber",
        "MSG":"msg",
        "TYPE":"type",
        "SAMI_PATH":"sami_path",
        "SUBTITLES_WEBVTT":"subtitles_webvtt",
        "SUBTITLES_FOR_HEARING_IMPAIRED":"subtitles_for_hearing_impaired",
        "STREAMS":"streams",
        "MEDIUM":"medium",
        "HLS":"hls",
        "SEASONS":"seasons",
        "SEASONNUMBER":"seasonNumber",
        "SHARINGURL":"sharingUrl",
        "CLIP":"clip",
        "FORMAT_SLUG":"format_slug",
        "FORMAT_POSITION":"format_position",
        "TITLE":"title",
        "DERIVED_FROM_ID":"derived_from_id",
        "SEASON":"season",
        "EPISODE":"episode",
        "FORMAT_TITLE":"format_title",
        "BROADCASTS":"broadcasts",
        "AIR_AT":"air_at",
        "PLAYABLE_FROM":"playable_from",
        "DURATION":"duration",
        "IS_EPISODIC":"is_episodic",
        "TYPE":"type",
        "DESCRIPTION":"description",
        "SUMMARY":"summary",
    }

    def _get_video_id(self):
        """
        Extract video id. It will try to avoid making an HTTP request
        if it can find the ID in the URL, but otherwise it will try
        to scrape it from the HTML document. Returns None in case it's
        unable to extract the ID at all.
        """
        html_data = self.get_urldata()
        match = re.search(r'data-video-id="([0-9]+)"', html_data)
        if match:
            return match.group(1)
        match = re.search(r'data-videoid="([0-9]+)', html_data)
        if match:
            return match.group(1)

        clips = False
        match = re.search('params":({.*}),"query', self.get_urldata())
        if match:
            jansson = json.loads(match.group(1))
            if self.json_keys["SEASONNUMBERORVIDEOID"] in jansson:
                season = jansson[self.json_keys["SEASONNUMBERORVIDEOID"]]
                match = re.search("\w-(\d+)$", season)
                if match:
                    season = match.group(1)
            else:
                return False
            if self.json_keys["VIDEOIDOREPISODENUMBER"] in jansson:
                videp = jansson[self.json_keys["VIDEOIDOREPISODENUMBER"]]
                match = re.search('(\w+)-(\d+)', videp)
                if match:
                    episodenr = match.group(2)
                else:
                    episodenr = videp
                    clips = True
                match = re.search('(s\w+)-(\d+)', season)
                if match:
                    season = match.group(2)
            else:
                # sometimes videoIdOrEpisodeNumber does not work.. this is a workaround
                match = re.search('(episode|avsnitt)-(\d+)', self.url)
                if match:
                    episodenr = match.group(2)
                else:
                    episodenr = season

            if clips:
                return episodenr
            else:
                match = re.search('"ContentPageProgramStore":({.*}),"ApplicationStore', self.get_urldata())
                if match:
                    janson = json.loads(match.group(1))
                    for i in janson[self.json_keys["FORMAT"]][self.json_keys["VIDEOS"]].keys():
                        if self.json_keys["PROGRAM"] in janson[self.json_keys["FORMAT"]][self.json_keys["VIDEOS"]][str(i)]:
                            for n in janson[self.json_keys["FORMAT"]][self.json_keys["VIDEOS"]][i][self.json_keys["PROGRAM"]]:
                                if str(n[self.json_keys["EPISODENUMBER"]]) and int(episodenr) == n[self.json_keys["EPISODENUMBER"]] and int(season) == n[self.json_keys["SEASONNUMBER"]]:
                                    return n[self.json_keys["ID"]]
                                elif n[self.json_keys["ID"]] == episodenr:
                                    return episodenr

        parse = urlparse(self.url)
        match = re.search(r'/\w+/(\d+)', parse.path)
        if match:
            return match.group(1)
        match = re.search(r'iframe src="http://play.juicyplay.se[^\"]+id=(\d+)', html_data)
        if match:
            return match.group(1)
        return None

    def get(self):
        vid = self._get_video_id()
        if vid is None:
            yield ServiceError("Can't find video file for: %s" % self.url)
            return

        url = "http://playapi.mtgx.tv/v3/videos/%s" % vid
        self.options.other = ""
        data = self.http.request("get", url)
        if data.status_code == 403:
            yield ServiceError("Can't play this because the video is geoblocked.")
            return
        dataj = json.loads(data.text)
        if self.json_keys["MSG"] in dataj:
            yield ServiceError(dataj[self.json_keys["MSG"]])
            return

        if dataj[self.json_keys["TYPE"]] == "live":
            self.options.live = True

        if self.options.output_auto:
            directory = os.path.dirname(self.options.output)
            self.options.service = "viafree"
            basename = self._autoname(dataj)
            title = "%s-%s-%s" % (basename, vid, self.options.service)
            if len(directory):
                self.options.output = os.path.join(directory, title)
            else:
                self.options.output = title
                
        if self.exclude():
            yield ServiceError("Excluding video")
            return
            
        streams = self.http.request("get", "http://playapi.mtgx.tv/v3/videos/stream/%s" % vid)
        if streams.status_code == 403:
            yield ServiceError("Can't play this because the video is geoblocked.")
            return
        streamj = json.loads(streams.text)
        

        if self.json_keys["MSG"] in streamj:
            yield ServiceError("Can't play this because the video is either not found or geoblocked.")
            return

        if self.options.get_info:
            video_info = self._get_info(dataj)
            if video_info:
                yield info(copy.copy(self.options),video_info)
                log.info("Collecting info")
            else: 
                log.info("Couldn't get info for this episode")
                
        if dataj[self.json_keys["SAMI_PATH"]]:
            if dataj[self.json_keys["SAMI_PATH"]].endswith("vtt"):
                subtype = "wrst"
            else:
                subtype = "sami"
            yield subtitle(copy.copy(self.options), subtype, dataj[self.json_keys["SAMI_PATH"]])
        if dataj[self.json_keys["SUBTITLES_WEBVTT"]]:
            yield subtitle(copy.copy(self.options), "wrst", dataj[self.json_keys["SUBTITLES_WEBVTT"]])
        if dataj["subtitles_for_hearing_impaired"]:
            if dataj[self.json_keys["SUBTITLES_FOR_HEARING_IMPAIRED"]].endswith("vtt"):
                subtype = "wrst"
            else:
                subtype = "sami"
            if self.options.get_all_subtitles:
                yield subtitle(copy.copy(self.options), subtype, dataj[self.json_keys["SUBTITLES_FOR_HEARING_IMPAIRED"]], "-SDH")
            else: 
                yield subtitle(copy.copy(self.options), subtype, dataj[self.json_keys["SUBTITLES_FOR_HEARING_IMPAIRED"]])

        if streamj[self.json_keys["STREAMS"]][self.json_keys["MEDIUM"]]:
            filename = streamj[self.json_keys["STREAMS"]][self.json_keys["MEDIUM"]]
            if ".f4m" in filename:
                streams = hdsparse(self.options, self.http.request("get", filename, params={"hdcore": "3.7.0"}), filename)
                if streams:
                    for n in list(streams.keys()):
                        yield streams[n]
            else:
                parse = urlparse(filename)
                match = re.search("^(/[^/]+)/(.*)", parse.path)
                if not match:
                    yield ServiceError("Can't get rtmpparse info")
                    return
                filename = "%s://%s:%s%s" % (parse.scheme, parse.hostname, parse.port, match.group(1))
                path = "-y %s" % match.group(2)
                self.options.other = "-W http://flvplayer.viastream.viasat.tv/flvplayer/play/swf/player.swf %s" % path
                yield RTMP(copy.copy(self.options), filename, 800)

        if streamj[self.json_keys["STREAMS"]][self.json_keys["HLS"]]:
            streams = hlsparse(self.options, self.http.request("get", streamj[self.json_keys["STREAMS"]][self.json_keys["HLS"]]),streamj[self.json_keys["STREAMS"]][self.json_keys["HLS"]])
            if streams:
                for n in list(streams.keys()):
                    yield streams[n]

    def find_all_episodes(self, options):
        videos = []
        match = re.search('"ContentPageProgramStore":({.*}),"ApplicationStore', self.get_urldata())
        if match:
            janson = json.loads(match.group(1))
            season = re.search("sasong-(\d+)", urlparse(self.url).path)
            if season:
                season = season.group(1)
            seasons = []
            for i in janson[self.json_keys["FORMAT"]][self.json_keys["SEASONS"]]:
                if season:
                    if int(season) == i[self.json_keys["SEASONNUMBER"]]:
                        seasons.append(i[self.json_keys["SEASONNUMBER"]])
                else:
                    seasons.append(i[self.json_keys["SEASONNUMBER"]])

            for i in seasons:
                if self.json_keys["PROGRAM"] in janson[self.json_keys["FORMAT"]][self.json_keys["VIDEOS"]][str(i)]:
                    for n in janson[self.json_keys["FORMAT"]][self.json_keys["VIDEOS"]][str(i)][self.json_keys["PROGRAM"]]:
                        videos.append(n[self.json_keys["SHARINGURL"]])
                if self.options.include_clips:
                    if self.json_keys["CLIP"] in janson[self.json_keys["FORMAT"]][self.json_keys["VIDEOS"]][str(i)]:
                        for n in janson[self.json_keys["FORMAT"]][self.json_keys["VIDEOS"]][str(i)][self.json_keys["CLIP"]]:
                            videos.append(n[self.json_keys["SHARINGURL"]])

        episodes = []
        for i in videos:
            episodes.append(i)        
        if options.all_last > 0:
            return sorted(episodes[-options.all_last:])
        return sorted(episodes)

    def _autoname(self, dataj):
        program = dataj[self.json_keys["FORMAT_SLUG"]]
        season = None
        episode = None
        title = None

        if self.json_keys["SEASON"] in dataj[self.json_keys["FORMAT_POSITION"]]:
            if dataj[self.json_keys["FORMAT_POSITION"]][self.json_keys["SEASON"]] > 0:
                season = dataj[self.json_keys["FORMAT_POSITION"]][self.json_keys["SEASON"]]
        if season:
            if len(dataj[self.json_keys["FORMAT_POSITION"]][self.json_keys["EPISODE"]]) > 0:
                episode = dataj[self.json_keys["FORMAT_POSITION"]][self.json_keys["EPISODE"]]

        if dataj[self.json_keys["TYPE"]] == "clip":
            #Removes the show name from the end of the filename
            #e.g. Showname.S0X.title instead of Showname.S07.title-showname
            match = re.search(r'(.+)-', dataj["title"])
            if match:
                title = filenamify(match.group(1))
            else:
                title = filenamify(dataj[self.json_keys["TITLE"]])
            if self.json_keys["DERIVED_FROM_ID"] in dataj:
                if self.json_keys[dataj["derived_from_id"]]:
                    parent_id = self.json_keys[dataj["derived_from_id"]]
                    datajparent = self._get_parent_info(parent_id)
                    if datajparent:
                        if not season and datajparent[self.json_keys["FORMAT_POSITION"]][self.json_keys["SEASON"]] > 0:
                            season = datajparent[self.json_keys["FORMAT_POSITION"]][self.json_keys["SEASON"]]
                        if len(datajparent[self.json_keys["FORMAT_POSITION"]][self.json_keys["EPISODE"]]) > 0:
                            episode = datajparent[self.json_keys["FORMAT_POSITION"]][self.json_keys["EPISODE"]]

        name = filenamify(program)
        if season:
            name = "{0}.s{1:02d}".format(name, int(season))
        if episode:
            name = "{0}e{1:02d}".format(name, int(episode))
        if title:
            name = "{0}.{1}".format(name, title)

        return name
        
    def _get_parent_info(self,parent_id):
        datajparent = None
        parent_episode = self.http.request("get", "http://playapi.mtgx.tv/v3/videos/%s" % parent_id)
        if  parent_episode.status_code != 403: #if not geoblocked
            datajparent = json.loads(parent_episode.text)
        return datajparent
       
    def _get_info(self, json):
        data = {}
        
        if json[self.json_keys["FORMAT_TITLE"]]:
            data['show'] = json[self.json_keys["FORMAT_TITLE"]]
            
        # data['title'] = title
        if self.json_keys["BROADCASTS"] in json:
            #TODO add saftey checks here to only get first broadcast 
            data['broadcastDate']= json[self.json_keys["BROADCASTS"]][0][self.json_keys["AIR_AT"]]
            data['publishDate']= json[self.json_keys["BROADCASTS"]][0][self.json_keys["PLAYABLE_FROM"]]
        data['duration'] = ceil(json[self.json_keys["DURATION"]]/60)
        
        if self.json_keys["FORMAT_POSITION"] in json:
            if self.json_keys["IS_EPISODIC"] in json[self.json_keys["FORMAT_POSITION"]]:
                data['season'] = json[self.json_keys["FORMAT_POSITION"]][self.json_keys["SEASON"]]
                data['episode'] = json[self.json_keys["FORMAT_POSITION"]][self.json_keys["EPISODE"]]
                
        if self.json_keys["TYPE"] in json:
            if json[self.json_keys["TYPE"]] == "program":
                data["type"] = 'TV-Show'
            elif json[self.json_keys["TYPE"]] == "clip":
                data['type'] = 'Clip'
                if self.json_keys["TITLE"] in json:
                    #Removes the show name from the end of the filename
                    #e.g. Showname.S0X.title instead of Showname.S07.title-showname
                    match = re.search(r'(.+)-', json[self.json_keys["TITLE"]])
                    if match:
                        title = match.group(1)
                    else:
                        title = json[self.json_keys["TITLE"]]
                    parent_id = dataj[self.json_keys["DERIVED_FROM_ID"]]
                    datajparent = self._get_parent_info(parent_id)
                    if datajparent:
                        if datajparent[self.json_keys["FORMAT_POSITION"]][self.json_keys["SEASON"]] > 0:
                            data[self.json_keys["PARENT_SEASON"]] = datajparent[self.json["format_position"]][self.json_keys["SEASON"]]
                        if len(datajparent[self.json_keys["FORMAT_POSITION"]][self.json_keys["EPISODE"]]) > 0:
                            data[self.json_keys["PARENT_EPISODE"]] = datajparent[self.json_keys["FORMAT_POSITION"]][self.json_keys["EPISODE"]]
                else:
                   data['type'] = json[self.json_keys["TYPE"]]
                   
        if json[self.json_keys["SAMI_PATH"]] or json[self.json_keys["SUBTITLES_FOR_HEARING_IMPAIRED"]] or json[self.json_keys["SUBTITLES_WEBVTT"]]:
            data['subtitle'] = True
        if self.json_keys["SUMMARY"] in json:
            data['description'] = json[self.json_keys["SUMMARY"]]
        if self.json_keys["DESCRIPTION"] in json:
            data["description"]+= "\n" + json[self.json_keys["DESCRIPTION"]]
        return data
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
        "id":"id",
        "seasonNumberOrVideoId":"seasonNumberOrVideoId",
        "videoIdOrEpisodeNumber":"videoIdOrEpisodeNumber",
        "format":"format",
        "videos":"videos",
        "program":"program",
        "episodeNumber":"episodeNumber",
        "seasonNumber":"seasonNumber",
        "msg":"msg",
        "type":"type",
        "sami_path":"sami_path",
        "sami_path":"subtitles_webvtt",
        "sami_path":"subtitles_for_hearing_impaired",
        "sami_path":"sami_path",
        "streams":"streams",
        "medium":"medium",
        "hls":"hls",
        "seasons":"seasons",
        "seasonNumber":"seasonNumber",
        "sharingUrl":"sharingUrl",
        "clip":"clip",
        "format_slug":"format_slug",
        "clip":"clip",
        "format_position":"format_position",
        "title":"title",
        "derived_from_id":"derived_from_id",
        "season":"season",
        "episode":"episode",
        "format_title":"format_title",
        "broadcasts":"broadcasts",
        "air_at":"air_at",
        "playable_from":"playable_from",
        "duration":"duration",
        "is_episodic":"is_episodic",
        "type":"type",
        "description":"description",
        "summary":"summary",
        "subtitles_webvtt":"subtitles_webvtt",
        "subtitles_for_hearing_impaired":"subtitles_for_hearing_impaired",
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
            if self.json_keys["seasonNumberOrVideoId"] in jansson:
                season = jansson[self.json_keys["seasonNumberOrVideoId"]]
                match = re.search("\w-(\d+)$", season)
                if match:
                    season = match.group(1)
            else:
                return False
            if self.json_keys["videoIdOrEpisodeNumber"] in jansson:
                videp = jansson[self.json_keys["videoIdOrEpisodeNumber"]]
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
                    for i in janson[self.json_keys["format"]][self.json_keys["videos"]].keys():
                        if self.json_keys["program"] in janson[self.json_keys["format"]][self.json_keys["videos"]][str(i)]:
                            for n in janson[self.json_keys["format"]][self.json_keys["videos"]][i][self.json_keys["program"]]:
                                if str(n[self.json_keys["episodeNumber"]]) and int(episodenr) == n[self.json_keys["episodeNumber"]] and int(season) == n[self.json_keys["seasonNumber"]]:
                                    return n[self.json_keys["id"]]
                                elif n[self.json_keys["id"]] == episodenr:
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
        if self.json_keys["msg"] in dataj:
            yield ServiceError(dataj[self.json_keys["msg"]])
            return

        if dataj[self.json_keys["type"]] == "live":
            self.options.live = True

        if self.exclude():
            yield ServiceError("Excluding video")
            return
            
        streams = self.http.request("get", "http://playapi.mtgx.tv/v3/videos/stream/%s" % vid)
        if streams.status_code == 403:
            yield ServiceError("Can't play this because the video is geoblocked.")
            return
        streamj = json.loads(streams.text)
        

        if self.json_keys["msg"] in streamj:
            yield ServiceError("Can't play this because the video is either not found or geoblocked.")
            return

        if self.options.output_auto:
            directory = os.path.dirname(self.options.output)
            self.options.service = "viafree"
            basename = self._autoname(dataj)
            title = "%s-%s-%s" % (basename, vid, self.options.service)
            if len(directory):
                self.options.output = os.path.join(directory, title)
            else:
                self.options.output = title
                
        if self.options.get_info:
            video_info = self._get_info(dataj)
            if video_info:
                yield info(copy.copy(self.options),video_info)
                log.info("Collecting info")
            else: 
                log.info("Couldn't get info for this episode")
                
        if dataj[self.json_keys["sami_path"]]:
            if dataj[self.json_keys["sami_path"]].endswith("vtt"):
                subtype = "wrst"
            else:
                subtype = "sami"
            yield subtitle(copy.copy(self.options), subtype, dataj[self.json_keys["sami_path"]])
        if dataj[self.json_keys["subtitles_webvtt"]]:
            yield subtitle(copy.copy(self.options), "wrst", dataj[self.json_keys["subtitles_webvtt"]])
        if dataj["subtitles_for_hearing_impaired"]:
            if dataj[self.json_keys["subtitles_for_hearing_impaired"]].endswith("vtt"):
                subtype = "wrst"
            else:
                subtype = "sami"
            if self.options.get_all_subtitles:
                yield subtitle(copy.copy(self.options), subtype, dataj[self.json_keys["subtitles_for_hearing_impaired"]], "-SDH")
            else: 
                yield subtitle(copy.copy(self.options), subtype, dataj[self.json_keys["subtitles_for_hearing_impaired"]])

        if streamj[self.json_keys["streams"]][self.json_keys["medium"]]:
            filename = streamj[self.json_keys["streams"]][self.json_keys["medium"]]
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

        if streamj[self.json_keys["streams"]][self.json_keys["hls"]]:
            streams = hlsparse(self.options, self.http.request("get", streamj[self.json_keys["streams"]][self.json_keys["hls"]]),streamj[self.json_keys["streams"]][self.json_keys["hls"]])
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
            for i in janson[self.json_keys["format"]][self.json_keys["seasons"]]:
                if season:
                    if int(season) == i[self.json_keys["seasonNumber"]]:
                        seasons.append(i[self.json_keys["seasonNumber"]])
                else:
                    seasons.append(i[self.json_keys["seasonNumber"]])

            for i in seasons:
                if self.json_keys["program"] in janson[self.json_keys["format"]][self.json_keys["videos"]][str(i)]:
                    for n in janson[self.json_keys["format"]][self.json_keys["videos"]][str(i)][self.json_keys["program"]]:
                        videos.append(n[self.json_keys["sharingUrl"]])
                if self.options.include_clips:
                    if self.json_keys["clip"] in janson[self.json_keys["format"]][self.json_keys["videos"]][str(i)]:
                        for n in janson[self.json_keys["format"]][self.json_keys["videos"]][str(i)][self.json_keys["clip"]]:
                            videos.append(n[self.json_keys["sharingUrl"]])

        episodes = []
        for i in videos:
            episodes.append(i)        
        if options.all_last > 0:
            return sorted(episodes[-options.all_last:])
        return sorted(episodes)

    def _autoname(self, dataj):
        program = dataj[self.json_keys["format_slug"]]
        season = None
        episode = None
        title = None

        if self.json_keys["season"] in dataj[self.json_keys["format_position"]]:
            if dataj[self.json_keys["format_position"]][self.json_keys["season"]] > 0:
                season = dataj[self.json_keys["format_position"]][self.json_keys["season"]]
        if season:
            if len(dataj[self.json_keys["format_position"]][self.json_keys["episode"]]) > 0:
                episode = dataj[self.json_keys["format_position"]][self.json_keys["episode"]]

        if dataj[self.json_keys["type"]] == "clip":
            #Removes the show name from the end of the filename
            #e.g. Showname.S0X.title instead of Showname.S07.title-showname
            match = re.search(r'(.+)-', dataj["title"])
            if match:
                title = filenamify(match.group(1))
            else:
                title = filenamify(dataj[self.json_keys["title"]])
            if self.json_keys["derived_from_id"] in dataj:
                if self.json_keys[dataj["derived_from_id"]]:
                    parent_id = self.json_keys[dataj["derived_from_id"]]
                    datajparent = self._get_parent_info(parent_id)
                    if datajparent:
                        if not season and datajparent[self.json_keys["format_position"]][self.json_keys["season"]] > 0:
                            season = datajparent[self.json_keys["format_position"]][self.json_keys["season"]]
                        if len(datajparent[self.json_keys["format_position"]][self.json_keys["episode"]]) > 0:
                            episode = datajparent[self.json_keys["format_position"]][self.json_keys["episode"]]

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
        
        if json[self.json_keys['format_title']]:
            data['show'] = json[self.json_keys['format_title']]
            
        # data['title'] = title
        if self.json_keys["broadcasts"] in json:
            #TODO add saftey checks here to only get first broadcast 
            data['broadcastDate']= json[self.json_keys["broadcasts"]][0][self.json_keys["air_at"]]
            data['publishDate']= json[self.json_keys["broadcasts"]][0][self.json_keys['playable_from']]
        data['duration'] = ceil(json[self.json_keys["duration"]]/60)
        
        if self.json_keys['format_position'] in json:
            if self.json_keys['is_episodic'] in json[self.json_keys["format_position"]]:
                data['season'] = json[self.json_keys["format_position"]][self.json_keys["season"]]
                data['episode'] = json[self.json_keys["format_position"]][self.json_keys["episode"]]
                
        if self.json_keys["type"] in json:
            if json[self.json_keys["type"]] == "program":
                data["type"] = 'TV-Show'
            elif json[self.json_keys["type"]] == "clip":
                data['type'] = 'Clip'
                if self.json_keys["title"] in json:
                    #Removes the show name from the end of the filename
                    #e.g. Showname.S0X.title instead of Showname.S07.title-showname
                    match = re.search(r'(.+)-', json[self.json_keys["title"]])
                    if match:
                        title = match.group(1)
                    else:
                        title = json[self.json_keys["title"]]
                    parent_id = dataj[self.json_keys["derived_from_id"]]
                    datajparent = self._get_parent_info(parent_id)
                    if datajparent:
                        if datajparent[self.json_keys["format_position"]][self.json_keys["season"]] > 0:
                            data[self.json_keys["parent_season"]] = datajparent[self.json["format_position"]][self.json_keys["season"]]
                        if len(datajparent[self.json_keys["format_position"]][self.json_keys["episode"]]) > 0:
                            data[self.json_keys["parent_episode"]] = datajparent[self.json_keys["format_position"]][self.json_keys["episode"]]
                else:
                   data['type'] = json[self.json_keys["type"]]
                   
        if json[self.json_keys["sami_path"]] or json[self.json_keys["subtitles_for_hearing_impaired"]] or json[self.json_keys["subtitles_webvtt"]]:
            data['subtitle'] = True
        if self.json_keys["summary"] in json:
            data['description'] = json[self.json_keys["summary"]]
        if self.json_keys["description"] in json:
            data["description"]+= "\n" + json[self.json_keys["description"]]
        return data
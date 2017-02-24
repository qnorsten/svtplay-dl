# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-
from __future__ import absolute_import
import re
import os
import xml.etree.ElementTree as ET
import copy
import json
import hashlib

from svtplay_dl.log import log
from svtplay_dl.service import Service, OpenGraphThumbMixin
from svtplay_dl.utils import filenamify, is_py2
from svtplay_dl.utils.urllib import urlparse, urljoin, parse_qs
from svtplay_dl.fetcher.hds import hdsparse
from svtplay_dl.fetcher.hls import hlsparse
from svtplay_dl.fetcher.dash import dashparse
from svtplay_dl.subtitle import subtitle
from svtplay_dl.info import info
from svtplay_dl.error import ServiceError
from math import ceil


class Svtplay(Service, OpenGraphThumbMixin):
    supported_domains = ['svtplay.se', 'svt.se', 'beta.svtplay.se', 'svtflow.se']
    # List of json keys used in application 
    # Should only need to update this function on json
    # Format is key_used_in_script: key_from_svtplay
    #TODO add video here? 
    json_keys = {
        "accessService":"accessService",
        "videoTitlePage":"videoTitlePage",
        "programTitle":"programTitle",
        "title":"title",
        "versions":"versions",
        "live":"live",
        "subtitleReferences":"subtitleReferences",
        "format":"format",
        "videoReferences":"videoReferences",
        "url":"url",
        "alt":"alt",
        "audioDescription":"audioDescription",
        "audioDescription":"audioDescription",
        "signInterpretation":"signInterpretation",
        "broadcastDate":"broadcastDate",
        "publishDate":"publishDate",
        "duration":"duration",
        "episodic":"episodic",
        "season":"season",
        "episodeNumber":"episodeNumber",
        "titleType":"titleType",
        "closedCaptioned":"closedCaptioned",
        "programVersionId":"programVersionId",
        "id":"id",
        "gridPage":"gridPage",
        "pagination":"pagination",
        "totalPages":"totalPages",
        "content":"content",
        "contentUrl":"contentUrl",
        "clusterPage":"clusterPage",
        "tabs":"tabs",
        "slug":"slug",
        "clips":"clips",
        "relatedVideosTabs":"relatedVideosTabs",
        "description":"description",
    }
     
    def get(self):
        parse = urlparse(self.url)
        if parse.netloc == "www.svtplay.se" or parse.netloc == "svtplay.se":
            if parse.path[:6] != "/video" and parse.path[:6] != "/klipp":
                yield ServiceError("This mode is not supported anymore. need the url with the video")
                return

        query = parse_qs(parse.query)
        self.access = None
        if self.json_keys["accessService"] in query:
            self.access = query[self.json_keys["accessService"]]

        match = re.search("__svtplay'] = ({.*});", self.get_urldata())
        if not match:
            yield ServiceError("Cant find video info.")
            return
        janson = json.loads(match.group(1))[self.json_keys["videoTitlePage"]]
        
        if self.json_keys["programTitle"] not in janson["video"]:
            yield ServiceError("Can't find any video on that page")
            return

        if self.access:
            for i in janson["video"][self.json_keys["versions"]]:
                if self.json_keys["accessService"] == self.access:
                    url = urljoin("http://www.svtplay.se", i["contentUrl"])
                    res = self.http.get(url)
                    match = re.search("__svtplay'] = ({.*});", res.text)
                    if not match:
                        yield ServiceError("Cant find video info.")
                        return
                    janson = json.loads(match.group(1))[self.json_keys["videoTitlePage"]]
                    
        if self.json_keys["live"] in janson["video"]:
            self.options.live = janson["video"][self.json_keys["live"]]
        
        parsed_info = self._parse_info(janson,True)
        if not parsed_info:
            yield ServiceError("Error parsing info, json keys might have changed?")
            
        if self.options.output_auto:
            self.options.service = "svtplay"
            self.options.output = self.outputfilename(parsed_info, self.options.output)

        if self.exclude():
            yield ServiceError("Excluding video")
            return
        
        if self.options.get_info:
            
            if parsed_info:
                yield info(copy.copy(self.options), parsed_info)
                log.info("Collected info")
            else: 
                log.info("Couldn't collect info for this episode")
                
        if not "vid" in parsed_info :
             yield ServiceError("Could not collect video ID")
           
        res = self.http.get("http://api.svt.se/videoplayer-api/video/{0}".format(parsed_info["vid"]))
        
        janson = res.json()
        if self.json_keys["live"] in janson:
            self.options.live = janson[self.json_keys["live"]]
        if self.json_keys["subtitleReferences"] in janson:
            for i in janson[self.json_keys["subtitleReferences"]]:
                if i[self.json_keys[self.json_keys["format"]]] == "websrt" and "url" in i:
                    yield subtitle(copy.copy(self.options), "wrst", i[self.json_keys["url"]])

        if self.json_keys["videoReferences"] in janson:
            if len(janson[self.json_keys["videoReferences"]]) == 0:
                yield ServiceError("Media doesn't have any associated videos (yet?)")
                return

            for i in janson[self.json_keys["videoReferences"]]:
                parse = urlparse(i[self.json_keys[self.json_keys["url"]]])
                query = parse_qs(parse.query)
                if i[self.json_keys[self.json_keys["format"]]] == "hls":
                    streams = hlsparse(self.options, self.http.request("get", i[self.json_keys["url"]]), i[self.json_keys["url"]])
                    if streams:
                        for n in list(streams.keys()):
                            yield streams[n]
                    if self.json_keys[self.json_keys["alt"]] in query and len(query[self.json_keys[self.json_keys["alt"]]]) > 0:
                        alt = self.http.get(query[self.json_keys[self.json_keys["alt"]]][0])
                        if alt:
                            streams = hlsparse(self.options, self.http.request("get", alt.request.url), alt.request.url)
                            if streams:
                                for n in list(streams.keys()):
                                    yield streams[n]
                if i[self.json_keys["format"]] == "hds":
                    match = re.search(r"\/se\/secure\/", i[self.json_keys["url"]])
                    if not match:
                        streams = hdsparse(self.options, self.http.request("get", i[self.json_keys["url"]], params={"hdcore": "3.7.0"}), i[self.json_keys["url"]])
                        if streams:
                            for n in list(streams.keys()):
                                yield streams[n]
                        if "alt" in query and len(query[self.json_keys["alt"]]) > 0:
                            alt = self.http.get(query[self.json_keys["alt"]][0])
                            if alt:
                                streams = hdsparse(self.options, self.http.request("get", alt.request.url, params={"hdcore": "3.7.0"}), alt.request.url)
                                if streams:
                                    for n in list(streams.keys()):
                                        yield streams[n]
                if i[self.json_keys["format"]] == "dash264" or i[self.json_keys["format"]] == "dashhbbtv":
                    streams = dashparse(self.options, self.http.request("get", i[self.json_keys["url"]]), i[self.json_keys["url"]])
                    if streams:
                        for n in list(streams.keys()):
                            yield streams[n]

                    if self.json_keys["alt"] in query and len(query[self.json_keys["alt"]]) > 0:
                        alt = self.http.get(query[self.json_keys["alt"]][0])
                        if alt:
                            streams = dashparse(self.options, self.http.request("get", alt.request.url), alt.request.url)
                            if streams:
                                for n in list(streams.keys()):
                                    yield streams[n]
    def _parse_info(self, janson,video=False):
        data = {}
        data['signInterpretation'] = False
        data['audiodescription'] = False
        
        #start info intersting for parsing into info file with --get-info
        if self.json_keys["accessService"] in janson:
            if self.json_keys["accessService"] == self.json_keys["audioDescription"]:
                   data['audiodescription'] = True

            if self.json_keys["accessService"] == self.json_keys["signInterpretation"]:
                data['signInterpretation'] = True
                
        if video: 
            janson = janson["video"]
        
        program = janson[self.json_keys["programTitle"]]
        title = janson[self.json_keys["title"]]

        if program != title and program:
            data['show'] = program
            
        data['title'] = title
        
        if self.json_keys["broadcastDate"] in janson:
            data['broadcastDate']= janson[self.json_keys["broadcastDate"]]
        if self.json_keys["publishDate"] in janson:
            data['publishDate'] = janson[self.json_keys["publishDate"]]
        data[self.json_keys['duration']] = ceil(janson["materialLength"]/60)
        if self.json_keys["episodic"] in janson:
            data['season'] = janson[self.json_keys["season"]]
            data['episode'] = janson[self.json_keys["episodeNumber"]]
        if self.json_keys["titleType"] in janson:
            if janson[self.json_keys["titleType"]] == "MOVIE":
                data[self.json_keys["titleType"]] = 'Movie'
            elif janson[self.json_keys["titleType"]] == "SERIES_OR_TV_SHOW":
                data[self.json_keys["titleType"]] = 'TV-Show'
            elif janson[self.json_keys["titleType"]] == "CLIP":
                data['type'] = 'Clip'
            else:
               data['type'] = janson[self.json_keys["titleType"]]
            
            
        if self.json_keys["closedCaptioned"] in janson:
            data['subtitle'] = True
        if self.json_keys["description"] in janson:
            if janson[self.json_keys["description"]]:
                data['description'] = janson[self.json_keys["description"]]
                
        #start data used for internal used
        if self.json_keys["programVersionId"] in janson:
            data["vid"] = janson[self.json_keys["programVersionId"]]
        else:
            data["vid"] = janson[self.json_keys["id"]]
        
        return data
            
    def _last_chance(self, videos, page, maxpage=2):
        if page > maxpage:
            return videos

        res = self.http.get("http://www.svtplay.se/sista-chansen?sida=%s" % page)
        match = re.search("__svtplay'] = ({.*});", res.text)
        if not match:
            return videos

        dataj = json.loads(match.group(1))
        pages = dataj[self.json_keys["gridPage"]][self.json_keys["pagination"]][self.json_keys["totalPages"]]

        for i  in dataj[self.json_keys["gridPage"]][self.json_keys["content"]]:
            videos.append(i[self.json_keys["contentUrl"]])
        page += 1
        self._last_chance(videos, page, pages)
        return videos

    def _genre(self, jansson):
        videos = []
        parse = urlparse(self._url)
        dataj = jansson[self.json_keys["clusterPage"]]
        tab = re.search("tab=(.+)", parse.query)
        if tab:
            tab = tab.group(1)
            for i in dataj[self.json_keys["tabs"]]:
                if i[self.json_keys["slug"]] == tab:
                    videos = self.videos_to_list(i[self.json_keys["content"]], videos)
        else:
            videos = self.videos_to_list(dataj[self.json_keys["clips"]], videos)

        return videos

    def find_all_episodes(self, options):
        parse = urlparse(self._url)
        
        if len(parse.path) > 7 and parse.path[-7:] == "rss.xml":
            match = self.url
        else:
            match = re.search(r'<link rel="alternate" type="application/rss\+xml" [^>]*href="([^"]+)"',
                              self.get_urldata())
            if match:
                match = match.group(1)
            
        if match is None:
            videos = []
            tab = None
            match = re.search("__svtplay'] = ({.*});", self.get_urldata())
            if re.search("sista-chansen", parse.path):
                videos = self._last_chance(videos, 1)
            elif not match:
                log.error("Couldn't retrieve episode list")
                return
            else:
                dataj = json.loads(match.group(1))
                if re.search("/genre", parse.path):
                    videos = self._genre(dataj)
                else:
                    if parse.query: 
                        match = re.search("tab=(.+)", parse.query)
                        if match:
                            tab = match.group(1)

                    items = dataj[self.json_keys["videoTitlePage"]][self.json_keys["relatedVideosTabs"]]
                    for i in items:
                        if tab:
                            if i[self.json_keys["slug"]] == tab:
                                videos = self.videos_to_list(i["videos"], videos)

                        else:
                            if "sasong" in i[self.json_keys["slug"]] or "senast" in i[self.json_keys["slug"]]:
                                videos = self.videos_to_list(i["videos"], videos)

                        if self.options.include_clips: 
                            if i[self.json_keys["slug"]] == "klipp":
                                videos = self.videos_to_list(i["videos"], videos)

            episodes = [urljoin("http://www.svtplay.se", x) for x in videos]
        else:
            data = self.http.request("get", match).content
            xml = ET.XML(data)
            episodes = [x.text for x in xml.findall(".//item/link")]
            
        if options.all_last > 0:
            return sorted(episodes[-options.all_last:])
        return sorted(episodes)

    def videos_to_list(self, lvideos, videos):
        for n in lvideos:
            parse = urlparse(n[self.json_keys["contentUrl"]])
            if parse.path not in videos:
                parsed_info = self._parse_info(n,False)
                filename = self.outputfilename(parsed_info, self.options.output)
                if not self.exclude2(filename):
                    videos.append(parse.path)
            if self.json_keys["versions"] in n:
                for i in n[self.json_keys["versions"]]:
                    parse = urlparse(i[self.json_keys["contentUrl"]])
                    filename = "" # output is None here.
                    if self.json_keys["accessService"] in i:
                        if i[self.json_keys["accessService"]] == self.json_keys["audioDescription"]:
                            filename += "-syntolkat"
                        if i[self.json_keys["accessService"]] == "signInterpretation":
                            filename += "-teckentolkat"
                    if not self.exclude2(filename) and parse.path not in videos:
                        videos.append(parse.path)

        return videos

    def outputfilename(self, data, filename):
        if filename:
            directory = os.path.dirname(filename)
        else:
            directory = ""
        name = None
        if "show" in data:
            name = filenamify(data["show"])
        other = filenamify(data["title"])

        vid = data["vid"]
        
        if is_py2:
            id = hashlib.sha256(vid).hexdigest()[:7]
        else:
            id = hashlib.sha256(vid.encode("utf-8")).hexdigest()[:7]

        if name == other:
            other = None
        elif name is None:
            name = other
            other = None
        season = self.seasoninfo(data)
        title = name
        if season:
            title += ".%s" % season
        if other:
            title += ".%s" % other
        if data["audiodescription"]:
                title += "-syntolkat"
        if data["signInterpretation"]:
                title += "-teckentolkat"
        title += "-%s-svtplay" % id
        title = filenamify(title)
        if len(directory):
            output = os.path.join(directory, title)
        else:
            output = title
        return output

    def seasoninfo(self, data):
        if "season" in data and data["season"]:
            season = "{:02d}".format(data["season"])
            episode = "{:02d}".format(data["episode"])
            if int(season) == 0 and int(episode) == 0:
                return None
            return "S%sE%s" % (season, episode)
        else:
            return None

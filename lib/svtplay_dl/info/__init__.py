from svtplay_dl.log import log
from svtplay_dl.utils import is_py2, is_py3
from svtplay_dl.output import output
import platform


class info(object):
    def __init__(self, options, data, subfix = None):
        self.data = data
        self.options = options
        self.subfix = subfix

    def save_info(self):
        
        if self.subfix:
            self.options.output = self.options.output + self.subfix
        #Might add support for other types here later    
        data = self.raw_txt(self.data)
        self.save_file(data, "txt")
    
    def raw_txt(self, data): 
        text = ''
        if "show" in data:
            text += "Show: %s" % (data['show'])
        if "title" in data:  
            text += "\nTitle: %s" % data['title']
        if "broadcastDate" in data:
            text+= "\nBroadcast Date: %s" % data["broadcastDate"]
        if "publishDate" in data:
            text+= "\nPublishDate Date: %s" % data['publishDate']
        if "duration" in data:
            text+= "\nDuration: %s min" % data['duration']
        if "season" in data:
            text+= "\nSeason: %s" % data['season']
        if "episode" in data:
            text+= "\nEpisode: %s" % data['episode']
        if "type" in data:
            text+="\nType: %s" % data['type']
            
        if "audiodescription" in data:
            text+="Audiodescription: True"
        if "signInterpretation" in data:
            text+="Sign Interpretation: True"
        if "subtitle" in data:
            text+="\nSubtitled: True"
        if "description" in data:
            text+= "\nDescription: " + data["description"]
        return text
    
    def save_file(self, data, subtype):
        if platform.system() == "Windows" and is_py3:
            file_d = output(self.options, subtype, mode="wt", encoding="utf-8")
        else:
            file_d = output(self.options, subtype, mode="wt")
        if hasattr(file_d, "read") is False:
            return
        file_d.write(data)
        file_d.close()
        
        

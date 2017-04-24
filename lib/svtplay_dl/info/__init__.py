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
            text += "Show: %s\n" % (data['show'])
        if "title" in data:  
            text += "Title: %s\n" % data['title']
        if "broadcastDate" in data:
            text+= "Broadcast Date: %s\n" % data["broadcastDate"]
        if "publishDate" in data:
            text+= "PublishDate Date: %s\n" % data['publishDate']
        if "duration" in data:
            text+= "Duration: %s \n" % data['duration']
        if "season" in data:
            text+= "Season: %s\n" % data['season']
        if "episode" in data:
            text+= "Episode: %s\n" % data['episode']
        if "type" in data:
            text+="Type: %s\n" % data['type']
            
        if "audiodescription" in data:
            text+="Audiodescription: True\n"
        if "signInterpretation" in data:
            text+="Sign Interpretation: True\n"
        if "subtitle" in data:
            text+="Subtitled: True\n"
        if "description" in data:
            text+= "Description: " + data["description"]
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
        
        

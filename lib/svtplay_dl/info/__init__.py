from svtplay_dl.log import log
from svtplay_dl.utils import is_py2, is_py3
from svtplay_dl.output import output
import platform


class info(object):
    def __init__(self, options, data, subfix = None):
        self.data = data
        self.options = options
        self.subfix = subfix

    def save(self):
        
        if self.subfix:
            self.options.output = self.options.output + self.subfix
            
        self.save_file(self.data, "txt")
        
    def save_file(self, data, subtype):
        if platform.system() == "Windows" and is_py3:
            file_d = output(self.options, subtype, mode="wt", encoding="utf-8")
        else:
            file_d = output(self.options, subtype, mode="wt")
        if hasattr(file_d, "read") is False:
            return
        file_d.write(data)
        file_d.close()
        
        

import time

class Timer:
    def __init__(self, freq):
        self.frequency = freq
        self.startTime = time.time()
        
    def reset(self):
        self.startTime = time.time()
        
    def fullTimeCheck(self):
        if (time.time() - self.startTime) >= self.frequency:
            self.reset()
            return True
        else:
            return False
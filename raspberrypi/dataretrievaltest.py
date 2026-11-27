import requests
import urllib.parse
import json


LIGHT_THRESHOLD = 800
MAX_LIGHT = 5
WIND_THRESHOLD = (1.72, 1.75)
TEMP_THRESHOLD = 20
SOIL_MOISTURE = 30
CALIBRATION_FACTOR = 7.5


#default modes
manualMode = False
voiceMode = False

manualFan = 'false'
manualLED = 'false'
manualCurtain = 'false'
manualPump = 0.0

getPlantName = "https://studev.groept.be/api/a24ib2team103/retrieve_plantName"
getPlantLimits = "https://studev.groept.be/api/a24ib2team103/get_plant_limits"
getMode = "https://studev.groept.be/api/a24ib2team103/retrieve_automaticmanual"
getManualInstructions = "https://studev.groept.be/api/a24ib2team103/retrieve_manualData"
setModeURL = "https://studev.groept.be/api/a24ib2team103/set_mode"
setErrorMessageURL = "https://studev.groept.be/api/a24ib2team103/set_errorMessage"
class DBsend:
    def __init__(self):
        pass
    
    def make_get_request(self, url, data):  #Make a http get request using a url and an array of data
        try:
            encoded_data = [urllib.parse.quote_plus(str(value)) for value in data]
            url = url+ "/"+"/".join(encoded_data)
            response = requests.get(url)  # Perform the GET request
            response.raise_for_status()  # Raise an error for bad responses (4xx and 5xx)
            return json.loads(response.text)  # Return the response content as a string
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return ""
        
    

    def retrieve_data(self, url):
        
        try: 
            response = requests.get(url)
            response.raise_for_status()
            return self.JSON_parse(response.text)
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return ""
    
    def JSON_parse(self, jsonString):
        return json.loads(jsonString)   
    
    def getDataFromJSON(self, json, index, load):
        return json[index][load]      
        
        
class LimitChecker:
    def __init__(self):
        self.db = DBsend()
        self.plantName = self.db.getDataFromJSON(self.db.retrieve_data(getPlantName),0, 'plantName')
        self.plantLimits = self.db.make_get_request(getPlantLimits, [self.plantName])
        self.manualInstructions = self.db.retrieve_data(getManualInstructions)
        self.mode = self.db.getDataFromJSON(self.db.retrieve_data(getMode),0, 'manual')
        self.voice = self.db.getDataFromJSON(self.db.retrieve_data(getMode),0, 'voice')

    
        
        
    def updPlant(self):
        self.plantName = self.db.getDataFromJSON(self.db.retrieve_data(getPlantName),0, 'plantName')
        return self.plantName
        
        
    def updLimits(self):
        self.updPlant()
        self.plantLimits = self.db.make_get_request(getPlantLimits, [self.plantName])
        return self.plantLimits
    
    def updMode(self):
        global manualMode, voiceMode
        self.mode = self.db.getDataFromJSON(self.db.retrieve_data(getMode),0, 'manual')
        self.voice = self.db.getDataFromJSON(self.db.retrieve_data(getMode),0, 'voice')
        manualMode = self.mode
        voiceMode = self.voice
        print(self.mode)
        print(self.voice)

    def updManual(self):
        self.manualInstructions = self.db.retrieve_data(getManualInstructions)
        return self.manualInstructions
        

def updateLims():
    global TEMP_THRESHOLD, SOIL_MOISTURE, LIGHT_THRESHOLD, MAX_LIGHT                
    limList = limChecker.updLimits()   

    TEMP_THRESHOLD = limChecker.db.getDataFromJSON(limList,0, 'max_temp')                 #Update the global plant limits based on JSON List retrieved from database
    SOIL_MOISTURE = limChecker.db.getDataFromJSON(limList,0, 'soil_humidity')             
    LIGHT_THRESHOLD = limChecker.db.getDataFromJSON(limList,0, 'light_intensity')
    MAX_LIGHT = limChecker.db.getDataFromJSON(limList,0, 'hours_of_light')

def checkMode():
    limChecker.updMode()                     #Return whether it is in manual or automatic mode
                                                    #Returns 'true' if manual, 'false' if automatic. Note this is as a string, not a boolean I believe     
  
def manualInstructions():
    global manualPump, manualCurtain, manualFan, manualLED
    manualList = limChecker.updManual()
    manualFan = limChecker.db.getDataFromJSON(manualList,0,'value')
    manualLED = limChecker.db.getDataFromJSON(manualList,1,'value')
    manualCurtain = limChecker.db.getDataFromJSON(manualList,2,'value')
    manualPump = limChecker.db.getDataFromJSON(manualList,3,'value')
        

def setMode(manual, voice):
    list = [manual, voice]
    limChecker.db.make_get_request(setModeURL,list)
     

def setErrorMessage(trueOrFalse, errorMessage): #must be string 'true' or 'false' 
    list = ['true', trueOrFalse, errorMessage]
    limChecker.db.make_get_request(setErrorMessageURL, list)

limChecker = LimitChecker()

setErrorMessage('true', "i am an error")
# print("old limits")
# print(TEMP_THRESHOLD)
# print(SOIL_MOISTURE)
# print(LIGHT_THRESHOLD)
# print(MAX_LIGHT)
# print("--------------")
# setMode("true","false")
# print("updating lims:")
# updateLims()
# checkMode()
# print("new limits")
# print(TEMP_THRESHOLD)
# print(SOIL_MOISTURE)
# print(LIGHT_THRESHOLD)
# print(MAX_LIGHT)
# print("--------------")


# print(manualFan)
# print(manualLED)
# print(manualCurtain)
# print(manualPump)
# print("--------------")
# manualInstructions()
# print(manualFan)
# print(manualLED)
# print(manualCurtain)
# print(manualPump)
# print("--------------")
                                                    
                                                    

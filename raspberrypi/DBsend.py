import requests

class DBsend:
    def __init__(self):
        pass
    
    def make_get_request(self, url, data):  #Make a http get request using a url and an array of data
        try:
            string = ""
            for value in data:
                string = string + "/" + value  
            url = url + string
            response = requests.get(url)  # Perform the GET request
            response.raise_for_status()  # Raise an error for bad responses (4xx and 5xx)
            return response.text  # Return the response content as a string
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return ""


#Example, send data 22, 70 to light table in DB        
getRequest = DBsend()
url = "https://studev.groept.be/api/a24ib2team103/insert_in_light"
data = ["2025-03-19%2017:33:17", "70", "3"]  # Directly defining list
getRequest.make_get_request(url, data)  # No more TypeError



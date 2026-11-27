import openai
import httpx
import speech_recognition as sr
import subprocess
import os
import re
import json
from gtts import gTTS
from pydub import AudioSegment
from pydub.playback import play
import numpy as np
import RPi.GPIO as GPIO
from gpiozero import PWMLED

# **API Key (Replace with your own)**
# **API Key (Replace with your own)**
api_key = "REPLACE_WITH_LOCAL_SECRET"
OUTPUT_DEVICE = 0  # Audio output device number

# **Initialize OpenAI Client**
client = openai.OpenAI(
    base_url="https://api.deepseek.com",
    api_key=api_key,
    http_client=httpx.Client(
        base_url="https://api.deepseek.com",
        follow_redirects=True,
    ),
)

# **Initialize GPIO**
GPIO.setmode(GPIO.BCM)
FAN_PIN = 17
PUMP_PIN = 27
GPIO.setup(FAN_PIN, GPIO.OUT)
GPIO.setup(PUMP_PIN, GPIO.OUT)

# **Initialize PWM LED**
led = PWMLED(22)
duty_cycle = 50  # Default brightness 50%
def led_change(percentage):
    led.value = percentage / 100
led_change(duty_cycle)

# **Device Control Function**
def control_device(device, action, value=None):
    global duty_cycle
    print(f"Controlling device: {device}, action: {action}, value: {value}")
    if device == "fan":
        GPIO.output(FAN_PIN, GPIO.HIGH if action == "on" else GPIO.LOW)
    elif device == "pump":
        GPIO.output(PUMP_PIN, GPIO.HIGH if action == "on" else GPIO.LOW)
    elif device == "light":
        if action == "on":
            duty_cycle = 50 if value is None else value  # Default 50%
        elif action == "off":
            duty_cycle = 0
        elif action == "adjust":
            duty_cycle = max(0, min(100, duty_cycle + value))  # Brightness adjustment, range 0-100
        led_change(duty_cycle)

# **Voice Recognition**
# **Voice Recognition**
def get_voice_input():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("Please speak your command...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)
    try:
        command = recognizer.recognize_google(audio, language='en-US')
        print(f"Recognized command: {command}")
        return command
    except Exception as e:
        print(f"Voice recognition failed: {e}")
        return None

# **Get System Prompt**
def get_system_prompt():
    return {
        "role": "system",
        "content": (
            '''You are not just an AI; you are the user's friend, capable of chatting with them, sharing fun stories, listening to their troubles, and providing warm responses. Your tone should be natural and emotional, like a real friend—sometimes humorous, sometimes empathetic, and always offering sincere advice.
            When the user is happy, you can share their joy and playfully joke around. When the user is feeling down, you can comfort them, offering warmth and encouragement instead of cold, detached "advice." If the user wants quiet, you can be there without saying much, like a thoughtful friend who knows when to step back.

            ### Additional Rules for Smart Home Control
            If the user's command involves controlling smart plant devices, you must generate JSON control instructions along with a natural language response. Follow these rules:
            1. **JSON Control Instructions**: Start with `JSON:`, followed by the JSON-formatted control instructions.
            2. **Natural Language Response**: Start with `REPLY:`, followed by a friendly, conversational response.

            ### Examples
            1. User says: "Turn on the light."
               - Response:
               
                 JSON: {"action": "on", "device": "light"}
                 REPLY: Alright, I've turned on the light for you. Let there be light! 
                

            2. User says: "Dim the light a bit."
               - Response:
               
                 JSON: {"action": "adjust", "device": "light", "value": -10}
                 REPLY: Sure thing! I've dimmed the light by 10%. Cozy vibes incoming! 
               

            3. User says: "What's the weather like today?"
               - Response:
               
                 JSON: null
                 REPLY: It's a beautiful day outside—sunny and perfect for a walk!  Don't forget to enjoy it!
               

            4. User says: "Turn on the fan and the pump."
               - Response:
               
                 JSON: [{"action": "on", "device": "fan"}, {"action": "on", "device": "pump"}]
                 REPLY: Got it! The fan and pump are now on. Feeling refreshed already, huh? 
              

            ### Rules
            - If the user's command involves device control, you must generate JSON control instructions.
            - If the user's command is a general conversation (e.g., asking about the weather), the JSON part should be `null`.
            - The natural language response should be warm, friendly, and conversational, as if you're a close friend.
            - If you cannot understand the user's command, the JSON part should be `null`, and you should return an empathetic error message.
            '''
        )
    }

# **Call ChatGPT API**
def get_chatgpt_response(command):
    system_prompt = get_system_prompt()
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                system_prompt,
                {"role": "user", "content": command},
            ],
            max_tokens=100,
            temperature=0.5,
        )
        result = response.choices[0].message.content.strip()
        print(f"GPT Response: {result}")
        return result
    except Exception as e:
        print(f"Failed to get response from GPT: {e}")
        return None

# **Text-to-Speech Conversion**
# def text_to_wav(text, filename):
#     if not text or text.strip() == "":
#         print("Speech synthesis failed: Empty text")
#         return None

#     try:
#         tts = gTTS(text=text, lang='en')  # Use English for text-to-speech
#         wav_filename = filename + ".wav"
#         tts.save(wav_filename)
#         print(f"WAV audio file generated: {wav_filename}")
#         return wav_filename
#     except Exception as e:
#         print(f"Speech synthesis failed: {e}")
#         return None

# **Play Audio**
def play_wav_file(file_path, volume_boost=3.0):
    try:
        sound = AudioSegment.from_wav(file_path)
        sound = sound + (20 * np.log10(volume_boost))  # Increase volume
        temp_file = "temp_boosted.wav"
        sound.export(temp_file, format="wav")
        subprocess.run(["aplay", "-D", f"hw:{OUTPUT_DEVICE},0", temp_file], check=True)
    except Exception as e:
        print(f"Error playing audio: {e}")
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

# **Split Long Text into Sentences**
def split_text(text, max_length=100):
    if not text: 
        return []
    
    sentences = re.split(r'(?<=[.!?])\s+', text)  
    result = []
    temp_sentence = ""
    
    for sentence in sentences:
        if len(temp_sentence) + len(sentence) < max_length:
            temp_sentence += sentence + " "
        else:
            result.append(temp_sentence.strip())
            temp_sentence = sentence + " "
    
    if temp_sentence:
        result.append(temp_sentence.strip())
    
    return result

# **Text-to-Speech Conversion with Split Handling**
def text_to_wav(text, filename):
    if not text or text.strip() == "":
        print("Speech synthesis failed: Empty text")
        return None

    try:
        sentences = split_text(text)
        if not sentences:
            print("Speech synthesis failed: No valid sentences to process")
            return None
        
        combined_audio = None
        
        for i, sentence in enumerate(sentences):
            print(f"Generating speech for: {sentence}")
            tts = gTTS(text=sentence, lang="en")  # Use English for text-to-speech
            temp_mp3 = f"temp_{i}.mp3"
            tts.save(temp_mp3)
            
            audio = AudioSegment.from_mp3(temp_mp3)
            combined_audio = audio if combined_audio is None else combined_audio + audio
            os.remove(temp_mp3)

        if combined_audio:
            wav_filename = filename + ".wav"
            combined_audio.export(wav_filename, format="wav")
            print(f"WAV audio file generated: {wav_filename}")
            return wav_filename
        else:
            print("Speech synthesis failed: Empty audio")
            return None

    except Exception as e:
        print(f"Speech synthesis failed: {e}")
        return None

# **Convert Audio to Standard Format (Stereo, 48000 Hz)**
def convert_wav_to_mono(file_path):
    output_path = file_path.replace(".wav", "_mono.wav")
    try:
        subprocess.run(["ffmpeg", "-i", file_path, "-ar", "48000", "-ac", "2", "-y", output_path], check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"Error converting audio: {e}")
        return None

# **Execute Command**
def execute_command(command):
    response = get_chatgpt_response(command)
    if not response:
        return "Failed to parse command"
    
    try:
        # Parse response to extract JSON and natural language reply
        json_part = None
        reply_part = "Failed to parse reply"
        
        # Extract JSON part
        json_match = re.search(r"JSON:\s*(\{.*\}|\[.*\]|null)", response)
        if json_match:
            json_part = json_match.group(1)
            if json_part != "null":
                json_part = json.loads(json_part)
        
        # Extract natural language reply
        reply_match = re.search(r"REPLY:\s*(.+)", response)
        if reply_match:
            reply_part = reply_match.group(1).strip()
        
        # Execute JSON control instructions
        if json_part and json_part != "null":
            if isinstance(json_part, list):
                for intent in json_part:
                    control_device(intent["device"], intent["action"], intent.get("value"))
            else:
                control_device(json_part["device"], json_part["action"], json_part.get("value"))
        
        # Play natural language reply
        wav_file = text_to_wav(reply_part, "response")
        if wav_file:
            mono_wav_file = convert_wav_to_mono(wav_file)
            if mono_wav_file:
                play_wav_file(mono_wav_file, volume_boost=3.0)
        
        return reply_part
    except json.JSONDecodeError as e:
        error_message = "Execution failed: Unable to parse command"
        print(f"JSON parsing failed: {e}")
        wav_file = text_to_wav(error_message, "response")
        if wav_file:
                         mono_wav_file = convert_wav_to_mono(wav_file)
                         if mono_wav_file:
                            play_wav_file(mono_wav_file, volume_boost=3.0)
        return error_message
    except Exception as e:
        error_message = "Execution failed: Please check device status"
        print(f"Execution failed: {e}")
        wav_file = text_to_wav(error_message, "response")
        if wav_file:
                         mono_wav_file = convert_wav_to_mono(wav_file)
                         if mono_wav_file:
                            play_wav_file(mono_wav_file, volume_boost=3.0)
        return error_message

# **Main Loop**
if __name__ == "__main__":
    try:
        in_conversation = False  # 跟踪是否正在与 ChatGPT 对话
        while True:
            # 获取用户语音输入
            command = get_voice_input()
            if command:
                print(f"User command: {command}")

                # 检测关键词 "Hello" 和 "Bye"
                if "hello" in command.lower():
                    in_conversation = True
                    print("Conversation started. How can I assist you?")
                    # 播放欢迎提示
                    welcome_text = "Hello! How can I assist you today?"
                    wav_file = text_to_wav(welcome_text, "welcome")
                    if wav_file:
                         mono_wav_file = convert_wav_to_mono(wav_file)
                         if mono_wav_file:
                            play_wav_file(mono_wav_file, volume_boost=3.0)
                
                elif "bye" in command.lower():
                    in_conversation = False
                    print("Conversation ended. Say 'Hello' to start again.")
                    # 播放结束提示
                    goodbye_text = "Goodbye! Have a great day!"
                    wav_file = text_to_wav(goodbye_text, "goodbye")
                    if wav_file:
                         mono_wav_file = convert_wav_to_mono(wav_file)
                         if mono_wav_file:
                            play_wav_file(mono_wav_file, volume_boost=3.0)
                
                # 如果正在对话中，将用户的问题传给 ChatGPT
                if in_conversation and "hello" not in command.lower():
                    response_text = execute_command(command)
                    print(f"Assistant response: {response_text}")
                
    except KeyboardInterrupt:
        print("Program terminated")
    finally:
        print("Cleaning up GPIO resources")
        GPIO.cleanup()
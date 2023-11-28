from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import serial
from enum import Enum
import netifaces as ni

import os
import subprocess

from typing import Callable
from threading import Thread, Lock
import re
import json
from pathlib import Path
from src.gpt import Gpt
from src.tts import Tts
from src.plugin.weather import get_weather
from src.plugin.clock import get_time

usb_port = '/dev/ttyUSB1'

def concurrent(fn: Callable) -> Callable[..., None]:
    """Decorator to run a function in a new thread."""
    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
    return wrapper


class AudioPlayer:
    def __init__(self):
        self.process = None
        self.playing = False

    @concurrent
    def load_and_play_once(self, filename):
        self.process = subprocess.Popen(
            ['aplay', '-D', 'hw:2,0', filename],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


    @concurrent
    def load_and_play_in_loop(self, filename):
        if self.process:
            return
        self.playing = True
        while self.playing:
            self.process = subprocess.Popen(['aplay', '-D', 'hw:2,0', filename])
            self.process.wait()
            self.process = None

    def stop(self):
        self.playing = False

        if self.process is not None:
            self.process.terminate()


class ArduinoMegaUart:
    def __init__(self):
        self.ser = serial.Serial(usb_port, 115200)

    def __call__(self, data_to_send: str):
        self.ser.write(data_to_send.encode())

    def close(self):
        self.ser.close()


class WheelController:
    bt_data = {
        "forward": "A",
        "forward-left": "H",
        "forward-right": "B",
        "left": "d",
        "right": "b",
        "backward": "E",
        "backward-left": "F",
        "backward-right": "D",
        "stop": "Z",
        "rotate-clockwise": "C",
        "rotate-anticlockwise": "G",
        "tracing": "U",
    }
    def __init__(self, uart: ArduinoMegaUart):
        self.uart = uart

    def __call__(self, command: str):

        if command in self.bt_data.values():
            self.uart(command)
        else:
            raise ValueError(f"Invalid command: {command}")

def parse_detection_data(text):
    detections = text.split('<detectNet.Detection object>')[1:]

    parsed_detections = []
    for detection in detections:
        data = re.findall(r'-- (\w+): +([\d.]+|[\(\)\d. ,]+)', detection)

        detection_dict = {}
        for key, value in data:
            if key in ['Left', 'Top', 'Right', 'Bottom', 'Width', 'Height', 'Area']:
                value = float(value)
            elif key == 'Center':
                value = tuple(map(float, value.strip('()').split(',')))
            elif key == 'ClassID':
                value = int(value)
            detection_dict[key] = value

        parsed_detections.append(detection_dict)

    return parsed_detections

def add_class_name(object_array, class_name_mapping):
    return [{'class': class_name_mapping[obj['ClassID']], **obj} for obj in object_array]

def detections_to_json():
    input_text = Path('/home/nvidia/example.txt').read_text()
    class_name_mapping = Path('./src/assets/ssd_coco_labels.txt').read_text().split('\n')
    detections = parse_detection_data(input_text)
    detections = add_class_name(detections, class_name_mapping)
    json_output = json.dumps(detections, indent=4)
    return json_output


app = FastAPI()

app = FastAPI(debug=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

arduino_mega_uart = ArduinoMegaUart()
wheel_controller = WheelController(arduino_mega_uart)
audio_player = AudioPlayer()
warning_player = AudioPlayer()

summarization_gpt = Gpt("summarization")
weather_gpt = Gpt("weather")
time_gpt = Gpt("time")
tts_model = Tts()

# @concurrent
def speak_time():
    time = get_time()
    time_summarization = time_gpt("what time is it? " + time)
    tts_model(time_summarization)

# @concurrent
def speak_image():
    json = detections_to_json()
    detection_summarization = summarization_gpt("please summarize this json. " + json)
    tts_model(detection_summarization)

# @concurrent
def speak_weather():
    weather_json = get_weather()
    weather_summarization = weather_gpt("please summarize this json. " + weather_json)
    tts_model(weather_summarization)

@app.get("/")
async def test_connection():
    return {"status": "okay"}

@app.get("/test/{command}")
async def test_uart(command: str):
    if command == "P":
        audio_player.load_and_play_in_loop('./ring.wav')
    elif command == "Q":
        audio_player.stop()
    elif command == "W":
        warning_player.load_and_play_in_loop('./proximity.wav')
        wheel_controller('Z')
    elif command == "S":
        warning_player.stop()
    elif command == "K":
        speak_image()
    elif command == "R":
        speak_weather()
    elif command == "T":
        speak_time()
    else:
        wheel_controller(command)
    return {"status": "okay"}

if __name__ == '__main__':
    # audio_player.load_and_play_in_loop('./ring.wav')
    # time.sleep(3000)
    ip = ni.ifaddresses('wlan0')[ni.AF_INET][0]['addr']
    uvicorn.run("main:app", host=ip, port=8000)

import Jetson.GPIO as GPIO
import time
from typing import Callable
from threading import Thread, Lock
import subprocess
import requests

clear_line = "\r" + " " * 80 + "\r"
echoPin = 11
trigPin = 12

start_time = 0
done = True
distance_in_cm = 0
last_triggered = None

is_playing = False

jetson_nano_ip = "10.68.175.42:8000"


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
        self.lock = Lock()  # Add a lock for synchronization

    @concurrent
    def load_and_play_in_loop(self, filename):
        with self.lock:
            if self.playing:
                return  # Avoid starting a new process if already playing
            self.playing = True

        while self.playing:
            with self.lock:
                if self.process:
                    self.process.terminate()
                self.process = subprocess.Popen(['aplay', '-D', 'hw:2,0', filename])
            self.process.wait()

    def stop(self):
        with self.lock:
            self.playing = False
            if self.process:
                self.process.terminate()
                self.process = None


audio_player = AudioPlayer()
forced_stoped = False

def setup():
    GPIO.setmode(GPIO.BOARD)  # Use physical pin numbering
    GPIO.setup(echoPin, GPIO.IN)
    GPIO.setup(trigPin, GPIO.OUT)

def measure_distance():
    global start_time, done, distance_in_cm

    if done:
        done = False
        start_time = time.time()
        GPIO.output(trigPin, GPIO.LOW)

    if time.time() > start_time + 0.002:
        GPIO.output(trigPin, GPIO.HIGH)

    if time.time() > start_time + 0.010:
        GPIO.output(trigPin, GPIO.LOW)
        start_time_echo = time.time()
        end_time_echo = time.time()
        while GPIO.input(echoPin) == 0:
            start_time_echo = time.time()

        while GPIO.input(echoPin) == 1:
            end_time_echo = time.time()

        duration = end_time_echo - start_time_echo
        distance_in_cm = (duration * 34300) / 2  # Speed of sound at 34300 cm/s
        done = True

def loop():
    global distance_in_cm, last_triggered, is_playing, forced_stoped
    measure_distance()
    warning_distance = 15

    if distance_in_cm < warning_distance:
            # requests.get(f"http://{jetson_nano_ip}/test/Z")
        requests.get(f"http://{jetson_nano_ip}/test/W")
        if not forced_stoped:
            forced_stoped = True
    elif distance_in_cm >= warning_distance:
        if forced_stoped:
            requests.get(f"http://{jetson_nano_ip}/test/S")
            forced_stoped = False

    print(clear_line + str(distance_in_cm), end='\r')

setup()
try:
    while True:
        loop()
        time.sleep(0.05)
except KeyboardInterrupt:
    GPIO.cleanup()

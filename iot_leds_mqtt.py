import RPi.GPIO as GPIO
import time, json, ssl
from tinydb import TinyDB
from datetime import datetime
import paho.mqtt.client as mqtt

# ===== Pins (BCM) =====
PIR_PIN = 17          # PIR OUT
DOOR_PIN = 27         # Reed switch NO -> GPIO27, COM -> 3.3V
LED_MOTION = 22       # LED for motion
LED_DOOR = 23         # LED for door open

# ===== MODE: set True to publish to AWS, False for local mosquitto =====
USE_AWS = True

# ===== MQTT config (LOCAL) =====
MQTT_HOST = "localhost"
MQTT_PORT = 1883

# ===== MQTT config (AWS) =====
AWS_ENDPOINT = "a34tg0ldi880qv-ats.iot.us-east-2.amazonaws.com"  # <-- put yours
CERT_DIR = "/home/rinotruc/pi/certs"                                       # <-- adjust if needed
AWS_CA   = f"{CERT_DIR}/AmazonRootCA1.pem"
AWS_CERT = f"{CERT_DIR}/c3399abafc08ec0e999c2974b310039e7c2acbfa70955008670ce90429bc5734-certificate.pem.crt"
AWS_KEY  = f"{CERT_DIR}/c3399abafc08ec0e999c2974b310039e7c2acbfa70955008670ce90429bc5734-private.pem.key"
AWS_PORT = 8883

TOPIC_TELEMETRY = "doorlock/group11/telemetry"
CLIENT_ID = "pi5"

# ===== Setup GPIO =====
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIR_PIN, GPIO.IN)
GPIO.setup(DOOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(LED_MOTION, GPIO.OUT)
GPIO.setup(LED_DOOR, GPIO.OUT)

# ===== DB =====
db = TinyDB('events.json')

# ===== MQTT client =====
client = mqtt.Client(client_id=CLIENT_ID, clean_session=True)

if USE_AWS:
    client.tls_set(
        ca_certs=AWS_CA,
        certfile=AWS_CERT,
        keyfile=AWS_KEY,
        tls_version=ssl.PROTOCOL_TLSv1_2,
    )
    client.connect(AWS_ENDPOINT, AWS_PORT, keepalive=60)
else:
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)

# optional: background network loop (more robust reconnect/keepalive)
client.loop_start()

def ts():
    return datetime.utcnow().isoformat() + "Z"

def publish_state(motion, door_closed):
    payload = {
        "ts": ts(),
        "device_id": CLIENT_ID,
        "motion": "motion" if motion else "clear",
        "door": "closed" if door_closed else "open"
    }
    db.insert(payload)  # local log
    client.publish(TOPIC_TELEMETRY, json.dumps(payload), qos=0, retain=False)
    print("Published:", payload)

print("Stabilizing PIR...")
time.sleep(5)
print(("AWS" if USE_AWS else "LOCAL") + " mode ? publishing on", TOPIC_TELEMETRY)

last_motion = None
last_door = None

try:
    # prime state
    last_motion = GPIO.input(PIR_PIN)
    last_door = GPIO.input(DOOR_PIN)
    publish_state(last_motion, last_door)

    while True:
        motion = GPIO.input(PIR_PIN)
        door_closed = GPIO.input(DOOR_PIN)

        # LED logic
        GPIO.output(LED_MOTION, GPIO.HIGH if motion else GPIO.LOW)
        GPIO.output(LED_DOOR, GPIO.HIGH if not door_closed else GPIO.LOW)  # ON if door open

        if motion != last_motion or door_closed != last_door:
            last_motion, last_door = motion, door_closed
            publish_state(motion, door_closed)

        time.sleep(0.05)

except KeyboardInterrupt:
    pass
finally:
    GPIO.output(LED_MOTION, GPIO.LOW)
    GPIO.output(LED_DOOR, GPIO.LOW)
    GPIO.cleanup()
    client.loop_stop()
    client.disconnect()
    print("\nStopped.")


import time
import json
import ssl
from datetime import datetime

import cv2
import numpy as np
from picamera2 import Picamera2
import paho.mqtt.client as mqtt
from tinydb import TinyDB
import RPi.GPIO as GPIO

# ================== GPIO PINS ==================
PIR_PIN    = 17   # PIR OUT
DOOR_PIN   = 27   # Reed switch NO -> GPIO27, COM -> 3.3V
LED_MOTION = 22   # LED for motion
LED_DOOR   = 23   # LED for "authorized open"
LED_FACE   = 24   # LED for "known face detected"

# ================== MQTT / AWS CONFIG ==================
USE_AWS      = True   # False = local mosquitto, True = AWS IoT

MQTT_HOST    = "localhost"
MQTT_PORT    = 1883

AWS_ENDPOINT = "a34tg0ldi880qv-ats.iot.us-east-2.amazonaws.com"
CERT_DIR     = "/home/rinotruc/pi/certs"
AWS_CA       = f"{CERT_DIR}/AmazonRootCA1.pem"
AWS_CERT     = f"{CERT_DIR}/c3399abafc08ec0e999c2974b310039e7c2acbfa70955008670ce90429bc5734-certificate.pem.crt"
AWS_KEY      = f"{CERT_DIR}/c3399abafc08ec0e999c2974b310039e7c2acbfa70955008670ce90429bc5734-private.pem.key"
AWS_PORT     = 8883

TOPIC        = "doorlock/group11/telemetry"
CLIENT_ID    = "pi5"
DEVICE_ID    = "rpi5-group11"
# Access logic: how long after a known face we still consider door "authorized"
ACCESS_WINDOW = 5.0  # seconds

# ================== GPIO SETUP ==================
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIR_PIN, GPIO.IN)
GPIO.setup(DOOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(LED_MOTION, GPIO.OUT)
GPIO.setup(LED_DOOR, GPIO.OUT)
GPIO.setup(LED_FACE, GPIO.OUT)

GPIO.output(LED_MOTION, GPIO.LOW)
GPIO.output(LED_DOOR, GPIO.LOW)
GPIO.output(LED_FACE, GPIO.LOW)

# ================== DB + MQTT CLIENT ==================
db = TinyDB("events.json")

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

client.loop_start()

def ts():
    # You can ignore the deprecation warning; it's fine for class.
    return datetime.utcnow().isoformat() + "Z"

# ================== LOAD MODELS ==================
print("Loading models...")
DETECTOR = cv2.dnn.readNetFromCaffe(
    "models/deploy.prototxt",
    "models/res10_300x300_ssd_iter_140000.caffemodel",
)
EMB = cv2.dnn.readNetFromONNX("models/face_recognition_sface_2021dec.onnx")

# ================== LOAD TEMPLATES (ROBUST) ==================
with open("templates/templates.json") as f:
    templates_raw = json.load(f)

# Support both:
# - old format: "name": [0.1, 0.2, ...]
# - new format: "name": [[0.1, 0.2, ...], [...], ...]
TEMPLATES = {}
for name, emb_list in templates_raw.items():
    if not emb_list:
        continue

    # If first element is a number -> old single-vector format
    if isinstance(emb_list[0], (int, float)):
        vecs = [np.array(emb_list, dtype=np.float32)]
    else:
        # list-of-list format
        vecs = [np.array(e, dtype=np.float32) for e in emb_list]

    # Normalize each embedding
    normed_vecs = []
    for v in vecs:
        v = v.astype(np.float32)
        n = np.linalg.norm(v) + 1e-8
        normed_vecs.append(v / n)

    TEMPLATES[name] = normed_vecs

ENROLLED = list(TEMPLATES.keys())
print("Enrolled users:", ENROLLED if ENROLLED else "[none]")
for name, emb_list in TEMPLATES.items():
    print(f"  {name}: {len(emb_list)} embeddings, dim={emb_list[0].shape[0]}")

# ================== FACE UTILS ==================
def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(
        np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8)
    )

def emb_from_crop(bgr: np.ndarray) -> np.ndarray:
    face = cv2.cvtColor(cv2.resize(bgr, (112, 112)), cv2.COLOR_BGR2RGB).astype(np.float32)
    blob = cv2.dnn.blobFromImage(
        face,
        scalefactor=1.0/255.0,
        size=(112, 112),
        swapRB=False
    )
    EMB.setInput(blob)
    e = EMB.forward().reshape(-1).astype(np.float32)
    norm = np.linalg.norm(e) + 1e-8
    return e / norm

def detect_faces(frame: np.ndarray):
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)),
        1.0,
        (300, 300),
        (104, 177, 123),
    )
    DETECTOR.setInput(blob)
    dets = DETECTOR.forward()
    faces = []
    for i in range(dets.shape[2]):
        conf = float(dets[0, 0, i, 2])
        if conf > 0.6:
            x1, y1, x2, y2 = (dets[0, 0, i, 3:7] * np.array([w, h, w, h])).astype(int)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 > x1 and y2 > y1:
                faces.append((x1, y1, x2, y2, conf))
    return faces
def publish_sensor_state(motion, door_closed, authorized_open, user):
    payload = {
        "ts": ts(),
        "device_id": DEVICE_ID,
        "motion": "motion" if motion else "clear",
        "door": "closed" if door_closed else "open",
        "auth": "authorized" if authorized_open else "unauthorized",
        "auth_user": user if authorized_open else None,
    }
    db.insert(payload)
    client.publish(TOPIC, json.dumps(payload), qos=0, retain=False)
    print("Sensor:", payload)

def publish_face_event(event: str, user: str, sim: float):
    payload = {
        "ts": ts(),
        "device_id": DEVICE_ID,
        "event": event,     # "face_ok", "ambiguous", or "unknown"
        "user": user,
        "sim": round(sim, 3),
    }
    client.publish(TOPIC, json.dumps(payload), qos=1, retain=False)
    print("Face:", payload)

# ================== CAMERA SETUP ==================
picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "RGB888"}
))
picam2.start()
time.sleep(0.2)

THRESH = 0.90   # similarity threshold for "known"
MARGIN = 0.03   # required gap between best and second-best

face_cooldown_until = 0.0

# State for access & face LED logic
last_face_ok_time = 0.0
last_known_user = None
face_led_until = 0.0

print("Stabilizing PIR...")
time.sleep(5)
print(("AWS" if USE_AWS else "LOCAL") + " mode, publishing on", TOPIC)
print("System ready. Press 'q' to quit.")
# Prime sensor state
last_motion = GPIO.input(PIR_PIN)
last_door   = GPIO.input(DOOR_PIN)
last_auth   = False
publish_sensor_state(last_motion, last_door, last_auth, last_known_user)

try:
    while True:
        now = time.time()

        # ----------- SENSOR LOGIC -----------
        motion = GPIO.input(PIR_PIN)
        door_closed = GPIO.input(DOOR_PIN)

        # Is door open AND we saw a known face recently?
        authorized_open = (not door_closed) and (now - last_face_ok_time <= ACCESS_WINDOW)

        # LED_MOTION = motion indicator
        GPIO.output(LED_MOTION, GPIO.HIGH if motion else GPIO.LOW)
        # LED_DOOR = authorized-open indicator
        GPIO.output(LED_DOOR, GPIO.HIGH if authorized_open else GPIO.LOW)

        # Auto turn-off for face LED
        if now > face_led_until:
            GPIO.output(LED_FACE, GPIO.LOW)

        if (motion != last_motion) or (door_closed != last_door) or (authorized_open != last_auth):
            last_motion, last_door, last_auth = motion, door_closed, authorized_open
            publish_sensor_state(motion, door_closed, authorized_open, last_known_user)

        # ----------- CAMERA + FACE RECOGNITION -----------
        rgb = picam2.capture_array()
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        faces = detect_faces(frame)

        for (x1, y1, x2, y2, conf) in faces:
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            e = emb_from_crop(crop)

            best_name = "unknown"
            best_sim = 0.0
            second_sim = 0.0

            # Optional debug: per-user max sim
            # debug_line = []

            for name, vecs in TEMPLATES.items():
                sims = [cosine(e, v) for v in vecs]
                person_best = max(sims)

                # debug_line.append(f"{name}:{person_best:.3f}")

                if person_best > best_sim:
                    second_sim = best_sim
                    best_sim = person_best
                    best_name = name
                elif person_best > second_sim:
                    second_sim = person_best

            # if debug_line:
            #     print("Sims ->", " | ".join(debug_line))

            # Decide if this is a confident match, ambiguous, or unknown
            confident_match = (best_sim >= THRESH) and ((best_sim - second_sim) >= MARGIN)

            if confident_match:
                color = (0, 255, 0)
                show_name = best_name
            elif best_sim >= THRESH:
                color = (0, 255, 255)  # yellow = ambiguous
                show_name = "ambiguous"
            else:
                color = (0, 0, 255)
                show_name = "unknown"

            label = f"{show_name}:{best_sim:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(0, y1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            # Remember last known face for access logic (only if confident)
            if confident_match:
                last_face_ok_time = now
                last_known_user = best_name
                GPIO.output(LED_FACE, GPIO.HIGH)
                face_led_until = now + 3.0   # keep face LED on for 3s

            # Publish face events with cooldown
            if now >= face_cooldown_until:
                if confident_match:
                    ev = "face_ok"
                    user_for_event = best_name
                elif best_sim >= THRESH:
                    ev = "ambiguous"
                    user_for_event = "ambiguous"
                else:
                    ev = "unknown"
                    user_for_event = "unknown"

                publish_face_event(ev, user_for_event, best_sim)
                face_cooldown_until = now + (3 if confident_match else 1)

        cv2.imshow("Doorlock: Sensors + Face Recognition", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

        time.sleep(0.02)
except KeyboardInterrupt:
    pass
finally:
    GPIO.output(LED_MOTION, GPIO.LOW)
    GPIO.output(LED_DOOR, GPIO.LOW)
    GPIO.output(LED_FACE, GPIO.LOW)
    GPIO.cleanup()
    client.loop_stop()
    client.disconnect()
    cv2.destroyAllWindows()
    print("\nStopped.")

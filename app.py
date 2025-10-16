import json, time
import numpy as np
import cv2
from picamera2 import Picamera2
import paho.mqtt.client as mqtt

USE_AWS = False
LOCAL_BROKER = "localhost"
TOPIC = "doorlock/group11/telemetry"
DEVICE_ID = "rpi5-group11"

mqttc = mqtt.Client(client_id="pi5-door", protocol=mqtt.MQTTv5)

def on_connect(client, userdata, flags, reason_code, properties=None):
    print("MQTT connected:", reason_code)
mqttc.on_connect = on_connect

if not USE_AWS:
    mqttc.connect(LOCAL_BROKER, 1883, 60)
else:
    AWS_ENDPOINT = "a34tg0ldi880qv-ats.iot.us-east-2.amazonaws.com"
    CERT_DIR = "/home/rinotruc/pi/certs"
    AWS_CA   = f"{CERT_DIR}/AmazonRootCA1.pem"
    AWS_CERT = f"{CERT_DIR}/c3399abafc08ec0e999c2974b310039e7c2acbfa70955008670ce90429bc5734-certificate.pem.crt"
    AWS_KEY  = f"{CERT_DIR}/c3399abafc08ec0e999c2974b310039e7c2acbfa70955008670ce90429bc5734-private.pem.key"
    mqttc.tls_set(ca_certs=AWS_CA, certfile=AWS_CERT, keyfile=AWS_KEY)
    mqttc.connect(AWS_ENDPOINT, 8883, 60)

print("Loading models...")
DETECTOR = cv2.dnn.readNetFromCaffe(
    "models/deploy.prototxt",
    "models/res10_300x300_ssd_iter_140000.caffemodel"
)
EMB = cv2.dnn.readNetFromONNX("models/face_recognition_sface_2021dec.onnx")

with open("templates/templates.json") as f:
    TEMPLATES = json.load(f)
TEMPLATES = {k: np.array(v, dtype=np.float32) for k, v in TEMPLATES.items()}
ENROLLED = list(TEMPLATES.keys())
print("Enrolled users:", ENROLLED if ENROLLED else "[none]")

def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))

def emb_from_crop(bgr: np.ndarray) -> np.ndarray:
    face = cv2.cvtColor(cv2.resize(bgr, (112, 112)), cv2.COLOR_BGR2RGB).astype(np.float32)
    blob = cv2.dnn.blobFromImage(face, scalefactor=1.0/255.0, size=(112, 112), swapRB=False)
    EMB.setInput(blob)
    e = EMB.forward().reshape(-1).astype(np.float32)
    norm = np.linalg.norm(e) + 1e-8
    return e / norm

def detect_faces(frame: np.ndarray):
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)),
                                 1.0, (300, 300), (104, 177, 123))
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

picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "RGB888"}
))
picam2.start()
time.sleep(0.2)

THRESH = 0.60
cooldown_until = 0.0
print("System ready. Press 'q' to quit.")

while True:
    rgb = picam2.capture_array()
    frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    faces = detect_faces(frame)
    now = time.time()

    for (x1, y1, x2, y2, conf) in faces:
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        e = emb_from_crop(crop)
        best_name, best_sim = "unknown", 0.0
        for name, tmpl in TEMPLATES.items():
            sim = cosine(e, tmpl)
            if sim > best_sim:
                best_name, best_sim = name, sim
        color = (0, 255, 0) if best_sim >= THRESH else (0, 0, 255)
        lbl = f"{best_name}:{best_sim:.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, lbl, (x1, max(0, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if now >= cooldown_until:
            event = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "device_id": DEVICE_ID,
                "event": "face_ok" if best_sim >= THRESH else "unknown",
                "user": best_name,
                "sim": round(best_sim, 3)
            }
            mqttc.publish(TOPIC, json.dumps(event), qos=1)
            cooldown_until = now + (3 if best_sim >= THRESH else 1)

    cv2.imshow("Face Recognition (SFace)", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
print("Exiting...")


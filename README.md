# group11

1) Hardware (BCM pin numbers)

PIR (HC-SR501): VCC→5V, GND→GND, OUT→GPIO17

Magnetic switch module: COM→3.3V, NO→GPIO27 (use NC if you want inverted logic)

LEDs:

  Motion LED → GPIO22 → 330Ω → LED anode, LED cathode → GND

  Door LED → GPIO23 → 330Ω → LED anode, LED cathode → GND

2) Software setup
   
sudo apt update && sudo apt install -y mosquitto mosquitto-clients python3-rpi.gpio python3-pip
pip3 install -r requirements.txt --break-system-packages

3) local test (no cloud)
   
Edit iot_leds_mqtt.py:
  USE_AWS = False
Open a subscriber in another terminal:
  mosquitto_sub -t "doorlock/group11/telemetry" -v

In other terminal run:
  python3 iot_leds_mqtt.py

Wave at PIR/open door -> see LEDs change + JSON publish + TinyDB logs in events.json

4) AWS IoT Core (cloud)
One-time in AWS Console:

IoT Core → Manage → Things → create: rpi5-group11 (or your device name)

Create/download certs & keys:

AmazonRootCA1.pem

<hash>-certificate.pem.crt

<hash>-private.pem.key

Secure → Policies → create policy (allow iot:Connect/Publish/Subscribe/Receive on *) and attach to the certificate.

Attach cert ↔ Thing.

Settings → copy Device data endpoint (looks like xxxxx-ats.iot.us-<region>.amazonaws.com).

Put files on the Pi:

mkdir -p /home/pi/certs
# copy the 3 files above into /home/pi/certs
chmod 600 /home/pi/certs/*pem* /home/pi/certs/*crt

Edit iot_leds_mqtt.py:

USE_AWS = True
AWS_ENDPOINT = "xxxxx-ats.iot.us-<region>.amazonaws.com"
CERT_DIR = "/home/pi/certs"
AWS_CA   = f"{CERT_DIR}/AmazonRootCA1.pem"
AWS_CERT = f"{CERT_DIR}/<hash>-certificate.pem.crt"
AWS_KEY  = f"{CERT_DIR}/<hash>-private.pem.key"
CLIENT_ID = "rpi5-group11"   # match Thing name if possible
TOPIC_TELEMETRY = "doorlock/group11/telemetry"
  
Test in AWS console → Test → MQTT test client → subscribe to:

doorlock/group11/telemetry

Run: 
python3 iot_leds_mqtt.py

5) What the script does

Reads PIR (GPIO17) and door (GPIO27)

Drives two LEDs (motion→GPIO22, door-open→GPIO23)

Logs every state change to TinyDB → events.json

Publishes JSON to MQTT topic doorlock/group11/telemetry

Toggle LOCAL vs AWS with USE_AWS = False/True

Sample payload:

{
  "ts": "2025-10-09T01:23:45Z",
  "device_id": "rpi5-group11",
  "motion": "motion",
  "door": "open"
}


TL;DR
Wire PIR→GPIO17, door switch COM→3.3V & NO→GPIO27, LEDs on GPIO22/23 (with 330Ω).

sudo apt install mosquitto mosquitto-clients python3-rpi.gpio && pip3 install -r requirements.txt --break-system-packages

Run local: set USE_AWS=False, subscribe with mosquitto_sub -t "doorlock/group11/#" -v, then python3 iot_leds_mqtt.py.

Run AWS: set USE_AWS=True, fill endpoint + cert paths, subscribe in AWS test client to doorlock/group11/#, run the script.

Don’t commit certs/keys; send them out-of-band if needed.



=================== PART 2 (Facial Recognition) =======================
This phase extends the previous IoT door and motion system by integrating real-time face recognition using Raspberry Pi 5, Pi Camera Module 2, and OpenCV DNN models. The goal is to verify authorized users locally and publish recognition events to the same MQTT topic (local or AWS IoT Core).

Hardware
Component	Connection
Raspberry Pi 5	Main controller
Pi Camera Module 2	CSI port
Existing LEDs, PIR, and magnetic switch	Same as in Part 1

Software Dependencies
sudo apt install -y python3-opencv libatlas-base-dev python3-picamera2
pip install paho-mqtt numpy

Optional (if using a virtual environment):
python3 -m venv venv
source venv/bin/activate

Folder structure
facerec/
 ├── app.py
 ├── enroll.py
 ├── models/
 │   ├── deploy.prototxt
 │   ├── res10_300x300_ssd_iter_140000.caffemodel
 │   └── face_recognition_sface_2021dec.onnx
 ├── enroll/Vicky/        # captured images
 └── templates/templates.json

Step to Run
1. Capture and Enroll Faces
   
Run once per user:
python3 capture_faces.py "Enter name"
python3 enroll.py

This saves normalized embeddings to templates/templates.json.

2. Run the Recognition App

python3 app.py

Shows live video stream.
Detects and recognizes faces in real time.
Publishes recognition results to MQTT.

3. MQTT Output Examples
{
  "ts": "2025-10-15T03:12:05Z",
  "device_id": "rpi5-group11",
  "event": "face_ok",
  "user": "Vicky",
  "sim": 0.72
}

You can view these live: 
mosquitto_sub -t "doorlock/group11/#" -v

or in the AWS IoT Core MQTT Test Client if USE_AWS=True.

4. Integration with IoT Door System

Both scripts (iot_leds_mqtt.py and app.py) publish to the same topic
doorlock/group11/telemetry, so you can see door events + face verification together.

5. Expected Behavior

When a person appears, the Pi recognizes the face and publishes the identity.
When motion or door state changes, sensors publish status updates.
The combined stream can later trigger cloud-side automation or access control logic.

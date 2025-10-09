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

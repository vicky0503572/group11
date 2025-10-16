#!/usr/bin/env python3
import os, sys, time
import numpy as np
import cv2
from picamera2 import Picamera2

print("USING PICAMERA2 (no v4l2)")

# ---- args: name [count]
if len(sys.argv) >= 2:
    NAME = sys.argv[1].strip()
else:
    NAME = input("Enter the person's name to enroll: ").strip()
if not NAME:
    print("No name provided. Exiting."); sys.exit(1)

try:
    target_count = int(sys.argv[2]) if len(sys.argv) >= 3 else 80
except ValueError:
    target_count = 80

# sanitize folder name a bit
safe_name = "".join(c for c in NAME if c.isalnum() or c in ("-", "_"))
out_dir = f"enroll/{safe_name or 'user'}"
os.makedirs(out_dir, exist_ok=True)

net = cv2.dnn.readNetFromCaffe(
    "models/deploy.prototxt",
    "models/res10_300x300_ssd_iter_140000.caffemodel"
)

picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "RGB888"}
))
picam2.start()
time.sleep(0.2)

def best_face_bbox(frame_bgr):
    h, w = frame_bgr.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(frame_bgr, (300, 300)),
                                 1.0, (300, 300), (104, 177, 123))
    net.setInput(blob)
    dets = net.forward()
    best, best_conf = None, 0.0
    for i in range(dets.shape[2]):
        conf = float(dets[0, 0, i, 2])
        if conf > best_conf:
            x1, y1, x2, y2 = (dets[0, 0, i, 3:7] * np.array([w, h, w, h])).astype(int)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            best, best_conf = (x1, y1, x2, y2), conf
    return best, best_conf

saved = 0
last_save = 0.0
min_interval = 0.25
print(f"Enrolling '{safe_name}' ? saving to {out_dir}")
print("Move your head: left/right/up/down; vary distance/lighting. Press q to quit.")

while True:
    rgb = picam2.capture_array()
    frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    bbox, conf = best_face_bbox(frame)
    if bbox and conf > 0.6:
        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        size = int(1.2 * max(x2 - x1, y2 - y1))
        x1p, y1p = max(0, cx - size // 2), max(0, cy - size // 2)
        x2p, y2p = min(frame.shape[1], cx + size // 2), min(frame.shape[0], cy + size // 2)
        crop = frame[y1p:y2p, x1p:x2p]

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)
        cv2.putText(frame, f"{conf:.2f}", (x1, max(0, y1-10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

        now = time.time()
        if crop.size > 0 and saved < target_count and (now - last_save) >= min_interval:
            fn = f"{out_dir}/{int(now*1000)}.jpg"
            cv2.imwrite(fn, crop)
            saved += 1
            last_save = now
            print(f"[{saved}/{target_count}] Saved {fn}")
            if saved >= target_count:
                print(f"\nCaptured {target_count} images. Press 'q' to exit the window.")

    cv2.imshow("capture", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
print(f"\nTotal saved: {saved} face crops in '{out_dir}'")


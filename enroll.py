
import os
import glob
import json

import numpy as np
import cv2

# ================== LOAD SFace MODEL ==================
NET = cv2.dnn.readNetFromONNX("models/face_recognition_sface_2021dec.onnx")

def to_emb(img_bgr: np.ndarray) -> np.ndarray:
    """
    Convert a BGR face image to a normalized embedding using SFace.
    """
    face = cv2.cvtColor(cv2.resize(img_bgr, (112, 112)), cv2.COLOR_BGR2RGB).astype(np.float32)
    blob = cv2.dnn.blobFromImage(
        face,
        scalefactor=1.0 / 255.0,
        size=(112, 112),
        swapRB=False
    )
    NET.setInput(blob)
    emb = NET.forward().reshape(-1).astype(np.float32)
    emb = emb / (np.linalg.norm(emb) + 1e-8)
    return emb

def images_in(dirpath: str):
    """
    Return sorted list of image paths in a directory.
    """
    paths = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        paths.extend(glob.glob(os.path.join(dirpath, ext)))
    return sorted(paths)

templates = {}

means = {}

for person_dir in sorted(glob.glob("enroll/*")):
    if not os.path.isdir(person_dir):
        continue

    name = os.path.basename(person_dir)
    embs = []

    for p in images_in(person_dir):
        img = cv2.imread(p)
        if img is None:
            continue
        try:
            e = to_emb(img)
            embs.append(e)
        except Exception as ex:
            print(f"[WARN] Failed on {p}: {ex}")

    if embs:
        embs = np.stack(embs, axis=0)   # (N, D)
        # store all embeddings for runtime k-NN style matching
        templates[name] = [e.tolist() for e in embs]

        # compute mean embedding just for reporting
        m = np.mean(embs, axis=0)
        m = m / (np.linalg.norm(m) + 1e-8)
        means[name] = m

        print(f"[DEBUG] {name}: {embs.shape[0]} images used")
    else:
        print(f"[WARN] No valid images for {name}, skipping.")

print("\n=== Template summary (using mean embeddings) ===")
for name, m in means.items():
    norm = np.linalg.norm(m)
    print(f"{name}: shape={m.shape}, norm={norm:.4f}")

names = list(means.keys())
vecs = [means[n] for n in names]

if len(names) >= 2:
    print("\n=== Pairwise cosine similarity between users (mean embeddings) ===")
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = vecs[i], vecs[j]
            cos = float(
                np.dot(a, b)
                / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8)
            )
            print(f"sim({names[i]}, {names[j]}) = {cos:.3f}")
else:
    print("\n(Not enough users for pairwise similarity check.)")


os.makedirs("templates", exist_ok=True)
with open("templates/templates.json", "w") as f:
    json.dump(templates, f, indent=2)

print("\nSaved templates for:", list(templates.keys()) if templates else "[none]")

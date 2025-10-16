# enroll.pyOpenCV DNN + SFace
import glob, os, json, numpy as np, cv2

NET = cv2.dnn.readNetFromONNX("models/face_recognition_sface_2021dec.onnx")

def to_emb(img_bgr):
    # SFace expects 112x112, RGB, 1/255 scale
    face = cv2.cvtColor(cv2.resize(img_bgr,(112,112)), cv2.COLOR_BGR2RGB).astype(np.float32)
    blob = cv2.dnn.blobFromImage(face, scalefactor=1.0/255, size=(112,112), swapRB=False)
    NET.setInput(blob)
    emb = NET.forward().reshape(-1).astype(np.float32)
    emb /= (np.linalg.norm(emb) + 1e-8)
    return emb

templates = {}
for person_dir in glob.glob("enroll/*"):
    name = os.path.basename(person_dir)
    embs=[]
    for p in glob.glob(f"{person_dir}/*.jpg"):
        img = cv2.imread(p)
        if img is None: continue
        embs.append(to_emb(img))
    if embs:
        m = np.mean(embs, axis=0); m /= (np.linalg.norm(m)+1e-8)
        templates[name] = m.tolist()

os.makedirs("templates", exist_ok=True)
with open("templates/templates.json","w") as f:
    json.dump(templates, f, indent=2)
print("Saved templates for:", list(templates.keys()))


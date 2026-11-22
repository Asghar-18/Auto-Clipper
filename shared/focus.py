"""Practical on-screen subject presence analysis (not identity verification).

The Dylan Page campaign requires the streamer to stay the main focus. This module
samples frames, detects *faces* with the bundled YuNet model (or OpenCV's Haar
cascade as a fallback), and reports presence/absence timing. It deliberately does
not claim to recognise Dylan: face detection is evidence of a visible person,
not proof of identity. Low-confidence or unavailable detection is reported as
requiring manual review and is never treated as approval.
"""
import os

import numpy as np

from campaign import config

MODEL_NAME = "face_detection_yunet_2023mar.onnx"
DEFAULT_SAMPLE_INTERVAL = 1.0
MIN_SAMPLES = 5
MIN_FACE_AREA_RATIO = 0.0008       # ignore background-size faces
QUALIFYING_AREA_FACTOR = 0.35      # relative to the median detected face size


def _model_path():
    return os.path.join(config.ROOT, "models", MODEL_NAME)


def _detector(frame_w: int, frame_h: int):
    """Return (kind, detector, scale) or (None, None, 1.0)."""
    try:
        import cv2
    except ImportError:
        return None, None, 1.0
    model = _model_path()
    if os.path.isfile(model):
        try:
            scale = min(1.0, 640.0 / max(1, frame_w))
            size = (max(1, int(frame_w * scale)), max(1, int(frame_h * scale)))
            detector = cv2.FaceDetectorYN.create(model, "", size, 0.6, 0.3, 5000)
            return "yunet", detector, scale
        except Exception:
            pass
    cascade = os.path.join(getattr(cv2.data, "haarcascades", ""), "haarcascade_frontalface_default.xml")
    if cascade and os.path.isfile(cascade):
        try:
            detector = cv2.CascadeClassifier(cascade)
            if not detector.empty():
                return "haar", detector, 1.0
        except Exception:
            pass
    return None, None, 1.0


def _faces(frame, kind, detector, scale):
    """Return [(cx, cy, area_ratio)] in frame coordinates."""
    import cv2
    h, w = frame.shape[:2]
    found = []
    if kind == "yunet":
        small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1.0 else frame
        detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = detector.detect(small)
        for face in (faces if faces is not None else []):
            x, y, fw, fh = [float(value) / scale for value in face[:4]]
            if fw <= 0 or fh <= 0:
                continue
            found.append((x + fw / 2, y + fh / 2, (fw * fh) / max(1, w * h)))
    elif kind == "haar":
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        boxes = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        for x, y, fw, fh in boxes:
            found.append((float(x + fw / 2), float(y + fh / 2), (float(fw) * float(fh)) / max(1, w * h)))
    return found


def analyze_focus(video_path: str, start: float = 0.0, length: float | None = None,
                  sample_interval: float = DEFAULT_SAMPLE_INTERVAL) -> dict:
    """Sample a clip and report whether a visible person stays on screen.

    Returns a dict with ``status`` (ok / needs_manual_review / unavailable),
    ``presence_ratio``, ``longest_absence_seconds`` and sample detail. ``identity_verified``
    is always False: this is a visibility check, not a face recognition system.
    """
    analysis = {
        "status": "unavailable",
        "method": "face-presence sampling (no identity verification)",
        "identity_verified": False,
        "detector": None,
        "samples": 0,
        "faces_detected": 0,
        "qualifying_samples": 0,
        "presence_ratio": 0.0,
        "longest_absence_seconds": 0.0,
        "sample_times": [],
        "observations": [],
        "dominant_zone": None,
        "note": "",
    }
    try:
        import cv2
    except ImportError:
        analysis["note"] = "OpenCV is not installed; focus must be reviewed manually"
        return analysis
    capture = cv2.VideoCapture(os.path.abspath(video_path))
    if not capture.isOpened():
        analysis["note"] = "clip could not be opened for focus sampling"
        return analysis
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
    kind, detector, scale = _detector(width, height)
    if detector is None:
        capture.release()
        analysis["note"] = "no face detector available; focus must be reviewed manually"
        return analysis
    analysis["detector"] = kind
    if length is None:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        length = frames / fps if fps > 0 else 0.0
    interval = max(0.2, float(sample_interval))
    moments = []
    moment = max(0.0, float(start))
    end = max(0.0, float(start)) + max(0.0, float(length))
    while moment < end or not moments:
        moments.append(moment)
        moment += interval
        if len(moments) >= 600:
            break
    observations = []
    try:
        for index, absolute in enumerate(moments):
            if index:
                capture.set(cv2.CAP_PROP_POS_MSEC, absolute * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            faces = _faces(frame, kind, detector, scale)
            if faces:
                largest = max(faces, key=lambda item: item[2])
                observations.append({"time": round(absolute - float(start), 2),
                                     "faces": len(faces), "area": largest[2],
                                     "cx": largest[0], "cy": largest[1]})
            else:
                observations.append({"time": round(absolute - float(start), 2),
                                     "faces": 0, "area": 0.0, "cx": None, "cy": None})
    finally:
        capture.release()

    analysis["samples"] = len(observations)
    analysis["observations"] = observations
    analysis["faces_detected"] = sum(1 for item in observations if item["faces"])
    analysis["sample_times"] = [item["time"] for item in observations]
    zones = {"left": 0, "centre": 0, "right": 0}
    for item in observations:
        if item["cx"] is None:
            continue
        zone = "left" if item["cx"] < width / 3 else "right" if item["cx"] > 2 * width / 3 else "centre"
        zones[zone] += 1
    if any(zones.values()):
        analysis["dominant_zone"] = max(zones, key=zones.get)
    areas = [item["area"] for item in observations if item["area"] > 0]
    if areas:
        threshold = max(MIN_FACE_AREA_RATIO, float(np.median(areas)) * QUALIFYING_AREA_FACTOR)
        qualifying = [item["area"] >= threshold for item in observations]
    else:
        qualifying = [False] * len(observations)
    analysis["qualifying_samples"] = sum(qualifying)
    if observations:
        analysis["presence_ratio"] = round(analysis["qualifying_samples"] / len(observations), 3)
        run = best = 0
        for present in qualifying:
            run = 0 if present else run + 1
            best = max(best, run)
        analysis["longest_absence_seconds"] = round(best * interval, 2)
    if len(observations) < MIN_SAMPLES:
        analysis["status"] = "needs_manual_review"
        analysis["note"] = "too few decodable frames; focus must be reviewed manually"
    elif analysis["presence_ratio"] < 0.1:
        analysis["status"] = "needs_manual_review"
        analysis["note"] = "no reliable visible-person signal; focus must be reviewed manually"
    else:
        analysis["status"] = "ok"
        analysis["note"] = "face presence measured; identity is not verified"
    return analysis


def focus_checks(analysis: dict, profile) -> list[dict]:
    """Translate focus analysis into profile-driven compliance checks."""
    from campaigns.base import rule_check

    max_absence = profile.editing.max_subject_absence_seconds
    min_presence = profile.editing.min_subject_presence_ratio
    uncertain = analysis.get("status") != "ok"
    absence = analysis.get("longest_absence_seconds", 0.0)
    presence = analysis.get("presence_ratio", 0.0)
    return [
        rule_check(
            "subject_present_throughout",
            not uncertain and presence >= (min_presence or 0.0),
            f"presence={presence:.0%} (minimum {min_presence:.0%}); "
            f"status={analysis.get('status')}" if min_presence else f"presence={presence:.0%}",
            manual_review=True,
        ),
        rule_check(
            "subject_not_intro_only",
            not uncertain and absence <= (max_absence if max_absence is not None else 0.0),
            f"longest absence {absence:.1f}s (maximum {max_absence}s); "
            f"status={analysis.get('status')}",
            manual_review=True,
        ),
    ]

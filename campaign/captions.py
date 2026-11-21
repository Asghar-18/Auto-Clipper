"""Word-timing provider that avoids the VAD crash on this machine.

Mirrors clip.whisper_words, but disables faster-whisper's VAD filter and uses a
ctranslate2 version that loads on this CPU. No changes to clip.py are needed.
"""
import clip

_model = None


def transcribe_words(audio, language="en"):
    """Return clip.WordTimings for a numpy float32 audio array."""
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, info = _model.transcribe(audio, word_timestamps=True, vad_filter=False,
                                       task="transcribe", language=language or None)
    words = [(float(word.start), float(word.end), word.word.strip())
             for segment in segments for word in (segment.words or [])]
    spoken = info.language or "unknown"
    if spoken == "hi":
        if clip.contains_arabic_script(" ".join(item[2] for item in words)):
            return clip.WordTimings(words, spoken, "none",
                                    "Hindi recognition returned Arabic script; captions omitted")
        words = [(start, end, clip.romanize_hindi(text)) for start, end, text in words]
        return clip.WordTimings(words, spoken, "Hinglish")
    if spoken == "en":
        return clip.WordTimings(words, spoken, "English")
    return clip.WordTimings(words, spoken, "none", "Captions disabled for unsupported or uncertain language")

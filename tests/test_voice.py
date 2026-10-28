"""F4 voice notes: WAV conversion, transcription request format, structured extraction (no real audio)."""

import io
import json
import wave
from types import SimpleNamespace

import httpx
import numpy as np

from backend.voice import notes

# A transcript fixture standing in for the builder's real voice note (no synthetic speech is generated).
TRANSCRIPT = ("Walkdown on line P-101, LPG service. Heavy scale and pitting on the second flange from the pump, "
              "light surface rust on the pipe support. Please book a UT thickness check on that flange.")


def tone_wav(rate=44100, channels=2, seconds=0.5) -> bytes:
    """A test tone (format test only)."""
    t = np.arange(int(rate * seconds)) / rate
    x = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(x, channels).tobytes())
    return buf.getvalue()


def test_wav_conversion_to_api_format():
    out = notes.to_api_wav(tone_wav())
    with wave.open(io.BytesIO(out)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert abs(w.getnframes() - 8000) <= 1
    ok = notes.to_api_wav(tone_wav(rate=16000, channels=1))
    assert ok == tone_wav(rate=16000, channels=1)  # already valid: unchanged


def test_transcribe_request_format(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.setattr(notes, "load_dotenv", lambda *a, **k: None)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("latin-1")
        seen["auth"] = request.headers["authorization"]
        seen["has_parts"] = 'name="request"' in body and 'name="audio"' in body
        seen["model"] = '"model": "muse-voice-transcribe-1.0"' in body and '"audioEncoding": "WAV"' in body
        return httpx.Response(200, json={"sessionId": "s", "transcript": TRANSCRIPT, "audioDurationMs": 12500,
                                         "turns": []})

    out = notes.transcribe(tone_wav(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out == {"transcript": TRANSCRIPT, "audio_ms": 12500}
    assert seen == {"auth": "Bearer test-key", "has_parts": True, "model": True}


def test_extract_validates_structured_note(monkeypatch):
    reply = {"asset_tag": "P-101", "line_service": "lpg", "summary": "Heavy pitting on a flange of P-101.",
             "remarks": [{"location": "second flange from the pump", "description": "heavy scale and pitting",
                          "severity_words": "heavy"}], "follow_ups": ["UT thickness check"]}
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, prompt_tokens_details=None))

    monkeypatch.setattr(notes, "meta_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    note = notes.extract(TRANSCRIPT)
    assert note.asset_tag == "P-101" and note.line_service.value == "lpg" and note.follow_ups == ["UT thickness check"]
    assert seen["response_format"]["json_schema"]["strict"] is True and TRANSCRIPT in seen["messages"][1]["content"]


def test_schema_allows_unknown_service():
    s = notes.note_schema()
    assert None in s["properties"]["line_service"]["enum"] and set(s["required"]) == set(s["properties"])

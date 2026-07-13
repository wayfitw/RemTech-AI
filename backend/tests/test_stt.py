"""Issue #34 (TASK-1002) — локальный STT (Whisper) в хуки turn-сервиса."""
import io
import struct
import wave

import pytest

from app import media, turn


def _wav_silence(seconds=0.4, rate=16000) -> bytes:
    frames = int(rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % frames, *([0] * frames)))
    return buf.getvalue()


def test_get_transcriber_selection(monkeypatch):
    monkeypatch.setattr(media, "_transcriber", None)
    monkeypatch.setattr(media.settings, "stt_backend", "null")
    assert isinstance(media.get_transcriber(), media.NullTranscriber)

    monkeypatch.setattr(media, "_transcriber", None)
    monkeypatch.setattr(media.settings, "stt_backend", "whisper")
    tr = media.get_transcriber()
    assert isinstance(tr, media.WhisperTranscriber)   # выбран, но модель ещё не загружена
    assert tr._model is None


async def test_disabled_by_default_returns_empty(monkeypatch):
    monkeypatch.setattr(media.settings, "stt_enabled", False)
    assert await media.maybe_transcribe(b"any-audio", "audio/ogg") == ""


async def test_empty_audio_rejected():
    tr = media.WhisperTranscriber("small")
    with pytest.raises(media.TranscriptionError):
        await tr.transcribe(b"")           # пустое аудио — без загрузки модели


async def test_maybe_transcribe_swallows_broken_audio(monkeypatch):
    monkeypatch.setattr(media.settings, "stt_enabled", True)
    monkeypatch.setattr(media, "_transcriber", None)
    monkeypatch.setattr(media.settings, "stt_backend", "whisper")

    class _Boom(media.WhisperTranscriber):
        async def transcribe(self, audio, mime=""):
            raise media.TranscriptionError("битый формат")
    monkeypatch.setattr(media, "_transcriber", _Boom("small"))
    # ход не падает — хук возвращает пустую строку
    assert await media.maybe_transcribe(b"\x00\x01", "audio/ogg") == ""


async def test_run_turn_audio_failure_emits_error(monkeypatch):
    """Голос не распознан (STT выключен/битый) → честный отказ, ядро не вызывается."""
    called = {"n": 0}

    async def fake_process(*a, **k):
        called["n"] += 1
    monkeypatch.setattr(turn.orchestrator, "process", fake_process)
    monkeypatch.setattr(media.settings, "stt_enabled", False)

    events = []

    async def emit(e):
        events.append(e)

    await turn.run_turn({"user_id": 1, "role": "user"}, None, "", [], None, emit,
                        audio=b"voice-bytes", audio_mime="audio/ogg")
    assert any(e["type"] == "error" for e in events)
    assert called["n"] == 0


async def test_whisper_roundtrip_if_available():
    """Реальный прогон faster-whisper на коротком образце (скип, если не установлен)."""
    pytest.importorskip("faster_whisper")
    tr = media.WhisperTranscriber("tiny", language="ru", device="cpu", compute_type="int8")
    result = await tr.transcribe(_wav_silence(), "audio/wav")
    assert isinstance(result, str)         # тишина → пустая/короткая строка, но без падения

"""Issue #32 (ADR-011) — интерфейсы медиа-трансформаций для голосовых каналов.

Контракты Transcriber (речь→текст, STT) и Synthesizer (текст→речь, TTS) с
локальными дефолтами. Полноценные Whisper (STT) и Silero (TTS) — TASK-1002/1003;
здесь интерфейсы + минимальная локальная реализация и опциональные хуки,
которые в веб-канале по умолчанию ВЫКЛЮЧЕНЫ (STT_ENABLED/TTS_ENABLED=false).

ADR-010/011: локальные модели держат голос/ПДн в контуре без egress в облако.
"""
import asyncio
import io
import struct
import wave
from abc import ABC, abstractmethod

from app.config import get_settings
from app.logging_config import get_logger

settings = get_settings()
log = get_logger("remtech.media")


class TranscriptionError(Exception):
    """Не удалось распознать аудио (пустое/битое/неподдерживаемый формат)."""


class SynthesisError(Exception):
    """Не удалось синтезировать речь (пустой текст/ошибка модели)."""


class Transcriber(ABC):
    """Речь → текст."""
    @abstractmethod
    async def transcribe(self, audio: bytes, mime: str = "") -> str: ...


class Synthesizer(ABC):
    """Текст → речь (аудио-байты)."""
    @abstractmethod
    async def synthesize(self, text: str) -> bytes: ...


class NullTranscriber(Transcriber):
    """Заглушка STT — когда голос выключен/бэкенд не выбран."""
    async def transcribe(self, audio: bytes, mime: str = "") -> str:
        return ""


class WhisperTranscriber(Transcriber):
    """Issue #34 — локальный STT на faster-whisper (CTranslate2). Модель грузится
    лениво при первом распознавании и кэшируется. Работает на CPU (GPU опционально);
    голос не покидает контур (ADR-010/011). Битое/пустое аудио → TranscriptionError."""

    def __init__(self, model: str, language: str = "", device: str = "cpu",
                 compute_type: str = "int8"):
        self._model_name = model
        self._language = language or None
        self._device = device
        self._compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise TranscriptionError(
                    "faster-whisper не установлен (pip install faster-whisper)") from e
            log.info("loading whisper model=%s device=%s", self._model_name, self._device)
            self._model = WhisperModel(self._model_name, device=self._device,
                                       compute_type=self._compute_type)
        return self._model

    def _run(self, audio: bytes) -> str:
        model = self._load()
        segments, _info = model.transcribe(io.BytesIO(audio), language=self._language)
        return " ".join(seg.text for seg in segments).strip()

    async def transcribe(self, audio: bytes, mime: str = "") -> str:
        if not audio:
            raise TranscriptionError("пустое аудио")
        try:
            return await asyncio.to_thread(self._run, audio)
        except TranscriptionError:
            raise
        except Exception as e:   # битый/неподдерживаемый формат — понятный отказ, без падения хода
            raise TranscriptionError(f"не удалось распознать аудио: {type(e).__name__}") from e


class SilenceSynthesizer(Synthesizer):
    """Заглушка TTS: валидный WAV-тишина длиной ~по тексту (когда голос выключен)."""
    async def synthesize(self, text: str) -> bytes:
        seconds = max(0.3, min(len(text or "") * 0.06, 30.0))
        rate = 16000
        frames = int(rate * seconds)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(struct.pack("<%dh" % frames, *([0] * frames)))
        return buf.getvalue()


class SileroSynthesizer(Synthesizer):
    """Issue #40 — локальный TTS на Silero (torch.hub). Ленивая загрузка модели +
    кэш на процесс. Русские голоса, CPU, без egress (ADR-010/011). Возвращает WAV.
    Ошибка синтеза → SynthesisError (канал откатывается на текстовый ответ)."""

    def __init__(self, model: str, speaker: str, sample_rate: int = 48000, device: str = "cpu"):
        self._model_id = model
        self._speaker = speaker
        self._sample_rate = sample_rate
        self._device = device
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                import torch
            except ImportError as e:
                raise SynthesisError("torch не установлен (pip install torch)") from e
            log.info("loading silero tts model=%s speaker=%s", self._model_id, self._speaker)
            model, _ = torch.hub.load("snakers4/silero-models", "silero_tts",
                                      language="ru", speaker=self._model_id, trust_repo=True)
            model.to(self._device)
            self._model = model
        return self._model

    def _run(self, text: str) -> bytes:
        model = self._load()
        audio = model.apply_tts(text=text, speaker=self._speaker, sample_rate=self._sample_rate)
        # torch.FloatTensor [-1,1] → int16 PCM → WAV (без numpy)
        ints = [max(-32768, min(32767, int(x * 32767))) for x in audio.tolist()]
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._sample_rate)
            w.writeframes(struct.pack("<%dh" % len(ints), *ints))
        return buf.getvalue()

    async def synthesize(self, text: str) -> bytes:
        text = (text or "").strip()
        if not text:
            raise SynthesisError("пустой текст")
        try:
            return await asyncio.to_thread(self._run, text[:1000])   # длину ограничиваем
        except SynthesisError:
            raise
        except Exception as e:   # спецсимволы/сбой модели — понятный отказ, ход не падает
            raise SynthesisError(f"не удалось синтезировать: {type(e).__name__}") from e


def wav_to_ogg_opus(wav: bytes) -> bytes | None:
    """WAV → OGG/Opus для Telegram sendVoice (голосовое сообщение). None при сбое —
    вызывающий откатывается на sendAudio(WAV). Требует PyAV (уже в зависимостях)."""
    try:
        import av
        with wave.open(io.BytesIO(wav)) as w:
            rate, nframes = w.getframerate(), w.getnframes()
            pcm = w.readframes(nframes)
        out = io.BytesIO()
        container = av.open(out, mode="w", format="ogg")
        stream = container.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        src = av.AudioFrame(format="s16", layout="mono", samples=nframes)
        src.sample_rate = rate
        src.planes[0].update(pcm)
        for frame in resampler.resample(src):
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):   # flush
            container.mux(packet)
        container.close()
        return out.getvalue()
    except Exception as e:
        log.info("ogg-энкодер недоступен, откат на sendAudio: %s", type(e).__name__)
        return None


_transcriber: Transcriber | None = None


def get_transcriber() -> Transcriber:
    """STT-бэкенд по конфигу: whisper (faster-whisper) или заглушка. Кэшируется —
    модель Whisper тяжёлая, грузим один раз на процесс."""
    global _transcriber
    if _transcriber is None:
        if settings.stt_backend == "whisper":
            _transcriber = WhisperTranscriber(
                settings.stt_model, settings.stt_language,
                settings.stt_device, settings.stt_compute_type)
        else:
            _transcriber = NullTranscriber()
    return _transcriber


_synthesizer: Synthesizer | None = None


def get_synthesizer() -> Synthesizer:
    """TTS-бэкенд по конфигу: silero (torch) или заглушка. Кэшируется — модель тяжёлая."""
    global _synthesizer
    if _synthesizer is None:
        if settings.tts_backend == "silero":
            _synthesizer = SileroSynthesizer(
                settings.tts_model, settings.tts_speaker,
                settings.tts_sample_rate, settings.tts_device)
        else:
            _synthesizer = SilenceSynthesizer()
    return _synthesizer


async def maybe_transcribe(audio: bytes, mime: str = "") -> str:
    """Опциональный STT-хук на входе хода (по умолчанию выключен). Битое/пустое
    аудио не роняет ход — возвращаем пустую строку, канал сообщит о неудаче."""
    if not settings.stt_enabled or not audio:
        return ""
    try:
        return await get_transcriber().transcribe(audio, mime)
    except TranscriptionError as e:
        log.info("stt failed: %s", e)
        return ""


async def maybe_synthesize(text: str) -> bytes | None:
    """Опциональный TTS-хук на выходе хода (по умолчанию выключен). Ошибка синтеза
    не роняет ход — возвращаем None, канал отдаёт текстовый ответ (#40)."""
    if not settings.tts_enabled or not (text or "").strip():
        return None
    try:
        return await get_synthesizer().synthesize(text)
    except SynthesisError as e:
        log.info("tts failed: %s", e)
        return None

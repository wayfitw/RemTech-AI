"""Генерация изображений (FLUX Kontext Pro) и видео (Kling) через Replicate.
Портировано из mybot/services/replicate_svc.py."""
import asyncio
import base64

import httpx
import replicate

from app.config import get_settings

_token = get_settings().replicate_api_token
_client = replicate.Client(api_token=_token) if _token else None


def _read_output(output) -> bytes | None:
    """Универсальное чтение результата Replicate (file-like / url / список)."""
    try:
        if hasattr(output, "read"):
            return output.read()
        if hasattr(output, "url"):
            return httpx.get(str(output.url), timeout=120).content
        url = str(output[0]) if hasattr(output, "__getitem__") else str(output)
        return httpx.get(url, timeout=120).content
    except Exception as e:
        print(f"Replicate read error: {e}")
        return None


def _generate_flux_sync(prompt: str) -> bytes | None:
    if not _client:
        return None
    try:
        output = _client.run(
            "black-forest-labs/flux-kontext-pro",
            input={
                "prompt": prompt,
                "output_format": "jpg",
                "output_quality": 90,
                "safety_tolerance": 2,
            },
        )
        return _read_output(output)
    except Exception as e:
        print(f"FLUX error: {e}")
        return None


async def generate_image_flux(prompt: str) -> bytes | None:
    return await asyncio.to_thread(_generate_flux_sync, prompt)


def _edit_image_flux_sync(image_bytes: bytes, instruction: str) -> bytes | None:
    if not _client:
        return None
    try:
        data_uri = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"
        output = _client.run(
            "black-forest-labs/flux-kontext-pro",
            input={
                "prompt": instruction,
                "input_image": data_uri,
                "output_format": "jpg",
                "output_quality": 92,
                "safety_tolerance": 2,
            },
        )
        return _read_output(output)
    except Exception as e:
        print(f"FLUX edit error: {e}")
        return None


async def edit_image_flux(image_bytes: bytes, instruction: str) -> bytes | None:
    return await asyncio.to_thread(_edit_image_flux_sync, image_bytes, instruction)


def _generate_video_sync(prompt: str, image_bytes: bytes | None = None, duration: int = 5) -> bytes | None:
    if not _client:
        return None
    try:
        dur = 10 if duration >= 10 else 5
        params = {"prompt": prompt, "duration": dur, "aspect_ratio": "16:9"}
        if image_bytes:
            params["start_image"] = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"
        output = _client.run("kwaivgi/kling-v2.6", input=params)
        return _read_output(output)
    except Exception as e:
        print(f"Kling video error: {e}")
        return None


async def generate_video(prompt: str, image_bytes: bytes | None = None, duration: int = 5) -> bytes | None:
    return await asyncio.to_thread(_generate_video_sync, prompt, image_bytes, duration)

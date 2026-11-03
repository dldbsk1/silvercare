"""음성 파일 실제 형식·길이 확인 (워커, mutagen)

- 읽을 수 없음·형식 판별 불가·길이 없음 → AUDIO_UNREADABLE
- 허용 외 형식 (mutagen은 읽지만 음성 업로드 대상 아님) → AUDIO_FORMAT_MISMATCH
- 선언 MIME ≠ 실제 형식, 둘 다 허용 형식 → 통과 + 로그 (기기별 라벨 차이로 녹음 유실 방지)
- 길이: 1.5초 이상 180.5초 미만 → 반올림 2~180 (DB CHECK 0~180 항상 만족)
"""
import io
import logging
import math
from dataclasses import dataclass

import mutagen
from mutagen.aac import AAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE


logger = logging.getLogger("silvercare.audio")

MIN_SECONDS = 1.5
MAX_SECONDS = 180.5

# mutagen 형식 → 대표 MIME
FORMATS = {
    MP4: "audio/mp4",
    AAC: "audio/aac",
    MP3: "audio/mpeg",
    WAVE: "audio/wav",
}

# 같은 형식으로 보는 선언 MIME
MIME_FAMILY = {
    "audio/mp4": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/x-m4a": "audio/mp4",
    "audio/aac": "audio/aac",
    "audio/mpeg": "audio/mpeg",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
}


class AudioProblem(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AudioInfo:
    mime: str
    seconds: float

    @property
    def duration_seconds(self) -> int:
        # 반올림 (0.5 올림)
        return math.floor(self.seconds + 0.5)


def probe(data: bytes, declared_mime: str) -> AudioInfo:
    try:
        parsed = mutagen.File(io.BytesIO(data))
    except Exception as e:
        raise AudioProblem("AUDIO_UNREADABLE", f"파일 분석 실패: {e}") from e

    if parsed is None:
        raise AudioProblem("AUDIO_UNREADABLE", "형식 판별 불가")

    mime = FORMATS.get(type(parsed))
    if mime is None:
        raise AudioProblem(
            "AUDIO_FORMAT_MISMATCH", f"허용 외 형식: {type(parsed).__name__}"
        )

    seconds = getattr(parsed.info, "length", None)
    if not seconds or seconds <= 0:
        raise AudioProblem("AUDIO_UNREADABLE", "길이 정보 없음")

    if MIME_FAMILY.get(declared_mime) != mime:
        logger.warning("선언 MIME %s ≠ 실제 %s, 허용 형식이라 통과", declared_mime, mime)

    if not MIN_SECONDS <= seconds < MAX_SECONDS:
        raise AudioProblem(
            "AUDIO_DURATION_OUT_OF_RANGE", f"길이 {seconds:.2f}초 (2~180초만)"
        )

    return AudioInfo(mime=mime, seconds=seconds)

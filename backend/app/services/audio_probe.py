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
    if (not seconds or seconds <= 0) and mime == "audio/mp4":
        seconds = mp4_duration(data)
    if not seconds or seconds <= 0:
        raise AudioProblem("AUDIO_UNREADABLE", "길이 정보 없음")

    if MIME_FAMILY.get(declared_mime) != mime:
        logger.warning("선언 MIME %s ≠ 실제 %s, 허용 형식이라 통과", declared_mime, mime)

    if not MIN_SECONDS <= seconds < MAX_SECONDS:
        raise AudioProblem(
            "AUDIO_DURATION_OUT_OF_RANGE", f"길이 {seconds:.2f}초 (2~180초만)"
        )

    return AudioInfo(mime=mime, seconds=seconds)


# ── MP4 길이 직접 읽기 (mutagen 실패 대비) ──
# 삼성 녹음 앱: moov 안 trak 앞에 QuickTime식 meta (version·flags 없음)
# → mutagen 1.47이 meta 잘못 읽고 trak 못 찾음 → 길이 0

def iter_boxes(data: bytes, start: int, end: int):
    """(종류, 내용 시작, 상자 끝). 크기 이상 → 중단"""
    i = start
    while i + 8 <= end:
        size = int.from_bytes(data[i:i + 4], "big")
        kind = data[i + 4:i + 8]
        header = 8
        if size == 1:
            if i + 16 > end:
                return
            size = int.from_bytes(data[i + 8:i + 16], "big")
            header = 16
        elif size == 0:
            size = end - i
        if size < header or i + size > end:
            return
        yield kind, i + header, i + size
        i += size


def child(data: bytes, start: int, end: int, kind: bytes):
    for k, s, e in iter_boxes(data, start, end):
        if k == kind:
            return s, e
    return None


def mdhd_seconds(data: bytes, start: int, end: int) -> float | None:
    """mvhd·mdhd 공통: version 0 → 32비트 길이 / 1 → 64비트"""
    version = data[start] if start < end else None
    if version == 0 and start + 20 <= end:
        unit = int.from_bytes(data[start + 12:start + 16], "big")
        length = int.from_bytes(data[start + 16:start + 20], "big")
    elif version == 1 and start + 32 <= end:
        unit = int.from_bytes(data[start + 20:start + 24], "big")
        length = int.from_bytes(data[start + 24:start + 32], "big")
    else:
        return None
    return length / unit if unit else None


def mp4_duration(data: bytes) -> float | None:
    """음성 트랙(soun) mdhd 길이. 없으면 mvhd. 못 읽음 → None"""
    moov = child(data, 0, len(data), b"moov")
    if moov is None:
        return None

    for kind, s, e in iter_boxes(data, *moov):
        if kind != b"trak":
            continue
        mdia = child(data, s, e, b"mdia")
        if mdia is None:
            continue
        hdlr = child(data, *mdia, b"hdlr")
        mdhd = child(data, *mdia, b"mdhd")
        # hdlr: version·flags(4) + pre_defined(4) + 종류(4)
        if hdlr and mdhd and data[hdlr[0] + 8:hdlr[0] + 12] == b"soun":
            return mdhd_seconds(data, *mdhd)

    mvhd = child(data, *moov, b"mvhd")
    return mdhd_seconds(data, *mvhd) if mvhd else None

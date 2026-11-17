"""테스트용 음성 파일 (파이썬 wave로 생성, 저장소에 파일 안 둠)"""
import io
import wave

# 낮은 샘플레이트 → 3분도 수백 KB
SAMPLE_RATE = 1000


def box(kind: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def full_box_duration(kind: bytes, unit: int, length: int) -> bytes:
    """mvhd·mdhd version 0: version·flags + 생성·수정 시각 + 단위 + 길이"""
    return box(kind, bytes(4) + bytes(8) + unit.to_bytes(4, "big") + length.to_bytes(4, "big") + bytes(80))


# 안드로이드 MediaRecorder: moov 안 trak 앞 QuickTime식 meta (version·flags 없음)
ANDROID_META = box(b"meta", (
    box(b"hdlr", bytes(8) + b"mdta" + bytes(12) + b"\x00")
    + box(b"keys", bytes(4) + (1).to_bytes(4, "big") + box(b"mdta", b"com.android.version"))
    + box(b"ilst", box((1).to_bytes(4, "big"), box(b"data", (1).to_bytes(4, "big") + bytes(4) + b"13")))
))


def make_android_m4a(seconds: float, unit: int = 44100) -> bytes:
    """오디오 내용 없이 상자 구조만 (길이 확인용)"""
    hdlr = box(b"hdlr", bytes(8) + b"soun" + bytes(12) + b"\x00")
    trak = box(b"trak", box(b"mdia", full_box_duration(b"mdhd", unit, round(seconds * unit)) + hdlr))
    moov = box(b"moov", full_box_duration(b"mvhd", 1000, round(seconds * 1000)) + ANDROID_META + trak)
    ftyp = box(b"ftyp", b"mp42" + bytes(4) + b"isommp42")
    return ftyp + box(b"mdat", bytes(64)) + moov


def make_wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * round(seconds * SAMPLE_RATE))
    return buffer.getvalue()

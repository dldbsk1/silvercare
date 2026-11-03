"""테스트용 음성 파일 (파이썬 wave로 생성, 저장소에 파일 안 둠)"""
import io
import wave

# 낮은 샘플레이트 → 3분도 수백 KB
SAMPLE_RATE = 1000


def make_wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * round(seconds * SAMPLE_RATE))
    return buffer.getvalue()

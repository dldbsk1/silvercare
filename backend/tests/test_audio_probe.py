"""음성 파일 형식·길이 확인 (mutagen, DB 없이)"""
import pytest

from app.services import audio_probe
from tests.audio_samples import make_wav


@pytest.mark.parametrize("seconds, stored", [
    (1.5, 2),
    (2.0, 2),
    (2.5, 3),
    (179.6, 180),
    (180.4, 180),
])
def test_duration_in_range_rounded(seconds, stored):
    info = audio_probe.probe(make_wav(seconds), "audio/wav")

    assert info.mime == "audio/wav"
    assert info.duration_seconds == stored


@pytest.mark.parametrize("seconds", [0.5, 1.4, 180.5, 200])
def test_duration_out_of_range(seconds):
    with pytest.raises(audio_probe.AudioProblem) as e:
        audio_probe.probe(make_wav(seconds), "audio/wav")

    assert e.value.code == "AUDIO_DURATION_OUT_OF_RANGE"


@pytest.mark.parametrize("data", [b"", b"not audio at all", b"\x00" * 1000])
def test_unreadable(data):
    with pytest.raises(audio_probe.AudioProblem) as e:
        audio_probe.probe(data, "audio/mp4")

    assert e.value.code == "AUDIO_UNREADABLE"


def test_empty_wav_has_no_length():
    with pytest.raises(audio_probe.AudioProblem) as e:
        audio_probe.probe(make_wav(0), "audio/wav")

    assert e.value.code == "AUDIO_UNREADABLE"


def test_disallowed_format():
    # FLAC: mutagen은 읽지만 업로드 허용 형식 아님
    flac = b"fLaC" + bytes([0x80, 0, 0, 34]) + bytes(10) + bytes([0x0A, 0xC4, 0x42, 0xF0, 0, 0, 0, 0]) + bytes(16)

    with pytest.raises(audio_probe.AudioProblem) as e:
        audio_probe.probe(flac, "audio/mp4")

    assert e.value.code in ("AUDIO_FORMAT_MISMATCH", "AUDIO_UNREADABLE")


def test_declared_mime_mismatch_within_allowed_passes():
    # 실제 wav, 선언 m4a → 허용 형식끼리 → 통과 (기기별 라벨 차이)
    info = audio_probe.probe(make_wav(3), "audio/mp4")

    assert info.mime == "audio/wav"

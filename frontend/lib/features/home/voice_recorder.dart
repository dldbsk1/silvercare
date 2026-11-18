import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import 'audio_file_io.dart' if (dart.library.js_interop) 'audio_file_web.dart';

/// 녹음 형식 (서버 허용 형식)
/// - 앱: AAC m4a
/// - 웹: WAV 16kHz 모노 (브라우저 mp4 = 조각난 mp4 → 서버 길이 판별 불가). 3분 ≈ 5.8MB
const appAudioType = 'audio/mp4';
const webAudioType = 'audio/wav';

/// 녹음 결과 (앱: 임시 파일, 웹: blob 주소). 분류 시작 전 서버 전송 X
class RecordedAudio {
  RecordedAudio(this.path, {this.contentType = appAudioType});

  final String path;
  final String contentType;

  Future<Uint8List> readBytes() => readAudio(path);

  /// 취소·다시 녹음·업로드 끝 → 삭제 (웹: blob 해제)
  Future<void> delete() => deleteAudio(path);
}

/// 녹음기 (테스트용 교체 가능)
abstract class VoiceRecorder {
  /// 마이크 권한 (처음이면 요청)
  Future<bool> hasPermission();

  Future<void> start();

  /// 끝 → 파일. 실패 → null
  Future<RecordedAudio?> stop();

  /// 녹음 중단 + 파일 버림
  Future<void> cancel();

  /// 소리 크기 0~1 (파형 막대용)
  Stream<double> levels();

  Future<void> dispose();
}

/// 실제 녹음 (record 패키지)
/// 전화 수신 등 끼어들기 → 일시정지 (기능명세서 A-HOME-001)
class DeviceVoiceRecorder implements VoiceRecorder {
  final _recorder = AudioRecorder();

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  @override
  Future<void> start() async {
    if (kIsWeb) {
      // 웹: 경로 무시 → 끝나면 blob 주소
      await _recorder.start(
        const RecordConfig(encoder: AudioEncoder.wav, numChannels: 1, sampleRate: 16000),
        path: '',
      );
      return;
    }
    final dir = await getTemporaryDirectory();
    final path = '${dir.path}/voice_${DateTime.now().millisecondsSinceEpoch}.m4a';
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.aacLc, numChannels: 1, bitRate: 64000),
      path: path,
    );
  }

  @override
  Future<RecordedAudio?> stop() async {
    final path = await _recorder.stop();
    if (path == null) return null;
    return RecordedAudio(path, contentType: kIsWeb ? webAudioType : appAudioType);
  }

  @override
  Future<void> cancel() => _recorder.cancel();

  /// dBFS (-160~0) → 0~1 (말소리 대략 -50 이상)
  @override
  Stream<double> levels() => _recorder
      .onAmplitudeChanged(const Duration(milliseconds: 100))
      .map((a) => ((a.current + 50) / 50).clamp(0.0, 1.0));

  @override
  Future<void> dispose() => _recorder.dispose();
}

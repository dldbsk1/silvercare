import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../home/home_api.dart';
import '../../home/voice_recorder.dart';
import '../record_api.dart';
import 'record_sheets.dart';

/// 다시 녹음하기 (받아쓰기 실패 음성 → 같은 기록의 음성 교체)
/// 녹음 (2초~3분) → 업로드 → replace-audio → 바뀐 기록 반환. 닫기·실패 → null
Future<RecordDetail?> showReRecordSheet(
  BuildContext context, {
  required RecordDetail record,
  required RecordApi recordApi,
  HomeApi? homeApi,
  VoiceRecorder? recorder,
}) {
  return showModalBottomSheet<RecordDetail>(
    context: context,
    useRootNavigator: true,
    isDismissible: false,
    enableDrag: false,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    builder: (_) => _ReRecordSheet(
      record: record,
      recordApi: recordApi,
      homeApi: homeApi ?? HomeApi(),
      recorder: recorder ?? DeviceVoiceRecorder(),
    ),
  );
}

enum _Step { ready, recording, saving }

class _ReRecordSheet extends StatefulWidget {
  const _ReRecordSheet({required this.record, required this.recordApi, required this.homeApi, required this.recorder});

  final RecordDetail record;
  final RecordApi recordApi;
  final HomeApi homeApi;
  final VoiceRecorder recorder;

  @override
  State<_ReRecordSheet> createState() => _ReRecordSheetState();
}

class _ReRecordSheetState extends State<_ReRecordSheet> {
  static const _maxDuration = Duration(minutes: 3);
  static const _minDuration = Duration(seconds: 2);

  _Step _step = _Step.ready;
  String? _error;
  final _stopwatch = Stopwatch();
  Timer? _ticker;

  @override
  void dispose() {
    _ticker?.cancel();
    if (_step == _Step.recording) unawaited(widget.recorder.cancel());
    unawaited(widget.recorder.dispose());
    super.dispose();
  }

  Future<void> _start() async {
    final allowed = await widget.recorder.hasPermission();
    if (!mounted) return;
    if (!allowed) {
      setState(() => _error = '마이크 권한을 허용해 주세요.');
      return;
    }
    try {
      await widget.recorder.start();
    } catch (_) {
      if (mounted) setState(() => _error = '녹음을 시작하지 못했어요.');
      return;
    }
    if (!mounted) return;
    _stopwatch
      ..reset()
      ..start();
    _ticker = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (_stopwatch.elapsed >= _maxDuration) {
        _stopAndSave();
      } else {
        setState(() {});
      }
    });
    setState(() {
      _step = _Step.recording;
      _error = null;
    });
  }

  Future<void> _stopAndSave() async {
    if (_step != _Step.recording) return;
    _ticker?.cancel();
    _stopwatch.stop();
    final elapsed = _stopwatch.elapsed > _maxDuration ? _maxDuration : _stopwatch.elapsed;
    setState(() => _step = _Step.saving);

    final audio = await widget.recorder.stop();
    if (!mounted) return;
    if (audio == null || elapsed < _minDuration) {
      await audio?.delete();
      if (mounted) {
        setState(() {
          _step = _Step.ready;
          _error = '2초 이상 말해 주세요.';
        });
      }
      return;
    }

    try {
      final upload = await widget.homeApi.requestUpload(widget.record.parentId, contentType: audio.contentType);
      await widget.homeApi.uploadAudio(upload, await audio.readBytes());
      final updated = await widget.recordApi.replaceAudio(
        widget.record.id,
        uploadId: upload.uploadId,
        durationSeconds: elapsed.inSeconds.clamp(2, 180),
      );
      await audio.delete();
      if (mounted) Navigator.of(context).pop(updated);
    } catch (e) {
      await audio.delete();
      if (!mounted) return;
      setState(() {
        _step = _Step.ready;
        _error = e is ApiException ? e.message : '올리지 못했어요. 다시 녹음해 주세요.';
      });
    }
  }

  String get _elapsedText {
    final s = _stopwatch.elapsed.inSeconds;
    return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final recording = _step == _Step.recording;
    final saving = _step == _Step.saving;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              '다시 녹음하기',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
            ),
            const SizedBox(height: 8),
            Text(
              recording
                  ? '말씀이 끝나면 멈춤을 눌러 주세요'
                  : saving
                  ? '음성을 올리는 중이에요'
                  : '이 기록의 녹음을 새로 바꿔요. 기록한 시각은 그대로예요.',
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 16, color: AppColors.subtext),
            ),
            const SizedBox(height: 24),
            if (saving)
              const SizedBox(
                width: 72,
                height: 72,
                child: Padding(padding: EdgeInsets.all(18), child: CircularProgressIndicator(strokeWidth: 3)),
              )
            else
              IconButton.filled(
                iconSize: 40,
                style: IconButton.styleFrom(
                  backgroundColor: recording ? AppColors.text : AppColors.primary,
                  fixedSize: const Size(72, 72),
                ),
                tooltip: recording ? '멈춤' : '녹음 시작',
                onPressed: recording ? _stopAndSave : _start,
                icon: Icon(recording ? Icons.stop_rounded : Icons.mic, color: Colors.white),
              ),
            const SizedBox(height: 12),
            Text(
              recording ? _elapsedText : ' ',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: AppColors.text),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 15, color: Theme.of(context).colorScheme.error),
              ),
            ],
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: saving ? null : () => Navigator.of(context).pop(),
                style: sheetButtonStyle().copyWith(
                  backgroundColor: const WidgetStatePropertyAll(AppColors.track),
                  foregroundColor: const WidgetStatePropertyAll(AppColors.text),
                ),
                child: const Text('취소'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

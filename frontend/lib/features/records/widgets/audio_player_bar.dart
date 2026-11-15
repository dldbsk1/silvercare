import 'dart:async';

import 'package:flutter/material.dart';
import 'package:just_audio/just_audio.dart';

import '../../../app/theme.dart';

/// 재생기 (테스트용 교체)
abstract class AudioPlayback {
  Future<void> setUrl(String url);
  Future<void> play();
  Future<void> pause();
  Future<void> seek(Duration position);
  Stream<Duration> get positionStream;

  /// 재생 중 여부 (끝까지 재생 → false)
  Stream<bool> get playingStream;
  Future<void> dispose();
}

class JustAudioPlayback implements AudioPlayback {
  final _player = AudioPlayer();

  @override
  Future<void> setUrl(String url) => _player.setUrl(url);

  @override
  Future<void> play() async {
    // play()는 재생이 끝날 때 완료 → 기다리지 않음
    unawaited(_player.play());
  }

  @override
  Future<void> pause() => _player.pause();

  @override
  Future<void> seek(Duration position) => _player.seek(position);

  @override
  Stream<Duration> get positionStream => _player.positionStream;

  @override
  Stream<bool> get playingStream => _player.playerStateStream.map(
        (s) => s.playing && s.processingState != ProcessingState.completed,
      );

  @override
  Future<void> dispose() => _player.dispose();
}

/// Figma: ▶ ─────── 0:48
/// 처음 누를 때 재생 주소 받음 (5분 유효). 지난 주소 → 다시 받음. 화면 나감 → 멈춤 (dispose)
class AudioPlayerBar extends StatefulWidget {
  const AudioPlayerBar({super.key, required this.seconds, required this.loadUrl, this.player});

  final int seconds;
  final Future<String> Function() loadUrl;
  final AudioPlayback? player;

  @override
  State<AudioPlayerBar> createState() => _AudioPlayerBarState();
}

class _AudioPlayerBarState extends State<AudioPlayerBar> {
  static const _urlLifetime = Duration(minutes: 4);

  late final AudioPlayback _player = widget.player ?? JustAudioPlayback();
  StreamSubscription<Duration>? _positionSub;
  StreamSubscription<bool>? _playingSub;

  DateTime? _loadedAt;
  bool _playing = false;
  bool _loading = false;
  Duration _position = Duration.zero;

  Duration get _total => Duration(seconds: widget.seconds);

  @override
  void initState() {
    super.initState();
    _positionSub = _player.positionStream.listen((p) {
      if (mounted) setState(() => _position = p > _total ? _total : p);
    });
    _playingSub = _player.playingStream.listen((playing) {
      if (mounted) setState(() => _playing = playing);
    });
  }

  @override
  void dispose() {
    unawaited(_positionSub?.cancel());
    unawaited(_playingSub?.cancel());
    unawaited(_player.dispose());
    super.dispose();
  }

  Future<void> _toggle() async {
    if (_playing) {
      await _player.pause();
      return;
    }
    setState(() => _loading = true);
    try {
      final loadedAt = _loadedAt;
      if (loadedAt == null || DateTime.now().difference(loadedAt) > _urlLifetime) {
        final at = _position;
        await _player.setUrl(await widget.loadUrl());
        _loadedAt = DateTime.now();
        if (at > Duration.zero && at < _total) await _player.seek(at);
      }
      if (_position >= _total) await _player.seek(Duration.zero);
      await _player.play();
    } catch (_) {
      _loadedAt = null;
      if (mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(const SnackBar(content: Text('음성을 재생하지 못했어요. 다시 시도해 주세요.')));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  static String _clock(Duration d) => '${d.inMinutes}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final progress = _total.inMilliseconds == 0 ? 0.0 : _position.inMilliseconds / _total.inMilliseconds;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 10, 18, 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(32),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 48,
            height: 48,
            child: IconButton.filled(
              onPressed: _loading ? null : _toggle,
              tooltip: _playing ? '멈추기' : '재생',
              style: IconButton.styleFrom(backgroundColor: AppColors.primary),
              icon: _loading
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : Icon(_playing ? Icons.pause : Icons.play_arrow_outlined, color: Colors.white),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: progress.clamp(0.0, 1.0),
                minHeight: 5,
                color: AppColors.primaryGlow,
                backgroundColor: AppColors.track,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Text(
            _playing || _position > Duration.zero ? _clock(_position) : _clock(_total),
            style: const TextStyle(fontSize: 16, color: AppColors.subtext),
          ),
        ],
      ),
    );
  }
}

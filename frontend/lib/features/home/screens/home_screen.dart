import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../records/record_api.dart';
import '../../records/screens/record_detail_screen.dart';
import '../../records/widgets/record_card.dart';
import '../home_api.dart';
import '../voice_recorder.dart';

/// SCR_A_100 홈 (A-HOME-001~009)
///
/// 위에서부터: 호칭 + 알림 / D-day 카드 / 기록 영역 / 최근 기록 3건
///
/// 기록 영역 상태 (_Mode)
///   idle       마이크 버튼 + 주제 칩 + 글 입력 + 출처 + 저장
///   recording  정지 버튼 + 0:12 / 3:00 + 파형 (최대 3분 → 자동 정지)
///   review     녹음 끝, 휴대폰 안에만 있음 → 다시 녹음 / 취소 / 분류 시작
///   saving     업로드·기록 생성·분류 대기 ("정리하는 중")
///   result     분류 결과 카드 (신체 > 식사하기에 저장됐어요)
///
/// 음성: 분류 시작 전에는 업로드 X (잘못 녹음한 음성 저장 X). 2초 미만 → 버림
/// 처리 대기: 2초마다 확인, 60초 넘으면 중단 + 기록함 안내
/// TODO(B단계): 오늘 컨디션, 받은 체크리스트, 알림 개수
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, this.homeApi, this.authApi, this.recorder, this.recordApi});

  /// 테스트용 교체
  final HomeApi? homeApi;
  final AuthApi? authApi;
  final VoiceRecorder? recorder;
  final RecordApi? recordApi;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

enum _Mode { idle, recording, review, saving, result }

class _HomeScreenState extends State<HomeScreen> {
  static const _maxDuration = Duration(minutes: 3);
  static const _minDuration = Duration(seconds: 2);
  static const _pollEvery = Duration(seconds: 2);
  static const _pollLimit = Duration(seconds: 60);
  static const _topics = ['식사', '잠', '화장실', '기억', '기분', '걷기', '약'];

  late final HomeApi _api = widget.homeApi ?? HomeApi();
  late final AuthApi _auth = widget.authApi ?? AuthApi();
  late final VoiceRecorder _recorder = widget.recorder ?? DeviceVoiceRecorder();

  final _textController = TextEditingController();

  HomeData? _home;
  String? _loadError;

  _Mode _mode = _Mode.idle;
  String _source = 'direct';

  // 녹음
  final _stopwatch = Stopwatch();
  Timer? _ticker;
  StreamSubscription<double>? _levelSub;
  final List<double> _levels = List.filled(11, 0.15);
  RecordedAudio? _audio;
  Duration _recorded = Duration.zero;

  // 저장·결과
  String? _idempotencyKey;
  String _savingMessage = '';
  String? _resultTitle;
  String? _resultText;
  String? _resultRecordId;
  bool _resultPending = false;

  @override
  void initState() {
    super.initState();
    _textController.addListener(() => setState(() {}));
    _load();
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _levelSub?.cancel();
    _textController.dispose();
    _audio?.delete();
    _recorder.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final me = await _auth.fetchMe();
      if (me.parentIds.isEmpty) {
        if (mounted) context.go(me.nextRoute);
        return;
      }
      final home = await _api.fetchHome(me.parentIds.first);
      if (!mounted) return;
      setState(() {
        _home = home;
        _loadError = null;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  Future<void> _refreshRecent() async {
    final home = _home;
    if (home == null) return;
    try {
      final fresh = await _api.fetchHome(home.parentId);
      if (mounted) setState(() => _home = fresh);
    } on ApiException {
      // 다음 새로고침 때
    }
  }

  /// 저장 결과 → 상세 열고 분류 바꾸기 / 글 고치기 바로
  void _openResult(RecordAction action) {
    final id = _resultRecordId;
    if (id == null) return;
    setState(() => _mode = _Mode.idle);
    openRecordDetail(context, id, action: action, recordApi: widget.recordApi);
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  // ── 녹음 ──

  Future<void> _startRecording() async {
    final allowed = await _recorder.hasPermission();
    if (!mounted) return;
    if (!allowed) {
      _toast('마이크 권한을 허용해 주세요.');
      return;
    }
    try {
      await _recorder.start();
    } catch (_) {
      if (mounted) _toast('녹음을 시작하지 못했어요.');
      return;
    }
    if (!mounted) return;
    FocusScope.of(context).unfocus();
    _stopwatch
      ..reset()
      ..start();
    _levelSub = _recorder.levels().listen((level) {
      setState(
        () => _levels
          ..removeAt(0)
          ..add(level.clamp(0.15, 1.0)),
      );
    });
    _ticker = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (_stopwatch.elapsed >= _maxDuration) {
        _stopRecording();
      } else {
        setState(() {});
      }
    });
    setState(() => _mode = _Mode.recording);
  }

  Future<void> _stopRecording() async {
    _ticker?.cancel();
    _stopwatch.stop();
    unawaited(_levelSub?.cancel());
    _levelSub = null;
    final elapsed = _stopwatch.elapsed > _maxDuration
        ? _maxDuration
        : _stopwatch.elapsed;
    final audio = await _recorder.stop();
    if (!mounted) return;

    if (audio == null || elapsed < _minDuration) {
      await audio?.delete();
      setState(() => _mode = _Mode.idle);
      _toast('2초 이상 말해 주세요.');
      return;
    }
    setState(() {
      _audio = audio;
      _recorded = elapsed;
      _mode = _Mode.review;
    });
  }

  Future<void> _discardRecording({bool again = false}) async {
    await _audio?.delete();
    _audio = null;
    setState(() => _mode = _Mode.idle);
    if (again) await _startRecording();
  }

  // ── 저장 ──

  Future<void> _saveVoice() async {
    final home = _home!;
    final audio = _audio!;
    _idempotencyKey ??= HomeApi.newIdempotencyKey();
    setState(() {
      _mode = _Mode.saving;
      _savingMessage = '음성을 올리는 중이에요';
    });
    try {
      final upload = await _api.requestUpload(home.parentId);
      await _api.uploadAudio(upload, await audio.readBytes());
      final recordId = await _api.createVoice(
        home.parentId,
        uploadId: upload.uploadId,
        durationSeconds: _recorded.inSeconds.clamp(2, 180),
        source: _source,
        recordedAt: DateTime.now().subtract(_recorded),
        idempotencyKey: _idempotencyKey!,
      );
      await audio.delete();
      _audio = null;
      await _waitForResult(recordId);
    } catch (e) {
      // 업로드 실패 → 녹음은 휴대폰에 그대로 (다시 분류 시작 가능)
      if (!mounted) return;
      setState(() => _mode = _Mode.review);
      _toast(e is ApiException ? e.message : '올리지 못했어요. 다시 시도해 주세요.');
    }
  }

  Future<void> _saveText() async {
    final home = _home!;
    final text = _textController.text.trim();
    _idempotencyKey ??= HomeApi.newIdempotencyKey();
    FocusScope.of(context).unfocus();
    setState(() {
      _mode = _Mode.saving;
      _savingMessage = '정리하는 중이에요';
    });
    try {
      final recordId = await _api.createText(
        home.parentId,
        text: text,
        source: _source,
        idempotencyKey: _idempotencyKey!,
      );
      _textController.clear();
      await _waitForResult(recordId);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _mode = _Mode.idle);
      _toast(e.message);
    }
  }

  /// 처리 끝까지 확인 → 결과 카드. 60초 넘으면 "아직 정리 중"
  Future<void> _waitForResult(String recordId) async {
    _idempotencyKey = null;
    if (mounted) setState(() => _savingMessage = '정리하는 중이에요');
    final deadline = DateTime.now().add(_pollLimit);
    Processing? processing;
    while (mounted && DateTime.now().isBefore(deadline)) {
      try {
        processing = await _api.fetchProcessing(recordId);
        if (processing.done) break;
      } on ApiException {
        // 일시 오류 → 다음 확인
      }
      await Future<void>.delayed(_pollEvery);
    }
    if (!mounted) return;

    String title;
    String? text = processing?.text;
    var pending = false;
    if (processing == null || !processing.done) {
      title = '저장했어요. 아직 정리 중이에요';
      pending = true;
    } else if (processing.status == 'failed') {
      title = processing.transcriptEmpty
          ? '말소리를 알아듣지 못했어요'
          : '저장했어요. 분류는 하지 못했어요';
    } else {
      final result = await _api.fetchRecord(recordId);
      text = result.text;
      title = result.items.isEmpty
          ? '저장했어요. 맞는 항목이 없어요'
          : '${result.items.first.path}에 저장됐어요';
    }
    setState(() {
      _mode = _Mode.result;
      _resultTitle = title;
      _resultText = text;
      _resultRecordId = recordId;
      _resultPending = pending;
    });
    recordsChanged.value++;
    _refreshRecent();
  }

  // ── 화면 ──

  @override
  Widget build(BuildContext context) {
    final home = _home;
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: home == null
            ? _loading()
            : RefreshIndicator(
                onRefresh: _refreshRecent,
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                  children: [
                    _header(home),
                    const SizedBox(height: 12),
                    _DdayCard(
                      dday: home.dday,
                      onTap: () => context.go('/survey'),
                    ),
                    const SizedBox(height: 24),
                    ..._recordArea(),
                    const SizedBox(height: 28),
                    _recentHeader(),
                    const SizedBox(height: 12),
                    if (home.recentRecords.isEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 24),
                        child: Text(
                          '첫 기록을 남겨 보세요',
                          textAlign: TextAlign.center,
                          style: TextStyle(fontSize: 16, color: AppColors.text),
                        ),
                      )
                    else
                      for (final record in home.recentRecords) ...[
                        RecordCard(
                          record: record,
                          onTap: () => openRecordDetail(context, record.id, recordApi: widget.recordApi),
                        ),
                        const SizedBox(height: 12),
                      ],
                  ],
                ),
              ),
      ),
    );
  }

  Widget _loading() {
    if (_loadError == null)
      return const Center(child: CircularProgressIndicator());
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              _loadError!,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 16),
            ),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: () {
                setState(() => _loadError = null);
                _load();
              },
              child: const Text('다시 불러오기'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _header(HomeData home) {
    return Row(
      children: [
        Expanded(
          child: Text(
            home.nickname,
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
        ),
        IconButton(
          tooltip: '알림',
          icon: const Icon(
            Icons.notifications_none,
            size: 28,
            color: AppColors.text,
          ),
          onPressed: () => _toast('알림은 준비 중이에요.'),
        ),
      ],
    );
  }

  List<Widget> _recordArea() {
    switch (_mode) {
      case _Mode.idle:
        return [
          Center(
            child: _RecordButton(recording: false, onTap: _startRecording),
          ),
          const SizedBox(height: 14),
          const Text(
            '눌러서 말하기',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: 20),
          _topicChips(),
          const SizedBox(height: 16),
          _textInput(),
          const SizedBox(height: 16),
          _sourceChips(),
          const SizedBox(height: 16),
          _primaryButton(
            '저장',
            _textController.text.trim().isEmpty ? null : _saveText,
          ),
        ];
      case _Mode.recording:
        return [
          Center(child: _RecordButton(recording: true, onTap: _stopRecording)),
          const SizedBox(height: 14),
          Text(
            '${_clock(_stopwatch.elapsed)} / ${_clock(_maxDuration)}',
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: 28),
          _Waveform(levels: _levels),
          const SizedBox(height: 28),
          _sourceChips(),
        ];
      case _Mode.review:
        return [
          _ReviewCard(
            duration: _clock(_recorded),
            onRetry: () => _discardRecording(again: true),
            onCancel: _discardRecording,
          ),
          const SizedBox(height: 16),
          _sourceChips(),
          const SizedBox(height: 16),
          _primaryButton('분류 시작', _saveVoice),
        ];
      case _Mode.saving:
        return [_SavingCard(message: _savingMessage)];
      case _Mode.result:
        return [
          _ResultCard(
            title: _resultTitle ?? '',
            text: _resultText,
            pending: _resultPending,
            onChangeClass: () => _openResult(RecordAction.classify),
            onEditText: () => _openResult(RecordAction.edit),
            onClose: () => setState(() => _mode = _Mode.idle),
          ),
        ];
    }
  }

  /// 주제 칩: 누르면 글 입력칸에 "식사: " 시작 (비어 있을 때)
  Widget _topicChips() {
    return SizedBox(
      height: 44,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: _topics.length,
        separatorBuilder: (_, _) => const SizedBox(width: 10),
        itemBuilder: (context, i) => _Pill(
          label: _topics[i],
          selected: false,
          onTap: () {
            if (_textController.text.trim().isEmpty) {
              _textController.text = '${_topics[i]}: ';
              _textController.selection = TextSelection.collapsed(
                offset: _textController.text.length,
              );
            }
          },
        ),
      ),
    );
  }

  Widget _textInput() {
    return TextField(
      controller: _textController,
      minLines: 3,
      maxLines: 6,
      maxLength: 1000,
      style: const TextStyle(fontSize: 16, color: AppColors.text),
      decoration: InputDecoration(
        hintText: '오늘 부모님은 어떠셨나요?',
        hintStyle: const TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w700,
          color: AppColors.subtext,
        ),
        counterText: '',
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.all(16),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppColors.track),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppColors.primaryGlow),
        ),
      ),
    );
  }

  Widget _sourceChips() {
    return Wrap(
      spacing: 18,
      children: [
        for (final entry in sourceLabels.entries)
          _Pill(
            label: entry.value,
            selected: _source == entry.key,
            onTap: () => setState(() => _source = entry.key),
          ),
      ],
    );
  }

  Widget _primaryButton(String label, VoidCallback? onPressed) {
    return FilledButton(
      onPressed: onPressed,
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.primaryGlow,
        disabledBackgroundColor: AppColors.track,
        disabledForegroundColor: AppColors.subtext,
        minimumSize: const Size.fromHeight(52),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
      child: Text(label),
    );
  }

  Widget _recentHeader() {
    return Row(
      children: [
        const Expanded(
          child: Text(
            '최근 기록',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
        ),
        TextButton(
          onPressed: () => context.go('/records'),
          style: TextButton.styleFrom(foregroundColor: AppColors.text),
          child: const Text(
            '더보기',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
        ),
      ],
    );
  }

  static String _clock(Duration d) =>
      '${d.inMinutes}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';
}

/// 녹음 버튼 (Figma: 바깥 원 176 mint, 안쪽 140)
/// 대기: 진한 녹색 + 마이크 / 녹음 중: 더 진한 녹색 + 흰 정지 사각형
class _RecordButton extends StatelessWidget {
  const _RecordButton({required this.recording, required this.onTap});

  final bool recording;
  final VoidCallback onTap;

  static const _recordingColor = Color(0xFF0F2A28);

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: recording ? '녹음 멈추기' : '녹음 시작',
      child: Container(
        width: 176,
        height: 176,
        padding: const EdgeInsets.all(18),
        decoration: const BoxDecoration(
          color: AppColors.mint,
          shape: BoxShape.circle,
        ),
        child: Material(
          color: recording ? _recordingColor : AppColors.primary,
          shape: const CircleBorder(),
          child: InkWell(
            onTap: onTap,
            customBorder: const CircleBorder(),
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 200),
              child: recording
                  ? Container(
                      key: const ValueKey('stop'),
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(8),
                      ),
                    )
                  : const Icon(
                      Icons.mic_none,
                      key: ValueKey('mic'),
                      size: 56,
                      color: Colors.white,
                    ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 파형 막대 11개 (소리 크기에 따라 높이)
class _Waveform extends StatelessWidget {
  const _Waveform({required this.levels});

  final List<double> levels;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          for (final level in levels)
            AnimatedContainer(
              duration: const Duration(milliseconds: 100),
              margin: const EdgeInsets.symmetric(horizontal: 3),
              width: 4,
              height: 40 * level,
              decoration: BoxDecoration(
                color: AppColors.primaryGlow,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
        ],
      ),
    );
  }
}

/// 둥근 선택 칩 (주제·출처). 선택: mint + 녹색 테두리
class _Pill extends StatelessWidget {
  const _Pill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      selected: selected,
      button: true,
      child: Material(
        color: selected ? AppColors.mint : Colors.white,
        shape: StadiumBorder(
          side: BorderSide(
            color: selected ? AppColors.primaryGlow : AppColors.track,
          ),
        ),
        child: InkWell(
          onTap: onTap,
          customBorder: const StadiumBorder(),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Text(
                label,
                style: const TextStyle(fontSize: 15, color: AppColors.text),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 흰 카드 (모서리 16)
class _Card extends StatelessWidget {
  const _Card({required this.child, this.padding = const EdgeInsets.all(16)});

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
      ),
      child: child,
    );
  }
}

/// D-day 카드 (Figma: mint 배경, 방문조사 D-3 / 10/28(수))
class _DdayCard extends StatelessWidget {
  const _DdayCard({required this.dday, required this.onTap});

  final Dday dday;
  final VoidCallback onTap;

  static const _weekdays = ['월', '화', '수', '목', '금', '토', '일'];

  String get _title => switch (dday.status) {
    'upcoming' => '방문조사 D-${dday.daysLeft}',
    'today' => '방문조사 D-day',
    'past' => '방문조사 D+${-(dday.daysLeft ?? 0)}',
    _ => '방문조사 날짜를 정해 주세요',
  };

  String? get _date {
    final d = dday.surveyDate;
    if (d == null) return null;
    return '${d.month}/${d.day}(${_weekdays[d.weekday - 1]})';
  }

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.mint,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 14, 12, 14),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _title,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.text,
                      ),
                    ),
                    if (_date != null)
                      Text(
                        _date!,
                        style: const TextStyle(
                          fontSize: 15,
                          color: AppColors.subtext,
                        ),
                      ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, size: 28, color: AppColors.text),
            ],
          ),
        ),
      ),
    );
  }
}

/// 녹음 끝 (아직 휴대폰 안) → 다시 녹음 / 취소
class _ReviewCard extends StatelessWidget {
  const _ReviewCard({
    required this.duration,
    required this.onRetry,
    required this.onCancel,
  });

  final String duration;
  final VoidCallback onRetry;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.graphic_eq, color: AppColors.primaryGlow),
              const SizedBox(width: 8),
              Text(
                '$duration 녹음했어요',
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AppColors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            '분류 시작을 눌러야 저장돼요.',
            style: TextStyle(fontSize: 15, color: AppColors.subtext),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: _OutlinePill(label: '다시 녹음', onPressed: onRetry),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _OutlinePill(label: '취소', onPressed: onCancel),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SavingCard extends StatelessWidget {
  const _SavingCard({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return _Card(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 28),
      child: Column(
        children: [
          const CircularProgressIndicator(color: AppColors.primaryGlow),
          const SizedBox(height: 14),
          Text(
            message,
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
        ],
      ),
    );
  }
}

/// 저장 결과 (Figma: ✓ 신체 > 식사하기에 저장됐어요 + 글 + 분류 바꾸기 / 글 고치기)
class _ResultCard extends StatelessWidget {
  const _ResultCard({
    required this.title,
    required this.text,
    required this.pending,
    required this.onChangeClass,
    required this.onEditText,
    required this.onClose,
  });

  final String title;
  final String? text;
  final bool pending;
  final VoidCallback onChangeClass;
  final VoidCallback onEditText;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return _Card(
      padding: const EdgeInsets.fromLTRB(16, 8, 8, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(
                pending ? Icons.schedule : Icons.check_circle,
                size: 22,
                color: AppColors.primary,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                  ),
                ),
              ),
              IconButton(
                tooltip: '새로 기록하기',
                icon: const Icon(Icons.close, color: AppColors.subtext),
                onPressed: onClose,
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (text != null && text!.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.background,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      text!,
                      style: const TextStyle(
                        fontSize: 16,
                        color: AppColors.text,
                      ),
                    ),
                  ),
                ],
                if (pending)
                  const Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: Text(
                      '정리가 끝나면 기록함에서 볼 수 있어요.',
                      style: TextStyle(fontSize: 15, color: AppColors.subtext),
                    ),
                  )
                else ...[
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: _OutlinePill(
                          label: '분류 바꾸기',
                          onPressed: onChangeClass,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: _OutlinePill(
                          label: '글 고치기',
                          onPressed: onEditText,
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _OutlinePill extends StatelessWidget {
  const _OutlinePill({required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.primary,
        side: const BorderSide(color: AppColors.primaryGlow),
        minimumSize: const Size.fromHeight(52),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
      child: Text(label),
    );
  }
}

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../home/home_api.dart';
import '../record_api.dart';
import '../widgets/audio_player_bar.dart';
import '../widgets/record_sheets.dart';
import 'record_edit_screen.dart';

/// 상세를 열자마자 할 일 (홈 저장 결과 카드의 분류 바꾸기 · 글 고치기)
enum RecordAction { classify, edit }

/// 기록 상세 열기 (지금 탭 안에서 → 아래 탭 유지)
Future<void> openRecordDetail(
  BuildContext context,
  String recordId, {
  RecordAction? action,
  RecordApi? recordApi,
}) {
  return Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => RecordDetailScreen(recordId: recordId, initialAction: action, recordApi: recordApi),
    ),
  );
}

/// 기록 상세 (SCR A-DET-001~003)
///
/// - 머리글: 일어난 시각 (없으면 기록한 시각) · 작성자
/// - 분류 줄 (여러 개) + 바꾸기 / 글 / 수정됨 · 원문 보기 / 음성 / 출처 · 수정 이력 / 글 고치기 · 기록지에서 제외
/// - 다른 가족 기록: 보기만 (댓글 → 베타 이후)
/// - 정리 중 → 2초마다 확인, 60초까지
/// - 수정 → base_version = 본 edit_version. 409 EDIT_CONFLICT → 최신 기록 다시 불러옴
class RecordDetailScreen extends StatefulWidget {
  const RecordDetailScreen({
    super.key,
    required this.recordId,
    this.initialAction,
    this.recordApi,
    this.playerFactory,
  });

  final String recordId;
  final RecordAction? initialAction;

  /// 테스트용 교체
  final RecordApi? recordApi;
  final AudioPlayback Function()? playerFactory;

  @override
  State<RecordDetailScreen> createState() => _RecordDetailScreenState();
}

class _RecordDetailScreenState extends State<RecordDetailScreen> {
  static const _pollEvery = Duration(seconds: 2);
  static const _pollLimit = Duration(seconds: 60);

  late final RecordApi _api = widget.recordApi ?? RecordApi();

  RecordDetail? _record;
  RecordVersions? _versions;
  String? _loadError;
  bool _busy = false;
  bool _showOriginal = false;
  bool _showHistory = false;

  Timer? _poll;
  DateTime? _pollUntil;
  bool _pollGaveUp = false;

  @override
  void initState() {
    super.initState();
    _load(first: true);
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  // ── 불러오기 ──

  Future<void> _load({bool first = false}) async {
    try {
      final record = await _api.fetch(widget.recordId);
      if (!mounted) return;
      setState(() {
        _record = record;
        _loadError = null;
      });
      _watchProcessing();
      unawaited(_loadVersions());
      if (first) _runInitialAction();
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  Future<void> _loadVersions() async {
    try {
      final versions = await _api.fetchVersions(widget.recordId);
      if (mounted) setState(() => _versions = versions);
    } on ApiException {
      // 이력 못 불러옴 → 이력 줄만 비움
    }
  }

  void _runInitialAction() {
    final record = _record!;
    switch (widget.initialAction) {
      case RecordAction.classify when _canClassify(record):
        WidgetsBinding.instance.addPostFrameCallback((_) => _changeClass());
      case RecordAction.edit when _canEdit(record):
        WidgetsBinding.instance.addPostFrameCallback((_) => _edit());
      default:
    }
  }

  /// 정리 중 → 끝날 때까지 다시 조회 (최대 60초)
  void _watchProcessing() {
    final record = _record;
    if (record == null || !record.processing) {
      _poll?.cancel();
      _poll = null;
      return;
    }
    if (_poll != null) return;
    _pollGaveUp = false;
    _pollUntil = DateTime.now().add(_pollLimit);
    _poll = Timer.periodic(_pollEvery, (_) async {
      if (DateTime.now().isAfter(_pollUntil!)) {
        _poll?.cancel();
        _poll = null;
        if (mounted) setState(() => _pollGaveUp = true);
        return;
      }
      try {
        final fresh = await _api.fetch(widget.recordId);
        if (!mounted) return;
        setState(() => _record = fresh);
        if (!fresh.processing) {
          _poll?.cancel();
          _poll = null;
          recordsChanged.value++;
          unawaited(_loadVersions());
        }
      } on ApiException {
        // 일시 오류 → 다음 확인
      }
    });
  }

  // ── 수정 공통 ──

  void _toast(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  /// 서버 변경 → 화면·이력·다른 화면 갱신. 동시 수정 → 최신 기록 다시 불러옴
  Future<void> _mutate(Future<RecordDetail?> Function() action, {String? done}) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final updated = await action();
      if (!mounted || updated == null) return;
      setState(() => _record = updated);
      recordsChanged.value++;
      unawaited(_loadVersions());
      _watchProcessing();
      if (done != null) _toast(done);
    } on ApiException catch (e) {
      if (!mounted) return;
      _toast(e.message);
      if (e.code == 'EDIT_CONFLICT') await _load();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  bool _canClassify(RecordDetail r) => r.isMine && r.stage != 'transcription' && !r.isChecklist;
  bool _canEdit(RecordDetail r) => r.isMine && r.stage != 'transcription';

  // ── 동작 ──

  Future<void> _changeClass() async {
    final record = _record!;
    List<SurveyItem> items;
    try {
      items = await _api.surveyItems();
    } on ApiException catch (e) {
      _toast(e.message);
      return;
    }
    if (!mounted) return;
    final codes = await showClassifySheet(
      context,
      items: items,
      selected: [for (final i in record.items) i.code],
    );
    if (codes == null) return;
    await _mutate(
      () => _api.update(record.id, baseVersion: record.editVersion, itemCodes: codes),
      done: '분류를 바꿨어요.',
    );
  }

  Future<void> _changeSource() async {
    final record = _record!;
    final source = await showSourceSheet(context, current: record.source);
    if (source == null || source == record.source) return;
    await _mutate(() => _api.update(record.id, baseVersion: record.editVersion, source: source));
  }

  Future<void> _edit() async {
    final record = _record!;
    final symptom = record.symptom;
    if (symptom != null) {
      final edit = await showSymptomEditSheet(context, symptom);
      if (edit == null) return;
      await _mutate(
        () => _api.updateSymptom(
          record.id,
          baseVersion: record.editVersion,
          timeBand: edit.timeBand,
          count: edit.count,
          note: edit.note,
        ),
      );
      return;
    }
    final saved = await Navigator.of(context, rootNavigator: true).push<RecordDetail>(
      MaterialPageRoute(builder: (_) => RecordEditScreen(record: record, recordApi: _api)),
    );
    if (saved == null) return;
    await _mutate(() async => saved, done: '고쳤어요.');
  }

  Future<void> _exclude() async {
    final choice = await showExcludeDialog(context);
    if (choice == null || !mounted) return;
    if (choice == ExcludeChoice.reclassify) {
      await _changeClass();
      return;
    }
    await _mutate(() => _api.exclude(_record!.id), done: '기록지에서 뺐어요.');
  }

  Future<void> _include() => _mutate(() => _api.include(_record!.id), done: '기록지에 다시 넣었어요.');

  Future<void> _retry() async {
    await _mutate(() async {
      await _api.reclassify(_record!.id);
      return _api.fetch(_record!.id);
    });
  }

  /// 녹음 파일 문제 → 홈에서 새로 녹음하거나 글로 남기기
  void _goHome() {
    final router = GoRouter.maybeOf(context);
    if (router != null) {
      router.go('/home');
    } else {
      Navigator.of(context).pop();
    }
  }

  // ── 화면 ──

  static String _time(DateTime t) =>
      '${t.month}/${t.day} ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final record = _record;
    return Scaffold(
      appBar: AppBar(
        backgroundColor: AppColors.background,
        surfaceTintColor: Colors.transparent,
        titleSpacing: 0,
        title: Text(
          record == null ? '' : '${_time(record.occurredAt ?? record.recordedAt)} · ${record.authorLabel}',
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
        ),
      ),
      body: record == null
          ? Center(
              child: _loadError == null
                  ? const CircularProgressIndicator()
                  : Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_loadError!, style: const TextStyle(fontSize: 16, color: AppColors.subtext)),
                        TextButton(onPressed: _load, child: const Text('다시 시도')),
                      ],
                    ),
            )
          : _body(record),
    );
  }

  Widget _body(RecordDetail record) {
    final banner = _banner(record);
    final original = record.originalText;
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 32),
      children: [
        if (record.excluded) ...[_ExcludedBand(onInclude: record.isMine && !_busy ? _include : null), const SizedBox(height: 16)],
        _classLines(record),
        const SizedBox(height: 10),
        _bodyText(record),
        if (banner != null) ...[const SizedBox(height: 16), banner],
        if (record.isEdited && original != null && original.isNotEmpty) ...[
          const SizedBox(height: 20),
          InkWell(
            onTap: () => setState(() => _showOriginal = !_showOriginal),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 44),
              child: Row(
                children: [
                  const Text('수정됨 · 원문 보기', style: TextStyle(fontSize: 16, color: AppColors.subtext)),
                  Icon(_showOriginal ? Icons.expand_less : Icons.expand_more, color: AppColors.subtext),
                ],
              ),
            ),
          ),
          if (_showOriginal) ...[const SizedBox(height: 8), OriginalBlock(text: original)],
        ],
        if (record.isVoice && !record.audioAvailable) ...[
          const SizedBox(height: 20),
          const Text(
            '작성자가 탈퇴해 음성 파일은 삭제됐어요.',
            style: TextStyle(fontSize: 15, color: AppColors.subtext),
          ),
        ] else if (record.isVoice && record.audioSeconds != null) ...[
          const SizedBox(height: 20),
          AudioPlayerBar(
            seconds: record.audioSeconds!,
            loadUrl: () => _api.audioUrl(record.id),
            player: widget.playerFactory?.call(),
          ),
        ],
        const SizedBox(height: 20),
        _infoCard(record),
        if (record.isMine) ..._buttons(record),
      ],
    );
  }

  /// • 신체 > 계단 오르내리기 (여러 줄) + 바꾸기
  Widget _classLines(RecordDetail record) {
    final lines = <String>[
      if (record.items.isNotEmpty)
        for (final i in record.items) i.path
      else if (record.processing)
        record.stage == 'transcription' ? '받아쓰는 중…' : '분류하는 중…'
      else if (record.failed)
        '분석 실패'
      else
        '미분류',
    ];
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final line in lines)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: const BoxDecoration(color: AppColors.primaryGlow, shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 8),
                      Flexible(
                        child: Text(line, style: const TextStyle(fontSize: 16, color: AppColors.text)),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
        if (_canClassify(record))
          TextButton(
            onPressed: _busy ? null : _changeClass,
            style: TextButton.styleFrom(foregroundColor: AppColors.text, padding: const EdgeInsets.symmetric(horizontal: 8)),
            child: const Text('바꾸기', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          ),
      ],
    );
  }

  Widget _bodyText(RecordDetail record) {
    final text = record.currentText;
    if (text == null || text.isEmpty) {
      if (record.processing) {
        return Row(
          children: [
            const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: 10),
            Text(
              _pollGaveUp ? '아직 정리 중이에요. 잠시 뒤 다시 확인해 주세요.' : '정리하는 중이에요',
              style: const TextStyle(fontSize: 18, color: AppColors.subtext),
            ),
          ],
        );
      }
      return const Text('(내용 없음)', style: TextStyle(fontSize: 20, color: AppColors.subtext));
    }
    return Text(
      text,
      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text, height: 1.45),
    );
  }

  /// 실패 · 말소리 없음 안내 (작성자만 버튼)
  Widget? _banner(RecordDetail record) {
    final mine = record.isMine && !_busy;
    if (record.transcriptionFailed) {
      if (record.audioBroken) {
        return _Banner(
          message: '녹음 파일에 문제가 있어요. 다시 녹음하거나 글로 남겨 주세요.',
          actions: [if (mine) ('새로 기록하기', _goHome)],
        );
      }
      return _Banner(
        message: record.processingError == 'STT_NOT_CONFIGURED' ? '지금은 받아쓰기를 할 수 없어요.' : '받아쓰지 못했어요.',
        actions: [if (mine) ('다시 시도', _retry)],
      );
    }
    if (record.failed) {
      return _Banner(
        message: '분류하지 못했어요.',
        actions: [
          if (mine && record.classifiedBy != 'user') ('다시 시도', _retry),
          if (mine) ('직접 분류하기', _changeClass),
        ],
      );
    }
    if (record.transcriptEmpty && (record.currentText ?? '').isEmpty) {
      return _Banner(
        message: '말소리를 알아듣지 못했어요.',
        actions: [if (mine) ('글로 적기', _edit)],
        error: false,
      );
    }
    return null;
  }

  Widget _infoCard(RecordDetail record) {
    final versions = _versions;
    final history = versions?.history ?? const <RecordVersion>[];
    final summary = history.isEmpty
        ? '원문 · ${_time(record.recordedAt)}'
        : '수정 ${history.length}번 · ${_time(history.first.editedAt)}';
    return Container(
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
      padding: const EdgeInsets.symmetric(horizontal: 18),
      child: Column(
        children: [
          _InfoRow(
            label: '출처',
            value: sourceLabels[record.source] ?? record.source,
            valueIcon: record.source == 'call' ? Icons.phone_outlined : Icons.visibility_outlined,
            action: record.isMine ? '변경' : null,
            onTap: record.isMine && !_busy ? _changeSource : null,
          ),
          const Divider(height: 1, color: AppColors.border),
          _InfoRow(
            label: '수정 이력',
            value: summary,
            trailing: _showHistory ? Icons.expand_less : Icons.chevron_right,
            onTap: () => setState(() => _showHistory = !_showHistory),
          ),
          if (_showHistory) _timeline(record, history),
        ],
      ),
    );
  }

  /// 최신 먼저: 수정 (무엇 · 누가 · 언제) … 맨 아래 원문
  Widget _timeline(RecordDetail record, List<RecordVersion> history) {
    final rows = <(String, String?)>[];
    for (var i = 0; i < history.length; i++) {
      final v = history[i];
      final after = i == 0 ? _versions!.current : history[i - 1].before;
      final kinds = [for (final c in v.changed) _changeLabel(c, v.before, after)];
      rows.add((
        '${i == 0 ? '현재' : '수정'} · ${v.editorLabel} · ${_time(v.editedAt)}',
        kinds.join(' · '),
      ));
    }
    rows.add(('원문 · ${record.authorLabel} · ${_time(record.recordedAt)}', null));
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        children: [
          for (var i = 0; i < rows.length; i++)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: i == 0 ? AppColors.primaryGlow : AppColors.track,
                        shape: BoxShape.circle,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(rows[i].$1, style: const TextStyle(fontSize: 16, color: AppColors.text)),
                        if (rows[i].$2 != null)
                          Text(rows[i].$2!, style: const TextStyle(fontSize: 14, color: AppColors.subtext)),
                      ],
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  static String _changeLabel(String field, RecordSnapshot before, RecordSnapshot after) => switch (field) {
        'text' => '글 고침',
        'source' => '출처 ${sourceLabels[before.source] ?? before.source} → ${sourceLabels[after.source] ?? after.source}',
        'item_codes' => '분류 바꿈',
        'occurred_at' => '일어난 시각 바꿈',
        _ => field,
      };

  List<Widget> _buttons(RecordDetail record) {
    return [
      const SizedBox(height: 24),
      if (_canEdit(record))
        FilledButton(
          onPressed: _busy ? null : _edit,
          style: sheetButtonStyle().copyWith(backgroundColor: const WidgetStatePropertyAll(AppColors.primaryGlow)),
          child: Text(record.isSymptom ? '증상 고치기' : '글 고치기'),
        ),
      const SizedBox(height: 8),
      if (!record.excluded)
        TextButton(
          onPressed: _busy ? null : _exclude,
          style: TextButton.styleFrom(foregroundColor: AppColors.subtext),
          child: const Text('기록지에서 제외', style: TextStyle(fontSize: 16)),
        ),
    ];
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.label,
    required this.value,
    this.valueIcon,
    this.action,
    this.trailing = Icons.chevron_right,
    this.onTap,
  });

  final String label;
  final String value;
  final IconData? valueIcon;
  final String? action;
  final IconData trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 56),
        child: Row(
          children: [
            Text(label, style: const TextStyle(fontSize: 16, color: AppColors.text)),
            const Spacer(),
            if (valueIcon != null) ...[Icon(valueIcon, size: 20, color: AppColors.text), const SizedBox(width: 6)],
            Flexible(
              child: Text(
                value,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 16, color: AppColors.text),
              ),
            ),
            if (action != null) ...[
              const SizedBox(width: 12),
              Text(action!, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text)),
            ],
            if (onTap != null) Icon(trailing, color: AppColors.text),
          ],
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.message, required this.actions, this.error = true});

  final String message;
  final List<(String, VoidCallback)> actions;
  final bool error;

  @override
  Widget build(BuildContext context) {
    final color = error ? Theme.of(context).colorScheme.error : AppColors.subtext;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 14, 8, 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(message, style: TextStyle(fontSize: 16, color: color, fontWeight: FontWeight.w700)),
          if (actions.isNotEmpty)
            Align(
              alignment: Alignment.centerRight,
              child: Wrap(
                children: [
                  for (final (label, onTap) in actions) TextButton(onPressed: onTap, child: Text(label)),
                ],
              ),
            )
          else
            const SizedBox(height: 6),
        ],
      ),
    );
  }
}

class _ExcludedBand extends StatelessWidget {
  const _ExcludedBand({required this.onInclude});

  final VoidCallback? onInclude;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 4, 4, 4),
      decoration: BoxDecoration(color: AppColors.track, borderRadius: BorderRadius.circular(14)),
      child: Row(
        children: [
          const Expanded(
            child: Text('기록지에서 뺀 기록이에요', style: TextStyle(fontSize: 16, color: AppColors.text)),
          ),
          if (onInclude != null)
            TextButton(
              onPressed: onInclude,
              style: TextButton.styleFrom(foregroundColor: AppColors.primary),
              child: const Text('다시 넣기', style: TextStyle(fontWeight: FontWeight.w700)),
            ),
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../record_api.dart';
import '../widgets/record_sheets.dart';

/// 글 고치기 (Figma: 내용 입력칸 / 고쳐도 원문은 그대로 남아요 / 원문 / 취소 · 저장)
/// 저장 → 고친 기록 반환. 동시 수정 (409 EDIT_CONFLICT) → 최신 기록 불러와 순번 갱신, 내 글은 그대로
/// replaceVoice: 받아쓰기 실패 음성 → "글로 적기" (빈 칸에서 시작, 저장 = 글 기록으로 전환)
class RecordEditScreen extends StatefulWidget {
  const RecordEditScreen({super.key, required this.record, required this.recordApi, this.replaceVoice = false});

  final RecordDetail record;
  final RecordApi recordApi;
  final bool replaceVoice;

  @override
  State<RecordEditScreen> createState() => _RecordEditScreenState();
}

class _RecordEditScreenState extends State<RecordEditScreen> {
  late RecordDetail _record = widget.record;
  late final _text = TextEditingController(text: widget.record.currentText ?? '');
  bool _saving = false;
  String? _notice;

  // 글로 적기 = 글 기록 규칙 (1000자)
  int get _limit => _record.isVoice && !widget.replaceVoice ? 2000 : 1000;
  String get _value => _text.text.trim();
  bool get _changed => _value.isNotEmpty && _value != (_record.currentText ?? '');

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      final saved = widget.replaceVoice
          ? await widget.recordApi.replaceText(_record.id, _value)
          : await widget.recordApi.update(_record.id, baseVersion: _record.editVersion, text: _value);
      if (mounted) Navigator.of(context).pop(saved);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.code == 'EDIT_CONFLICT') {
        await _reloadAfterConflict(e.message);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// 다른 기기에서 먼저 저장 → 최신 글 보여 주고 다시 저장 가능 (순번 갱신)
  Future<void> _reloadAfterConflict(String message) async {
    try {
      final latest = await widget.recordApi.fetch(_record.id);
      if (!mounted) return;
      setState(() {
        _record = latest;
        _notice = '다른 곳에서 먼저 고쳤어요. 최신 글을 확인하고 다시 저장해 주세요.';
      });
    } on ApiException {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<bool> _confirmDiscard() async {
    if (!_changed) return true;
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: Colors.white,
        title: const Text('고친 내용을 버릴까요?'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('계속 고치기')),
          TextButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('버리기')),
        ],
      ),
    );
    return result ?? false;
  }

  Future<void> _leave() async {
    if (await _confirmDiscard() && mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final original = _record.originalText;
    final notice = _notice;
    return PopScope(
      canPop: !_changed,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _leave();
      },
      child: Scaffold(
        appBar: AppBar(
          backgroundColor: AppColors.background,
          surfaceTintColor: Colors.transparent,
          leading: IconButton(icon: const Icon(Icons.arrow_back), tooltip: '뒤로', onPressed: _leave),
          titleSpacing: 0,
          title: Text(
            widget.replaceVoice ? '글로 적기' : '글 고치기',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
          ),
        ),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          children: [
            if (notice != null) ...[
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(color: AppColors.mint, borderRadius: BorderRadius.circular(16)),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(notice, style: const TextStyle(fontSize: 16, color: AppColors.text)),
                    const SizedBox(height: 8),
                    Text(
                      '최신 글: ${_record.currentText ?? ''}',
                      style: const TextStyle(fontSize: 16, color: AppColors.subtext),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
            ],
            const Text('내용', style: TextStyle(fontSize: 16, color: AppColors.subtext)),
            const SizedBox(height: 8),
            TextField(
              controller: _text,
              autofocus: true,
              minLines: 4,
              maxLines: 10,
              maxLength: _limit,
              onChanged: (_) => setState(() {}),
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: AppColors.text, height: 1.4),
              decoration: InputDecoration(
                filled: true,
                fillColor: Colors.white,
                contentPadding: const EdgeInsets.all(16),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                  borderSide: const BorderSide(color: AppColors.primaryGlow, width: 1.5),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                  borderSide: const BorderSide(color: AppColors.primaryGlow, width: 2),
                ),
              ),
            ),
            Text(
              widget.replaceVoice ? '녹음 대신 이 글로 저장돼요. 기록한 시각은 그대로예요.' : '고쳐도 원문은 그대로 남아요',
              style: const TextStyle(fontSize: 16, color: AppColors.subtext),
            ),
            if (original != null && original.isNotEmpty) ...[
              const SizedBox(height: 24),
              OriginalBlock(text: original),
            ],
          ],
        ),
        bottomNavigationBar: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
            child: Row(
              children: [
                Expanded(
                  child: FilledButton(
                    onPressed: _saving ? null : _leave,
                    style: sheetButtonStyle().copyWith(
                      backgroundColor: const WidgetStatePropertyAll(AppColors.track),
                      foregroundColor: const WidgetStatePropertyAll(AppColors.text),
                    ),
                    child: const Text('취소'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: _changed && !_saving ? _save : null,
                    style: sheetButtonStyle(),
                    child: _saving
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                          )
                        : const Text('저장'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 원문 블록 (왼쪽 세로줄 + "원문" + 글)
class OriginalBlock extends StatelessWidget {
  const OriginalBlock({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.only(left: 12),
      decoration: const BoxDecoration(border: Border(left: BorderSide(color: AppColors.primary, width: 2))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('원문', style: TextStyle(fontSize: 14, color: AppColors.subtext)),
          const SizedBox(height: 4),
          Text(text, style: const TextStyle(fontSize: 16, color: AppColors.text, height: 1.5)),
        ],
      ),
    );
  }
}

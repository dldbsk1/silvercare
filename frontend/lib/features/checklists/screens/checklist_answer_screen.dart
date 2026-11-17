import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../home/home_api.dart';
import '../checklist_api.dart';
import '../widgets/checklist_widgets.dart';

/// 답하기: 한 화면 한 항목 (1/4) → 모두 답했어요 확인 → [보내기]
/// - [다음]: 답이 바뀌었을 때만 저장 (PUT), 성공 → 다음 항목
/// - 처음 화면 = 첫 미답 항목 (이어서 하기)
/// - 보내기 성공 → pop(true), 기록함·홈 새로고침 (recordsChanged)
class ChecklistAnswerScreen extends StatefulWidget {
  const ChecklistAnswerScreen({super.key, required this.checklist, required this.api});

  final Checklist checklist;
  final ChecklistApi api;

  @override
  State<ChecklistAnswerScreen> createState() => _ChecklistAnswerScreenState();
}

class _ChecklistAnswerScreenState extends State<ChecklistAnswerScreen> {
  late List<ChecklistTask> _tasks = [...widget.checklist.items];

  /// 0..n-1 항목, n = 모두 답했어요
  late int _index = _firstUnanswered();

  String? _choice;
  bool _noteOpen = false;
  final _note = TextEditingController();
  bool _busy = false;

  int get _total => _tasks.length;
  bool get _review => _index >= _total;

  int _firstUnanswered() {
    final i = widget.checklist.items.indexWhere((t) => t.answer == null);
    return i < 0 ? widget.checklist.items.length : i;
  }

  @override
  void initState() {
    super.initState();
    _syncFields();
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  void _syncFields() {
    if (_review) return;
    final task = _tasks[_index];
    _choice = task.answer;
    _note.text = task.note ?? '';
    _noteOpen = (task.note ?? '').isNotEmpty;
  }

  void _go(int index) {
    setState(() {
      _index = index;
      _syncFields();
    });
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _next() async {
    final task = _tasks[_index];
    final choice = _choice;
    if (choice == null) return;
    final note = _note.text.trim().isEmpty ? null : _note.text.trim();

    if (choice != task.answer || note != task.note) {
      setState(() => _busy = true);
      try {
        final saved = await widget.api.answer(widget.checklist.id, task.taskId, answer: choice, note: note);
        _tasks = [..._tasks]..[_index] = saved;
      } on ApiException catch (e) {
        if (mounted) {
          setState(() => _busy = false);
          _onError(e);
        }
        return;
      }
      if (!mounted) return;
      setState(() => _busy = false);
    }

    final nextUnanswered = _tasks.indexWhere((t) => t.answer == null);
    _go(_index + 1 < _total && _tasks[_index + 1].answer == null
        ? _index + 1
        : (nextUnanswered < 0 ? _total : nextUnanswered));
  }

  Future<void> _submit() async {
    setState(() => _busy = true);
    try {
      final done = await widget.api.submit(widget.checklist.id);
      if (!mounted) return;
      recordsChanged.value++;
      final saved = done.items.where((t) => t.recordId != null).length;
      // 화면 닫은 뒤에도 보이게 이전 화면의 알림 영역에 표시
      final messenger = ScaffoldMessenger.of(context);
      Navigator.of(context).pop(true);
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(saved > 0 ? '보냈어요. 기록 $saved건이 저장됐어요.' : '보냈어요.')));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      if (e.code == 'INCOMPLETE_ANSWERS') {
        final ids = ((e.details as Map?)?['task_ids'] as List?)?.cast<String>() ?? const [];
        final i = _tasks.indexWhere((t) => ids.contains(t.taskId));
        if (i >= 0) _go(i);
      }
      _onError(e);
    }
  }

  void _onError(ApiException e) {
    if (e.code == 'CHECKLIST_CANCELLED' || e.code == 'CHECKLIST_SUBMITTED') {
      Navigator.of(context).pop(false);
      return;
    }
    _toast(e.message);
  }

  void _back() {
    if (_index == 0) {
      Navigator.of(context).pop(false);
    } else {
      _go(_index - 1);
    }
  }

  @override
  Widget build(BuildContext context) {
    final answered = _tasks.where((t) => t.answer != null).length;
    return PopScope(
      canPop: _index == 0,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        backgroundColor: AppColors.background,
        appBar: AppBar(
          backgroundColor: AppColors.background,
          surfaceTintColor: Colors.transparent,
          leading: IconButton(icon: const Icon(Icons.arrow_back), tooltip: '뒤로', onPressed: _back),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: 20),
              child: Center(
                child: Text(
                  '${_review ? _total : _index + 1}/$_total',
                  style: const TextStyle(fontSize: 16, color: AppColors.text),
                ),
              ),
            ),
          ],
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(12),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 7),
              child: SegmentBar(total: _total, filled: _review ? _total : _index + 1),
            ),
          ),
        ),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 24, 16, 16),
            child: _review ? _reviewBody(answered) : _questionBody(_tasks[_index]),
          ),
        ),
      ),
    );
  }

  Widget _questionBody(ChecklistTask task) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppColors.primary),
          ),
          child: Text(task.label, style: const TextStyle(fontSize: 16, color: AppColors.text)),
        ),
        const SizedBox(height: 10),
        Text(task.hint, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: AppColors.text)),
        const SizedBox(height: 20),
        Expanded(
          child: ListView(
            children: [
              for (final choice in task.choices) ...[
                if (choice == notSeen) const SizedBox(height: 8),
                _ChoiceButton(
                  label: answerLabels[choice] ?? choice,
                  selected: _choice == choice,
                  onTap: _busy
                      ? null
                      : () => setState(() {
                            _choice = choice;
                          }),
                ),
                const SizedBox(height: 10),
              ],
              if (_choice != null && !_noteOpen)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: () => setState(() => _noteOpen = true),
                    icon: const Icon(Icons.add, color: AppColors.primary),
                    label: const Text(
                      '한 줄 덧붙이기',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.primary),
                    ),
                  ),
                ),
              if (_noteOpen)
                TextField(
                  controller: _note,
                  maxLength: 200,
                  autofocus: (_tasks[_index].note ?? '').isEmpty,
                  style: const TextStyle(fontSize: 16),
                  decoration: InputDecoration(
                    hintText: '예: 밤에는 부축이 필요해요',
                    filled: true,
                    fillColor: Colors.white,
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
            ],
          ),
        ),
        _bottomButton('다음', _choice != null && !_busy ? _next : null),
      ],
    );
  }

  Widget _reviewBody(int answered) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('모두 답했어요', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700, color: AppColors.text)),
        const SizedBox(height: 4),
        const Text('보내기 전에 한 번 확인해 보세요', style: TextStyle(fontSize: 16, color: AppColors.subtext)),
        const SizedBox(height: 16),
        Expanded(
          child: ListView(
            children: [
              WhiteCard(
                padding: EdgeInsets.zero,
                child: Column(
                  children: [
                    for (var i = 0; i < _tasks.length; i++) ...[
                      if (i > 0) const Divider(height: 1, color: AppColors.border),
                      InkWell(
                        onTap: _busy ? null : () => _go(i),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      _tasks[i].label,
                                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                                    ),
                                  ),
                                  if (_tasks[i].answer != null) AnswerBadge(answer: _tasks[i].answer!),
                                ],
                              ),
                              if ((_tasks[i].note ?? '').isNotEmpty)
                                Padding(
                                  padding: const EdgeInsets.only(top: 6),
                                  child: Text(
                                    _tasks[i].note!,
                                    style: const TextStyle(fontSize: 15, color: AppColors.subtext),
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 12),
              const Text(
                '못 봤어요로 답한 항목은 기록으로 저장하지 않고, 다음에 다시 물어봐요',
                style: TextStyle(fontSize: 15, color: AppColors.subtext),
              ),
            ],
          ),
        ),
        _bottomButton('보내기', answered == _total && !_busy ? _submit : null),
      ],
    );
  }

  Widget _bottomButton(String label, VoidCallback? onPressed) {
    return FilledButton(
      onPressed: onPressed,
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.primaryGlow,
        disabledBackgroundColor: AppColors.track,
        minimumSize: const Size.fromHeight(52),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
      child: _busy
          ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
          : Text(label),
    );
  }
}

class _ChoiceButton extends StatelessWidget {
  const _ChoiceButton({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? AppColors.mint : Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: selected ? AppColors.primaryGlow : AppColors.border, width: selected ? 1.5 : 1),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 56),
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: TextStyle(fontSize: 16, fontWeight: selected ? FontWeight.w700 : FontWeight.w400),
                ),
              ),
              if (selected) const Icon(Icons.check, color: AppColors.primary),
            ],
          ),
        ),
      ),
    );
  }
}

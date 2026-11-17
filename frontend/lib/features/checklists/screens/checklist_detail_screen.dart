import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../checklist_api.dart';
import '../widgets/checklist_widgets.dart';

/// 보낸 체크리스트 상세 ("형 · 11/5")
/// - 진행 n/m · 대기/완료, 항목별 답 (보내기 전에도 지금까지 답), 메모 💬, 답 없음 → "답 안 함"
class ChecklistDetailScreen extends StatefulWidget {
  const ChecklistDetailScreen({super.key, required this.checklistId, required this.api});

  final String checklistId;
  final ChecklistApi api;

  @override
  State<ChecklistDetailScreen> createState() => _ChecklistDetailScreenState();
}

class _ChecklistDetailScreenState extends State<ChecklistDetailScreen> {
  Checklist? _checklist;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final checklist = await widget.api.fetch(widget.checklistId);
      if (mounted) setState(() => _checklist = checklist);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = _checklist;
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        surfaceTintColor: Colors.transparent,
        titleSpacing: 0,
        title: Text(
          c == null ? '' : '${c.to.label} · ${c.dueDate.month}/${c.dueDate.day}',
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
        ),
      ),
      body: c == null
          ? Center(
              child: _error == null
                  ? const CircularProgressIndicator()
                  : Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_error!, style: const TextStyle(fontSize: 16, color: AppColors.subtext)),
                        TextButton(onPressed: _load, child: const Text('다시 시도')),
                      ],
                    ),
            )
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
                children: [
                  _summary(c),
                  const SizedBox(height: 20),
                  const Padding(
                    padding: EdgeInsets.only(bottom: 10),
                    child: Text('항목별 답', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  ),
                  _answers(c),
                ],
              ),
            ),
    );
  }

  Widget _summary(Checklist c) {
    final to = c.to.isMe ? '나' : c.to.label;
    return WhiteCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '$to에게 보낸 체크리스트',
                      style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: AppColors.text),
                    ),
                    Text('확인 날짜 ${shortDate(c.dueDate)}', style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
                  ],
                ),
              ),
              StatusBadge(status: c.status),
            ],
          ),
          const SizedBox(height: 14),
          SegmentBar(total: c.totalItems, filled: c.answeredItems),
          const SizedBox(height: 8),
          Text('${c.answeredItems}/${c.totalItems} 진행', style: const TextStyle(fontSize: 15, color: AppColors.text)),
        ],
      ),
    );
  }

  Widget _answers(Checklist c) {
    return WhiteCard(
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          for (var i = 0; i < c.items.length; i++) ...[
            if (i > 0) const Divider(height: 1, color: AppColors.border),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Row(
                children: [
                  Expanded(
                    child: Text(c.items[i].label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  ),
                  if (c.items[i].answer != null)
                    AnswerBadge(answer: c.items[i].answer!)
                  else
                    const Text('답 안 함', style: TextStyle(fontSize: 15, color: AppColors.subtext)),
                ],
              ),
            ),
            if ((c.items[i].note ?? '').isNotEmpty) ...[
              const Divider(height: 1, color: AppColors.border),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                child: Row(
                  children: [
                    const Icon(Icons.chat_bubble_outline, size: 18, color: AppColors.subtext),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(c.items[i].note!, style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

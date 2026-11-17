import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../home/home_api.dart';

/// 기록 한 장 (홈 최근 기록 · 기록함 공통)
/// Figma: "19:40 · 나 · 직접 봄 · 수정됨" / [신체] 글 / 오른쪽 위 입력 방식 아이콘
class RecordCard extends StatelessWidget {
  const RecordCard({super.key, required this.record, this.showDay = true, this.onTap});

  final RecordSummary record;

  /// 날짜 표시 (홈: "어제 21:10" / 기록함: 날짜 머리글 있음 → "21:10")
  final bool showDay;
  final VoidCallback? onTap;

  String get _when {
    final t = record.recordedAt;
    final time = '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    if (!showDay) return time;
    final now = DateTime.now();
    final diff = DateTime(now.year, now.month, now.day).difference(DateTime(t.year, t.month, t.day)).inDays;
    if (diff == 0) return '오늘 $time';
    if (diff == 1) return '어제 $time';
    return '${t.month}/${t.day} $time';
  }

  String get _meta => [
        _when,
        record.isMine ? '나' : (record.authorName ?? '가족'),
        sourceLabels[record.source] ?? record.source,
        if (record.isEdited) '수정됨',
      ].join(' · ');

  IconData get _icon {
    if (record.inputType == 'voice') return Icons.mic_none;
    if (record.inputType == 'symptom') return Icons.monitor_heart_outlined;
    if (record.inputType == 'checklist') return Icons.checklist;
    if (record.source == 'call') return Icons.phone_outlined;
    return Icons.edit_outlined;
  }

  /// 영역 태그. 처리 중·실패·미분류 → 상태 글자
  String get _tag {
    if (record.areas.isNotEmpty) return areaLabels[record.areas.first] ?? record.areas.first;
    return switch (record.processingStatus) {
      'pending' || 'processing' => '정리 중',
      'failed' => '분석 실패',
      _ => '미분류',
    };
  }

  String get _text {
    final text = record.currentText;
    if (text != null && text.isNotEmpty) return text;
    if (record.inputType == 'voice' && record.processingStatus != 'failed') return '받아쓰는 중…';
    return '(내용 없음)';
  }

  @override
  Widget build(BuildContext context) {
    final tagColor = record.processingStatus == 'failed' ? Theme.of(context).colorScheme.error : AppColors.primary;
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 14, 16, 14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(_meta, style: const TextStyle(fontSize: 16, color: AppColors.subtext)),
                  ),
                  Icon(_icon, size: 24, color: AppColors.subtext),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: tagColor),
                    ),
                    child: Text(_tag, style: TextStyle(fontSize: 16, color: tagColor)),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _text,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 16, color: AppColors.text),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

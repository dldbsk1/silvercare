import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../checklist_api.dart';

const _weekdays = ['월', '화', '수', '목', '금', '토', '일'];

/// 11/5(목)
String shortDate(DateTime d) => '${d.month}/${d.day}(${_weekdays[d.weekday - 1]})';

/// 받침 있음 → 이, 없음 → 가 ("동생이", "형이", "누나가")
String subjectJosa(String name) {
  if (name.isEmpty) return '이';
  final code = name.codeUnitAt(name.length - 1);
  if (code < 0xAC00 || code > 0xD7A3) return '이';
  return (code - 0xAC00) % 28 == 0 ? '가' : '이';
}

/// 확인 날짜 문구: 오늘까지 · 내일까지 · 11/5(목)까지 · 지남
String dueText(DateTime due, DateTime now) {
  final today = DateTime(now.year, now.month, now.day);
  final days = DateTime(due.year, due.month, due.day).difference(today).inDays;
  if (days < 0) return '${shortDate(due)}까지였어요';
  if (days == 0) return '오늘까지';
  if (days == 1) return '내일까지';
  return '${shortDate(due)}까지';
}

/// 진행 막대 (항목 수만큼 칸)
class SegmentBar extends StatelessWidget {
  const SegmentBar({super.key, required this.total, required this.filled});

  final int total;
  final int filled;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (var i = 0; i < total; i++) ...[
          if (i > 0) const SizedBox(width: 6),
          Expanded(
            child: Container(
              height: 5,
              decoration: BoxDecoration(
                color: i < filled ? AppColors.primaryGlow : AppColors.track,
                borderRadius: BorderRadius.circular(3),
              ),
            ),
          ),
        ],
      ],
    );
  }
}

/// 대기(테두리) · 완료(민트) · 취소됨
class StatusBadge extends StatelessWidget {
  const StatusBadge({super.key, required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final done = status == 'submitted';
    final cancelled = status == 'cancelled';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: done ? AppColors.mint : (cancelled ? AppColors.track : Colors.white),
        borderRadius: BorderRadius.circular(16),
        border: done || cancelled ? null : Border.all(color: AppColors.primary),
      ),
      child: Text(statusLabel(status), style: const TextStyle(fontSize: 15, color: AppColors.text)),
    );
  }
}

/// 답 배지 ("조금 도와드림")
class AnswerBadge extends StatelessWidget {
  const AnswerBadge({super.key, required this.answer});

  final String answer;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(color: AppColors.mint, borderRadius: BorderRadius.circular(16)),
      child: Text(answerLabels[answer] ?? answer, style: const TextStyle(fontSize: 15, color: AppColors.text)),
    );
  }
}

/// 흰 둥근 카드
class WhiteCard extends StatelessWidget {
  const WhiteCard({super.key, required this.child, this.padding = const EdgeInsets.all(16)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
      child: child,
    );
  }
}

/// 받은 체크리스트 카드: "동생이 보냈어요 · 내일까지 · 항목 4개 · 1/4 · [이어서 하기]"
class ReceivedCard extends StatelessWidget {
  const ReceivedCard({super.key, required this.checklist, required this.now, required this.onContinue});

  final Checklist checklist;
  final DateTime now;
  final VoidCallback onContinue;

  @override
  Widget build(BuildContext context) {
    final from = checklist.from.label;
    final started = checklist.answeredItems > 0;
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
                      checklist.from.isMe ? '내가 보냈어요' : '$from${subjectJosa(from)} 보냈어요',
                      style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: AppColors.text),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${dueText(checklist.dueDate, now)} · 항목 ${checklist.totalItems}개',
                      style: const TextStyle(fontSize: 15, color: AppColors.subtext),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: AppColors.primary),
                ),
                child: Text(
                  '${checklist.answeredItems}/${checklist.totalItems}',
                  style: const TextStyle(fontSize: 15, color: AppColors.text),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SegmentBar(total: checklist.totalItems, filled: checklist.answeredItems),
          const SizedBox(height: 14),
          FilledButton(
            onPressed: onContinue,
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primaryGlow,
              minimumSize: const Size.fromHeight(48),
              shape: const StadiumBorder(),
              textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
            child: Text(started ? '이어서 하기' : '시작하기'),
          ),
        ],
      ),
    );
  }
}

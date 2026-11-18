import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../checklists/screens/checklist_screen.dart';
import '../records/screens/record_detail_screen.dart';

/// 알림 누름 → 화면 이동 (알림 목록 · 푸시 공통)
///
/// - 체크리스트 받음·기한 지남 → 받은 탭 / 답함·취소 → 보낸 탭
/// - 댓글·기록 실패 → 기록 상세
/// - 가족 합류 → 가족 탭
/// - 조사 전날·컨디션 → 홈
Future<void> openNotificationTarget(
  BuildContext context, {
  required String type,
  String? parentId,
  Map<String, dynamic> payload = const {},
}) async {
  final recordId = payload['record_id'];
  switch (type) {
    case 'checklist_received' || 'checklist_overdue' when parentId != null:
      await Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => ChecklistScreen(parentId: parentId, initialTab: 1)),
      );
    case 'checklist_submitted' || 'checklist_cancelled' when parentId != null:
      await Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => ChecklistScreen(parentId: parentId)),
      );
    case 'record_comment' || 'record_failed' when recordId is String:
      await openRecordDetail(context, recordId);
    case 'family_joined':
      GoRouter.of(context).go('/family');
    default:
      GoRouter.of(context).go('/home');
  }
}

/// 종류별 아이콘
IconData notificationIcon(String type) => switch (type) {
      'checklist_received' || 'checklist_submitted' || 'checklist_cancelled' || 'checklist_overdue' =>
        Icons.checklist_rounded,
      'survey_briefing' => Icons.event_note_outlined,
      'condition_reminder' => Icons.favorite_border,
      'family_joined' => Icons.group_add_outlined,
      'record_comment' => Icons.chat_bubble_outline,
      'record_failed' => Icons.error_outline,
      _ => Icons.notifications_none,
    };

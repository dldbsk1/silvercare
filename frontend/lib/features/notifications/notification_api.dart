import '../../core/api/api_client.dart';

/// 알림 1건 (GET /notifications)
class AppNotification {
  AppNotification({
    required this.id,
    required this.type,
    required this.parentId,
    required this.title,
    required this.body,
    required this.payload,
    required this.createdAt,
    required this.readAt,
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) => AppNotification(
        id: json['notification_id'] as String,
        type: json['type'] as String,
        parentId: json['parent_id'] as String?,
        title: json['title'] as String,
        body: json['body'] as String?,
        payload: Map<String, dynamic>.from(json['payload'] as Map? ?? const {}),
        createdAt: DateTime.parse(json['created_at'] as String).toLocal(),
        readAt: json['read_at'] == null ? null : DateTime.parse(json['read_at'] as String).toLocal(),
      );

  final String id;

  /// checklist_received · checklist_submitted · checklist_cancelled · checklist_overdue
  /// survey_briefing · condition_reminder · family_joined · record_comment · record_failed
  final String type;
  final String? parentId;
  final String title;
  final String? body;

  /// 화면 이동용 (checklist_id · record_id …)
  final Map<String, dynamic> payload;
  final DateTime createdAt;
  final DateTime? readAt;

  bool get unread => readAt == null;

  AppNotification markedRead() => AppNotification(
        id: id,
        type: type,
        parentId: parentId,
        title: title,
        body: body,
        payload: payload,
        createdAt: createdAt,
        readAt: readAt ?? DateTime.now(),
      );
}

class NotificationPage {
  NotificationPage({required this.items, required this.nextCursor, required this.unreadCount});

  final List<AppNotification> items;
  final String? nextCursor;
  final int unreadCount;
}

/// 알림 목록 · 읽음 · 기기 등록 (푸시 토큰)
class NotificationApi {
  NotificationApi({this.client});

  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  Future<NotificationPage> fetch({String? cursor, int limit = 20}) async {
    final page = await _api.getPage('/notifications', query: {
      'limit': limit,
      'cursor': ?cursor,
    });
    final meta = Map<String, dynamic>.from(page['meta'] as Map);
    return NotificationPage(
      items: [for (final n in page['data'] as List) AppNotification.fromJson(n as Map<String, dynamic>)],
      nextCursor: meta['next_cursor'] as String?,
      unreadCount: meta['unread_count'] as int? ?? 0,
    );
  }

  Future<void> markRead(String notificationId) => _api.patch('/notifications/$notificationId/read');

  Future<void> markAllRead() => _api.post('/notifications/read-all');

  /// 푸시 토큰 등록 → device_id (로그아웃 때 삭제)
  Future<String> registerDevice({required String platform, required String token}) async {
    final data = await _api.post('/devices', body: {'platform': platform, 'push_token': token}) as Map<String, dynamic>;
    return data['device_id'] as String;
  }

  Future<void> deleteDevice(String deviceId) => _api.delete('/devices/$deviceId');
}

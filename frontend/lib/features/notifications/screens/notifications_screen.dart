import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../notification_api.dart';
import '../notification_routes.dart';

/// POP_A_NOTI 알림 목록
///
/// - 최신순, 끝까지 내리면 다음 20개
/// - 안 읽음: 굵은 제목 + 점. 누르면 읽음 → 해당 화면
/// - 모두 읽음 (안 읽은 알림 있을 때만)
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key, this.api, this.onOpen});

  /// 테스트용 교체
  final NotificationApi? api;
  final Future<void> Function(BuildContext context, AppNotification notification)? onOpen;

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  late final NotificationApi _api = widget.api ?? NotificationApi();

  final _items = <AppNotification>[];
  String? _cursor;
  int _unread = 0;
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final page = await _api.fetch();
      if (!mounted) return;
      setState(() {
        _items
          ..clear()
          ..addAll(page.items);
        _cursor = page.nextCursor;
        _unread = page.unreadCount;
        _loading = false;
        _error = null;
      });
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e.message;
        });
      }
    }
  }

  Future<void> _loadMore() async {
    final cursor = _cursor;
    if (cursor == null || _loadingMore) return;
    setState(() => _loadingMore = true);
    try {
      final page = await _api.fetch(cursor: cursor);
      if (!mounted) return;
      setState(() {
        _items.addAll(page.items);
        _cursor = page.nextCursor;
        _unread = page.unreadCount;
      });
    } on ApiException catch (e) {
      // INVALID_CURSOR 등 → 처음부터
      if (mounted && e.code == 'INVALID_CURSOR') await _load();
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _open(AppNotification item) async {
    if (item.unread) {
      _replace(item.markedRead());
      unawaited(_api.markRead(item.id).catchError((Object _) {}));
    }
    final open = widget.onOpen ??
        (context, n) => openNotificationTarget(context, type: n.type, parentId: n.parentId, payload: n.payload);
    await open(context, item);
  }

  void _replace(AppNotification read) {
    final index = _items.indexWhere((n) => n.id == read.id);
    if (index < 0) return;
    setState(() {
      _items[index] = read;
      if (_unread > 0) _unread--;
    });
  }

  Future<void> _readAll() async {
    try {
      await _api.markAllRead();
      if (!mounted) return;
      setState(() {
        for (var i = 0; i < _items.length; i++) {
          _items[i] = _items[i].markedRead();
        }
        _unread = 0;
      });
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: AppColors.background,
        surfaceTintColor: Colors.transparent,
        title: const Text('알림', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text)),
        actions: [
          if (_unread > 0)
            TextButton(
              onPressed: _readAll,
              style: TextButton.styleFrom(foregroundColor: AppColors.text),
              child: const Text('모두 읽음', style: TextStyle(fontSize: 16)),
            ),
        ],
      ),
      body: _body(),
    );
  }

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error!, style: const TextStyle(fontSize: 16, color: AppColors.subtext)),
            TextButton(
              onPressed: () {
                setState(() => _loading = true);
                _load();
              },
              child: const Text('다시 불러오기'),
            ),
          ],
        ),
      );
    }
    if (_items.isEmpty) {
      return RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          children: const [
            SizedBox(height: 120),
            Text(
              '아직 받은 알림이 없어요',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 16, color: AppColors.subtext),
            ),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(vertical: 8),
        itemCount: _items.length + (_cursor != null ? 1 : 0),
        separatorBuilder: (_, _) => const Divider(height: 1, color: AppColors.border),
        itemBuilder: (context, index) {
          if (index >= _items.length) {
            // 그리는 중 setState X → 다음 프레임에
            WidgetsBinding.instance.addPostFrameCallback((_) => _loadMore());
            return const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            );
          }
          return _NotificationTile(item: _items[index], onTap: () => _open(_items[index]));
        },
      ),
    );
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({required this.item, required this.onTap});

  final AppNotification item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Container(
        color: item.unread ? Colors.white : null,
        padding: const EdgeInsets.fromLTRB(20, 14, 16, 14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(notificationIcon(item.type), size: 26, color: item.unread ? AppColors.text : AppColors.subtext),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.title,
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: item.unread ? FontWeight.w700 : FontWeight.w400,
                      color: AppColors.text,
                    ),
                  ),
                  if (item.body != null && item.body!.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(item.body!, style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
                  ],
                  const SizedBox(height: 4),
                  Text(timeAgo(item.createdAt), style: const TextStyle(fontSize: 14, color: AppColors.subtext)),
                ],
              ),
            ),
            if (item.unread)
              Padding(
                padding: const EdgeInsets.only(top: 6, left: 8),
                child: Container(
                  key: const Key('unread-dot'),
                  width: 8,
                  height: 8,
                  decoration: const BoxDecoration(color: AppColors.primary, shape: BoxShape.circle),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 방금 · 5분 전 · 3시간 전 · 어제 · 11/5
String timeAgo(DateTime time, {DateTime? now}) {
  final current = now ?? DateTime.now();
  final diff = current.difference(time);
  if (diff.inMinutes < 1) return '방금';
  if (diff.inHours < 1) return '${diff.inMinutes}분 전';
  final today = DateTime(current.year, current.month, current.day);
  final day = DateTime(time.year, time.month, time.day);
  if (day == today) return '${diff.inHours}시간 전';
  if (today.difference(day).inDays == 1) return '어제';
  return '${time.month}/${time.day}';
}

import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../record_api.dart';

/// 기록 상세 아래 댓글 (A-DET-002)
///
/// - 오래된 순. 내 댓글 → [지우기]
/// - 입력칸: 관리자·쓰기 가족만 (보기 가족 → 목록만)
/// - 불러오기 실패 → 칸 숨김 (상세 화면은 그대로)
class RecordCommentsSection extends StatefulWidget {
  const RecordCommentsSection({super.key, required this.recordId, required this.api});

  final String recordId;
  final RecordApi api;

  @override
  State<RecordCommentsSection> createState() => _RecordCommentsSectionState();
}

class _RecordCommentsSectionState extends State<RecordCommentsSection> {
  static const _maxLength = 1000;

  final _controller = TextEditingController();
  RecordComments? _comments;
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _controller.addListener(() => setState(() {}));
    _load();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final comments = await widget.api.fetchComments(widget.recordId);
      if (mounted) setState(() => _comments = comments);
    } catch (_) {
      // 댓글 못 불러옴 → 칸 숨김
    }
  }

  Future<void> _send() async {
    final body = _controller.text.trim();
    final current = _comments;
    if (body.isEmpty || current == null || _sending) return;
    setState(() => _sending = true);
    try {
      final added = await widget.api.addComment(widget.recordId, body);
      if (!mounted) return;
      _controller.clear();
      FocusScope.of(context).unfocus();
      setState(() => _comments = RecordComments(items: [...current.items, added], canComment: current.canComment));
    } on ApiException catch (e) {
      _toast(e.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _delete(RecordComment comment) async {
    final current = _comments;
    if (current == null) return;
    try {
      await widget.api.deleteComment(widget.recordId, comment.id);
      if (!mounted) return;
      setState(() => _comments = RecordComments(
            items: [for (final c in current.items) if (c.id != comment.id) c],
            canComment: current.canComment,
          ));
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  static String _time(DateTime t) =>
      '${t.month}/${t.day} ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final comments = _comments;
    if (comments == null) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          comments.items.isEmpty ? '댓글' : '댓글 ${comments.items.length}',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: AppColors.text),
        ),
        const SizedBox(height: 8),
        if (comments.items.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text('아직 댓글이 없어요', style: TextStyle(fontSize: 15, color: AppColors.subtext)),
          ),
        for (final c in comments.items)
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${c.authorLabel} · ${_time(c.createdAt)}',
                        style: const TextStyle(fontSize: 14, color: AppColors.subtext),
                      ),
                      const SizedBox(height: 4),
                      Text(c.body, style: const TextStyle(fontSize: 16, color: AppColors.text, height: 1.4)),
                    ],
                  ),
                ),
                if (c.isMine)
                  TextButton(
                    onPressed: () => _delete(c),
                    style: TextButton.styleFrom(foregroundColor: AppColors.subtext),
                    child: const Text('지우기', style: TextStyle(fontSize: 14)),
                  ),
              ],
            ),
          ),
        if (comments.canComment) ...[
          const SizedBox(height: 4),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: TextField(
                  key: const Key('comment-input'),
                  controller: _controller,
                  minLines: 1,
                  maxLines: 4,
                  maxLength: _maxLength,
                  style: const TextStyle(fontSize: 16),
                  decoration: const InputDecoration(
                    hintText: '가족에게 한마디 남기기',
                    counterText: '',
                    filled: true,
                    fillColor: Colors.white,
                    border: OutlineInputBorder(borderSide: BorderSide.none),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                tooltip: '댓글 보내기',
                onPressed: _controller.text.trim().isEmpty || _sending ? null : _send,
                style: IconButton.styleFrom(backgroundColor: AppColors.primary, fixedSize: const Size(48, 48)),
                icon: const Icon(Icons.send_rounded, color: Colors.white),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

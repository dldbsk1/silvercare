import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// 웹: 녹음 결과 = blob: 주소 (파일 X)
Future<Uint8List> readAudio(String path) async {
  final response = await web.window.fetch(path.toJS).toDart;
  final buffer = await response.arrayBuffer().toDart;
  return buffer.toDart.asUint8List();
}

/// blob 메모리 해제
Future<void> deleteAudio(String path) async => web.URL.revokeObjectURL(path);

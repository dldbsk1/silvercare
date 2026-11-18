import 'dart:io';
import 'dart:typed_data';

/// 앱: 휴대폰 임시 파일
Future<Uint8List> readAudio(String path) => File(path).readAsBytes();

Future<void> deleteAudio(String path) async {
  final file = File(path);
  if (await file.exists()) await file.delete();
}

import 'package:flutter/material.dart';

/// Figma 화면 붙이기 전 임시 화면
class PlaceholderScreen extends StatelessWidget {
  const PlaceholderScreen({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(child: Text('$title (준비 중)')),
    );
  }
}

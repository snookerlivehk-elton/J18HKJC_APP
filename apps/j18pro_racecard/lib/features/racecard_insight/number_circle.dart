import 'package:flutter/material.dart';

/// W / Q / P / 4th, or an unsettled number.
enum CircleKind { plain, win, quinella, place, fourth, empty }

/// Tip / famous unsettled circles, plus the shared hit colors.
///
/// Unsettled light: white / `#1E2A38` / `#E88B2A`.
/// Unsettled dark: `#2A313C` / `#E8EEF6` / `#E88B2A`.
/// Hits stay the same in both themes.
class CirclePaint {
  const CirclePaint({
    required this.background,
    required this.foreground,
    required this.border,
  });

  final Color background;
  final Color foreground;
  final Color border;
}

CirclePaint circlePaint(CircleKind kind, Brightness brightness) {
  return switch (kind) {
    CircleKind.win => const CirclePaint(
      background: Color(0xFFCC453F),
      foreground: Color(0xFFFFFFFF),
      border: Color(0xFFCC453F),
    ),
    CircleKind.quinella => const CirclePaint(
      background: Color(0xFF2F70CA),
      foreground: Color(0xFFFFFFFF),
      border: Color(0xFF2F70CA),
    ),
    CircleKind.place => const CirclePaint(
      background: Color(0xFF3F8F4A),
      foreground: Color(0xFFFFFFFF),
      border: Color(0xFF3F8F4A),
    ),
    CircleKind.fourth => const CirclePaint(
      background: Color(0xFF8A6BB8),
      foreground: Color(0xFFFFFFFF),
      border: Color(0xFF8A6BB8),
    ),
    CircleKind.empty =>
      brightness == Brightness.dark
          ? const CirclePaint(
              background: Color(0xFF2A313C),
              foreground: Color(0xFF8A93A3),
              border: Color(0xFF5A4630),
            )
          : const CirclePaint(
              background: Color(0xFFF7F1E6),
              foreground: Color(0xFFB0B8C4),
              border: Color(0xFFE0C49A),
            ),
    CircleKind.plain =>
      brightness == Brightness.dark
          ? const CirclePaint(
              background: Color(0xFF2A313C),
              foreground: Color(0xFFE8EEF6),
              border: Color(0xFFE88B2A),
            )
          : const CirclePaint(
              background: Color(0xFFFFFFFF),
              foreground: Color(0xFF1E2A38),
              border: Color(0xFFE88B2A),
            ),
  };
}

/// Finish-list slot. Index 3 is 殿 (`#8A6BB8`); Web leaves that slot uncolored.
CircleKind finishKindAt(int index) {
  return switch (index) {
    0 => CircleKind.win,
    1 => CircleKind.quinella,
    2 => CircleKind.place,
    3 => CircleKind.fourth,
    _ => CircleKind.plain,
  };
}

/// Colors an index pick when it matches the finish order.
CircleKind kindForPick(int horseNo, List<int> finish) {
  for (var i = 0; i < finish.length && i < 4; i++) {
    if (finish[i] == horseNo) return finishKindAt(i);
  }
  return CircleKind.plain;
}

class NumberCircle extends StatelessWidget {
  const NumberCircle({required this.text, required this.kind, super.key});

  final String text;
  final CircleKind kind;

  @override
  Widget build(BuildContext context) {
    final paint = circlePaint(kind, Theme.of(context).brightness);
    return Semantics(
      label: text,
      child: Container(
        width: 26,
        height: 26,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: paint.background,
          shape: BoxShape.circle,
          border: Border.all(color: paint.border, width: 1.5),
        ),
        child: Text(
          text,
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 12,
            height: 1,
            fontWeight: FontWeight.w800,
            color: paint.foreground,
          ),
        ),
      ),
    );
  }
}

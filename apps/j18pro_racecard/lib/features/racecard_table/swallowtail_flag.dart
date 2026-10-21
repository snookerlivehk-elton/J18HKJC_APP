import 'package:flutter/material.dart';

/// Bookmark / swallowtail. Cycles none → yellow → green → none.
class SwallowtailFlag extends StatelessWidget {
  const SwallowtailFlag({
    required this.color,
    required this.mark,
    required this.onPressed,
    super.key,
  });

  final Color color;
  final int mark;
  final VoidCallback onPressed;

  String get semanticsLabel {
    if (mark == 1) return '黃標，再點改綠標';
    if (mark == 2) return '綠標，再點取消';
    return '標記此馬';
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: semanticsLabel,
      toggled: mark != 0,
      child: InkWell(
        onTap: onPressed,
        child: SizedBox(
          width: 32,
          height: 32,
          child: Center(
            child: CustomPaint(
              size: const Size(25, 28),
              painter: SwallowtailPainter(color),
            ),
          ),
        ),
      ),
    );
  }
}

/// Web path `M2 1h8v9.2L6 7.4 2 10.2V1z` in a 12×14 viewBox.
class SwallowtailPainter extends CustomPainter {
  const SwallowtailPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final sx = size.width / 12;
    final sy = size.height / 14;
    final path = Path()
      ..moveTo(2 * sx, 1 * sy)
      ..lineTo(10 * sx, 1 * sy)
      ..lineTo(10 * sx, 10.2 * sy)
      ..lineTo(6 * sx, 7.4 * sy)
      ..lineTo(2 * sx, 10.2 * sy)
      ..close();
    canvas.drawPath(path, Paint()..color = color);
  }

  @override
  bool shouldRepaint(SwallowtailPainter oldDelegate) => oldDelegate.color != color;
}

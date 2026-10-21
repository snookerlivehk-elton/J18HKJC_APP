import 'dart:math' as math;

import 'package:flutter/material.dart';

/// How many static marks `setScrubIndex` can address.
const scrubMarkCount = 10;

/// Web `SCRUB_MARK_DEFS` point.
class ScrubMark {
  const ScrubMark({
    required this.minsBefore,
    required this.lab,
    required this.pos,
    this.openLab = false,
  });

  final int minsBefore;
  final String lab;
  final double pos;
  final bool openLab;
}

const scrubMarks = <ScrubMark>[
  ScrubMark(minsBefore: 180, lab: '開始賠率', pos: 0, openLab: true),
  ScrubMark(minsBefore: 30, lab: "30'", pos: 22),
  ScrubMark(minsBefore: 15, lab: "15'", pos: 38),
  ScrubMark(minsBefore: 10, lab: "10'", pos: 50),
  ScrubMark(minsBefore: 5, lab: "5'", pos: 62),
  ScrubMark(minsBefore: 4, lab: "4'", pos: 71),
  ScrubMark(minsBefore: 3, lab: "3'", pos: 79),
  ScrubMark(minsBefore: 2, lab: "2'", pos: 86),
  ScrubMark(minsBefore: 1, lab: "1'", pos: 93),
  ScrubMark(minsBefore: 0, lab: "0'", pos: 100),
];

const scrubTrackInset = 8.0;

/// `-1` or an out-of-range index follows the latest point.
int activeScrubIndex(int stored, int length) {
  if (length <= 0) return 0;
  if (stored < 0 || stored >= length) return length - 1;
  return stored;
}

String scrubLabFor(int stored) {
  return scrubMarks[activeScrubIndex(stored, scrubMarks.length)].lab;
}

/// Web `buildScrubPoints` rotation. Each point rotates the base picks.
List<List<int>> buildScrubPicks(List<int> base) {
  return [
    for (var i = 0; i < scrubMarks.length; i++)
      _rotateLeft(base, math.min(i, math.max(0, base.length - 1))),
  ];
}

List<int> _rotateLeft(List<int> picks, int rot) {
  if (rot <= 0 || picks.isEmpty) return List<int>.of(picks);
  final shift = rot % picks.length;
  if (shift == 0) return List<int>.of(picks);
  return [...picks.sublist(shift), ...picks.sublist(0, shift)];
}

/// Nearest mark for a pointer x on a bar of [width]. Same inset as [TimeScrub].
int nearestScrubIndex(double width, double x) {
  if (scrubMarks.isEmpty) return 0;
  final track = math.max(1.0, width - scrubTrackInset * 2);
  final local = (x - scrubTrackInset).clamp(0.0, track);
  final pct = (local / track) * 100;
  var best = 0;
  var bestDist = double.infinity;
  for (var i = 0; i < scrubMarks.length; i++) {
    final distance = (scrubMarks[i].pos - pct).abs();
    if (distance < bestDist) {
      bestDist = distance;
      best = i;
    }
  }
  return best;
}

/// Static scrub. Dragging or tapping snaps to the nearest mark.
class TimeScrub extends StatelessWidget {
  const TimeScrub({
    required this.storedIndex,
    required this.onIndex,
    super.key,
  });

  /// Controller value. `-1` renders as the last mark.
  final int storedIndex;
  final ValueChanged<int> onIndex;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final dark = brightness == Brightness.dark;
    final active = activeScrubIndex(storedIndex, scrubMarks.length);
    final mark = scrubMarks[active];
    final idle = dark ? const Color(0xFF8A93A3) : const Color(0xFF8A93A3);
    final hot = dark ? const Color(0xFFF0A84A) : const Color(0xFFE88B2A);
    final trackColor = dark ? const Color(0xFF3A4250) : const Color(0xFFE4E7EC);
    final valueText = mark.minsBefore > 0
        ? '${mark.lab} 距開跑${mark.minsBefore}分'
        : '${mark.lab} 開跑';
    return Semantics(
      slider: true,
      label: '賽前時間軸',
      value: valueText,
      child: SizedBox(
        key: const Key('time-scrub'),
        height: 36,
        child: LayoutBuilder(
          builder: (context, constraints) {
            final width = constraints.maxWidth;
            void apply(double x) => onIndex(nearestScrubIndex(width, x));
            return GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTapDown: (details) => apply(details.localPosition.dx),
              onHorizontalDragStart: (details) =>
                  apply(details.localPosition.dx),
              onHorizontalDragUpdate: (details) =>
                  apply(details.localPosition.dx),
              child: Stack(
                children: [
                  for (var i = 0; i < scrubMarks.length; i++)
                    _ScrubLabel(
                      mark: scrubMarks[i],
                      active: i == active,
                      width: width,
                      idle: idle,
                      hot: hot,
                    ),
                  Positioned(
                    left: scrubTrackInset,
                    right: scrubTrackInset,
                    bottom: 2,
                    height: 10,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: trackColor,
                        borderRadius: BorderRadius.circular(5),
                      ),
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: FractionallySizedBox(
                          widthFactor: (mark.pos / 100).clamp(0.0, 1.0),
                          heightFactor: 1,
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              color: hot,
                              borderRadius: BorderRadius.circular(5),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

class _ScrubLabel extends StatelessWidget {
  const _ScrubLabel({
    required this.mark,
    required this.active,
    required this.width,
    required this.idle,
    required this.hot,
  });

  final ScrubMark mark;
  final bool active;
  final double width;
  final Color idle;
  final Color hot;

  @override
  Widget build(BuildContext context) {
    final track = math.max(1.0, width - scrubTrackInset * 2);
    final center = scrubTrackInset + track * (mark.pos / 100);
    final text = Text(
      mark.lab,
      key: active ? const Key('scrub-active') : null,
      maxLines: 1,
      style: TextStyle(
        fontFamily: 'Noto Sans TC',
        fontSize: mark.openLab ? 9 : 10,
        height: 1,
        fontWeight: active ? FontWeight.w800 : FontWeight.w400,
        color: active ? hot : idle,
      ),
    );
    if (mark.pos <= 0) {
      return Positioned(left: 0, top: 1, child: text);
    }
    if (mark.pos >= 100) {
      return Positioned(right: 0, top: 1, child: text);
    }
    return Positioned(
      left: center,
      top: 1,
      child: FractionalTranslation(
        translation: const Offset(-0.5, 0),
        child: text,
      ),
    );
  }
}

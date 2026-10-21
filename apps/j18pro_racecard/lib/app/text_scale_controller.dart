import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Web `LIST_ZOOM_MAX`: two steps above the default, each +10%.
const textScaleMaxLevel = 2;

/// Web `listZoomFactor`: `1 + level * 0.1`.
double textScaleFactor(int level) =>
    1 + level.clamp(0, textScaleMaxLevel) * 0.1;

final textScaleLevelProvider = NotifierProvider<TextScaleController, int>(
  TextScaleController.new,
);

class TextScaleController extends Notifier<int> {
  @override
  int build() => 0;

  void step(int delta) {
    final next = (state + delta).clamp(0, textScaleMaxLevel);
    if (next == state) return;
    state = next;
  }

  void reset() {
    if (state == 0) return;
    state = 0;
  }
}

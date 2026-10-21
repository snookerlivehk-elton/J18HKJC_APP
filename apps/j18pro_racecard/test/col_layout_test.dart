import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/features/col_sort/col_layout.dart';

void main() {
  test('missing storage and bad json stay on the phase 2 columns', () {
    expect(decodeColLayout(null).visible, defaultColLayout.visible);
    expect(decodeColLayout('').hidden, defaultColLayout.hidden);
    expect(decodeColLayout('not-json').visible, defaultColLayout.visible);
    expect(decodeColLayout('[]').visible, defaultColLayout.visible);
  });

  test('unknown and duplicate keys are dropped', () {
    final layout = decodeColLayout(
      jsonEncode({
        'v': ['draw', 'water', 'draw', 'win'],
        'h': ['win', 'nope', 'hw'],
      }),
    );
    expect(layout.visible.first, 'draw');
    expect(layout.visible[1], 'win');
    expect(layout.hidden, ['hw']);
    expect(layout.visible.contains('water'), isFalse);
    expect(layout.visible.where((id) => id == 'draw').length, 1);
  });

  test('a missing key is inserted after its visible catalog neighbour', () {
    final layout = decodeColLayout(
      jsonEncode({
        'v': ['draw', 'place'],
        'h': ['win'],
      }),
    );
    expect(layout.hidden, ['win']);
    expect(
      layout.visible.indexOf('form6'),
      layout.visible.indexOf('place') + 1,
    );
    expect(layout.visible.contains('jockey'), isTrue);
  });

  test('a missing key is appended when its neighbour is hidden', () {
    final layout = decodeColLayout(
      jsonEncode({
        'v': ['draw'],
        'h': ['win'],
      }),
    );
    expect(layout.visible.first, 'draw');
    expect(layout.visible[1], 'place');
    expect(layout.hidden, ['win']);
  });

  test('moves append, swap, and ignore the ends', () {
    final hidden = colMoveToHidden(defaultColLayout, 'win');
    expect(hidden.visible, ['draw', 'place', 'form6']);
    expect(hidden.hidden.last, 'win');

    final shown = colMoveToVisible(defaultColLayout, 'jockey');
    expect(shown.visible.last, 'jockey');
    expect(shown.hidden.contains('jockey'), isFalse);

    final up = colMoveVisible(defaultColLayout, 'form6', -1);
    expect(up.visible, ['draw', 'win', 'form6', 'place']);
    expect(colMoveVisible(defaultColLayout, 'draw', -1).visible, [
      'draw',
      'win',
      'place',
      'form6',
    ]);
    expect(colMoveVisible(defaultColLayout, 'form6', 1).visible, [
      'draw',
      'win',
      'place',
      'form6',
    ]);
    expect(
      colMoveToHidden(defaultColLayout, 'jockey').visible,
      defaultColLayout.visible,
    );
  });

  test('a complete layout round-trips', () {
    const layout = ColLayout(
      visible: ['jockey', 'draw'],
      hidden: [
        'win',
        'place',
        'form6',
        'hw',
        'trainer',
        'age',
        'rating',
        'career',
        'gear',
        'dam',
        'sire',
        'damsire',
        'owner',
        'prize',
      ],
    );
    final decoded = decodeColLayout(encodeColLayout(layout));
    expect(decoded.visible, layout.visible);
    expect(decoded.hidden, layout.hidden);
  });
}

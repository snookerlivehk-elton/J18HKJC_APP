import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/racecard_table/scroll_columns.dart';

/// Same key as Web `localStorage["j18-scroll-col-layout-v1"]`.
const colLayoutPreferenceKey = 'j18-scroll-col-layout-v1';

/// Official order used when a stored layout is missing a known column.
const colLayoutCatalog = <String>[
  'draw',
  'win',
  'place',
  'form6',
  'hw',
  'jockey',
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
];

/// Phase 2 table. Extra fields start hidden so the shipped columns stay put.
const defaultColLayout = ColLayout(
  visible: ['draw', 'win', 'place', 'form6'],
  hidden: [
    'hw',
    'jockey',
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

class ColLayout {
  const ColLayout({required this.visible, required this.hidden});

  final List<String> visible;
  final List<String> hidden;
}

final colLayoutProvider = NotifierProvider<ColLayoutController, ColLayout>(
  ColLayoutController.new,
);

/// Columns the main table should paint, in the saved order.
final visibleScrollColumnsProvider = Provider<List<ScrollColumn>>((ref) {
  final layout = ref.watch(colLayoutProvider);
  return [for (final id in layout.visible) ?scrollColumnById(id)];
});

class ColLayoutController extends Notifier<ColLayout> {
  @override
  ColLayout build() {
    final raw = ref
        .watch(sharedPreferencesProvider)
        .getString(colLayoutPreferenceKey);
    return decodeColLayout(raw);
  }

  Future<void> moveToHidden(String id) async {
    await _commit(colMoveToHidden(state, id));
  }

  Future<void> moveToVisible(String id) async {
    await _commit(colMoveToVisible(state, id));
  }

  /// [delta] is -1 for up and 1 for down. Only the visible list moves.
  Future<void> moveVisible(String id, int delta) async {
    await _commit(colMoveVisible(state, id, delta));
  }

  Future<void> reset() async {
    await _commit(defaultColLayout);
  }

  Future<void> _commit(ColLayout next) async {
    if (_same(state, next)) return;
    state = next;
    await ref
        .read(sharedPreferencesProvider)
        .setString(colLayoutPreferenceKey, encodeColLayout(next));
  }
}

bool _same(ColLayout a, ColLayout b) {
  if (a.visible.length != b.visible.length ||
      a.hidden.length != b.hidden.length) {
    return false;
  }
  for (var i = 0; i < a.visible.length; i++) {
    if (a.visible[i] != b.visible[i]) return false;
  }
  for (var i = 0; i < a.hidden.length; i++) {
    if (a.hidden[i] != b.hidden[i]) return false;
  }
  return true;
}

String encodeColLayout(ColLayout layout) {
  return jsonEncode({'v': layout.visible, 'h': layout.hidden});
}

/// Web `loadColLayout`. Unknown and duplicate keys are dropped.
/// A known key missing from both lists is inserted after its catalog neighbour.
ColLayout decodeColLayout(String? raw) {
  if (raw == null || raw.isEmpty) return defaultColLayout;
  try {
    final data = jsonDecode(raw);
    if (data is! Map) return defaultColLayout;
    final known = colLayoutCatalog.toSet();
    final seen = <String>{};
    final visible = <String>[];
    final hidden = <String>[];
    for (final id in _stringList(data['v'])) {
      if (!known.contains(id) || !seen.add(id)) continue;
      visible.add(id);
    }
    for (final id in _stringList(data['h'])) {
      if (!known.contains(id) || !seen.add(id)) continue;
      hidden.add(id);
    }
    for (var index = 0; index < colLayoutCatalog.length; index++) {
      final id = colLayoutCatalog[index];
      if (!seen.add(id)) continue;
      var placed = false;
      if (index > 0) {
        final previous = colLayoutCatalog[index - 1];
        final previousIndex = visible.indexOf(previous);
        if (previousIndex >= 0) {
          visible.insert(previousIndex + 1, id);
          placed = true;
        }
      }
      if (!placed) visible.add(id);
    }
    return ColLayout(visible: visible, hidden: hidden);
  } on FormatException {
    return defaultColLayout;
  }
}

List<String> _stringList(Object? raw) {
  if (raw is! List) return const [];
  return [
    for (final item in raw)
      if (item is String) item,
  ];
}

ColLayout colMoveToHidden(ColLayout layout, String id) {
  final index = layout.visible.indexOf(id);
  if (index < 0) return layout;
  final visible = [...layout.visible]..removeAt(index);
  final hidden = [...layout.hidden, if (!layout.hidden.contains(id)) id];
  return ColLayout(visible: visible, hidden: hidden);
}

ColLayout colMoveToVisible(ColLayout layout, String id) {
  final index = layout.hidden.indexOf(id);
  if (index < 0) return layout;
  final hidden = [...layout.hidden]..removeAt(index);
  final visible = [...layout.visible, if (!layout.visible.contains(id)) id];
  return ColLayout(visible: visible, hidden: hidden);
}

ColLayout colMoveVisible(ColLayout layout, String id, int delta) {
  final index = layout.visible.indexOf(id);
  if (index < 0) return layout;
  final next = index + delta;
  if (next < 0 || next >= layout.visible.length) return layout;
  final visible = [...layout.visible];
  final swapped = visible[index];
  visible[index] = visible[next];
  visible[next] = swapped;
  return ColLayout(visible: visible, hidden: layout.hidden);
}

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/synth_review/synth_review.dart';

/// Personal horse notes.
///
/// Web keeps these on the in-memory runner only. This app writes them so a
/// note is still there after a restart. This is not the tip-pick column
/// (`j18-tip-note-picks-v1`), which stays unimplemented.
///
/// Stored JSON:
/// `{ "v": 1, "notes": { "2026-09-23:5:5": { "text": "", "history": [] } } }`
///
/// The map key is `date:raceNum:horseNo` ([horseNoteStorageKey]). A stored
/// record replaces the demo seed for that horse, even when `text` is empty.
const horseNotesPreferenceKey = 'j18-horse-notes-v1';

final horseNotesProvider =
    NotifierProvider<HorseNotesController, Map<String, HorseNoteRecord>>(
      HorseNotesController.new,
    );

class HorseNotesController extends Notifier<Map<String, HorseNoteRecord>> {
  @override
  Map<String, HorseNoteRecord> build() {
    final raw = ref
        .watch(sharedPreferencesProvider)
        .getString(horseNotesPreferenceKey);
    return decodeHorseNotes(raw);
  }

  /// Returns false when the horse is scratched or missing from the save.
  Future<bool> save({
    required String date,
    required int raceNum,
    required Runner runner,
    required String raceMeta,
    required String courseLabel,
    required String draft,
  }) async {
    if (runner.scratched) return false;
    final key = horseNoteStorageKey(date, raceNum, runner.no);
    final current = resolveHorseNote(
      saved: state,
      date: date,
      raceNum: raceNum,
      horseNo: runner.no,
      scratched: false,
    );
    final next = applyHorseNoteSave(
      current: current,
      draft: draft,
      meetingDate: date,
      runner: runner,
      raceMeta: raceMeta,
      courseLabel: courseLabel,
      id: 'n${DateTime.now().microsecondsSinceEpoch}',
    );
    final updated = Map<String, HorseNoteRecord>.of(state);
    updated[key] = next;
    state = updated;
    await ref
        .read(sharedPreferencesProvider)
        .setString(horseNotesPreferenceKey, encodeHorseNotes(updated));
    return true;
  }
}

String encodeHorseNotes(Map<String, HorseNoteRecord> notes) {
  return jsonEncode({
    'v': 1,
    'notes': {
      for (final entry in notes.entries) entry.key: entry.value.toJson(),
    },
  });
}

/// Drops a payload whose `v` is present and not 1. Unknown horses stay.
Map<String, HorseNoteRecord> decodeHorseNotes(String? raw) {
  if (raw == null || raw.isEmpty) return const {};
  try {
    final data = jsonDecode(raw);
    if (data is! Map) return const {};
    final version = data['v'];
    if (version != null && version != 1) return const {};
    final notes = data['notes'];
    if (notes is! Map) return const {};
    final out = <String, HorseNoteRecord>{};
    notes.forEach((key, value) {
      if (key is! String || value is! Map) return;
      final historyRaw = value['history'];
      final history = <HorseNoteEntry>[];
      if (historyRaw is List) {
        for (final item in historyRaw) {
          final entry = HorseNoteEntry.fromJson(item);
          if (entry != null) history.add(entry);
        }
      }
      out[key] = HorseNoteRecord(
        text: _textOf(value['text']),
        history: history,
      );
    });
    return out;
  } catch (_) {
    return const {};
  }
}

String _textOf(Object? value) {
  if (value == null) return '';
  return value.toString();
}

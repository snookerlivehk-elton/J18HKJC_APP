import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_table/scroll_columns.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('column widths are reused until the race, columns, or scale change', () {
    final cache = ScrollWidthCache();
    final race = _race(5, '10');
    final again = cache.resolve(
      race: race,
      textScaler: TextScaler.noScaling,
      columns: kPhase2ScrollColumns,
    );
    final first = cache.resolve(
      race: race,
      textScaler: TextScaler.noScaling,
      columns: kPhase2ScrollColumns,
    );
    expect(identical(first, again), isTrue);

    final scaled = cache.resolve(
      race: race,
      textScaler: const TextScaler.linear(1.2),
      columns: kPhase2ScrollColumns,
    );
    expect(identical(first, scaled), isFalse);

    final otherRace = cache.resolve(
      race: _race(6, '120'),
      textScaler: const TextScaler.linear(1.2),
      columns: kPhase2ScrollColumns,
    );
    expect(identical(scaled, otherRace), isFalse);

    final subset = cache.resolve(
      race: race,
      textScaler: TextScaler.noScaling,
      columns: [kPhase2ScrollColumns.first],
    );
    expect(subset, hasLength(1));
    expect(identical(subset, first), isFalse);
  });
}

Race _race(int num, String form) {
  return Race(
    num: num,
    name: '測試',
    time: '12:00',
    meta: '',
    runners: [
      Runner(
        no: 1,
        name: '馬',
        draw: 1,
        jockey: '騎',
        trainer: '練',
        win: 3.5,
        place: 1.5,
        scratched: false,
        silk: null,
        form6: form,
        recent: null,
        age: 4,
        rating: 60,
        rtgDelta: null,
        hw: 120,
        bodyWt: null,
        gear: null,
        career: null,
        rail: null,
        dam: null,
        sire: null,
        damsire: null,
        owner: null,
        prize: null,
      ),
    ],
  );
}

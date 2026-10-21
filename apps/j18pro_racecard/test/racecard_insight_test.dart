import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';
import 'package:j18pro_racecard/features/racecard_insight/index_picks.dart';
import 'package:j18pro_racecard/features/racecard_insight/payout_detail.dart';
import 'package:j18pro_racecard/features/racecard_insight/race_status.dart';
import 'package:j18pro_racecard/features/racecard_insight/time_scrub.dart';
import 'package:j18pro_racecard/features/racecard_table/row_chrome.dart';
import 'package:shared_preferences/shared_preferences.dart';

Runner _horse({
  required int no,
  double? win,
  int? rating,
  int? hw,
  String? rtgDelta,
  bool scratched = false,
  int? finish,
}) {
  return Runner(
    no: no,
    name: '馬$no',
    draw: 1,
    jockey: '騎',
    trainer: '練',
    win: win,
    place: win == null ? null : 2,
    scratched: scratched,
    silk: null,
    form6: null,
    recent: null,
    age: null,
    rating: rating,
    rtgDelta: rtgDelta,
    hw: hw,
    bodyWt: null,
    gear: null,
    career: null,
    rail: null,
    dam: null,
    sire: null,
    damsire: null,
    owner: null,
    prize: null,
    finish: finish,
  );
}

Race _race({
  int num = 5,
  String time = '20:40',
  String meta = '20:40 香港鄉村俱樂部挑戰盃（讓賽）　谷草 "C" 1650米 第四班 好地',
  String name = '香港鄉村俱樂部挑戰盃（讓賽）',
  List<Runner>? runners,
  bool paid = false,
  List<RaceDividend>? dividends,
}) {
  return Race(
    num: num,
    name: name,
    time: time,
    meta: meta,
    runners:
        runners ??
        [
          _horse(no: 1, win: 12, rating: 59, hw: 135, rtgDelta: '0'),
          _horse(no: 2, win: 5, rating: 40, hw: 120, rtgDelta: '-1'),
        ],
    paid: paid,
    dividends: dividends,
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('race status follows the Web minute thresholds', () {
    final race = _race();
    expect(
      resolveRaceStatus(race: race, dateIso: '2026-09-23', minutesUntil: 31),
      RaceStatusKind.wait,
    );
    expect(
      resolveRaceStatus(race: race, dateIso: '2026-09-23', minutesUntil: 30),
      RaceStatusKind.parade,
    );
    expect(
      resolveRaceStatus(race: race, dateIso: '2026-09-23', minutesUntil: 15),
      RaceStatusKind.gate,
    );
    expect(
      resolveRaceStatus(race: race, dateIso: '2026-09-23', minutesUntil: 5),
      RaceStatusKind.running,
    );
    expect(
      resolveRaceStatus(race: race, dateIso: '2026-09-23', minutesUntil: 0),
      RaceStatusKind.running,
    );
    expect(
      resolveRaceStatus(race: race, dateIso: '2026-09-23', minutesUntil: -1),
      RaceStatusKind.running,
    );
    expect(
      resolveRaceStatus(race: race, dateIso: 'bad', minutesUntil: null),
      RaceStatusKind.wait,
    );
    expect(
      resolveRaceStatus(
        race: _race(paid: true),
        dateIso: '2026-09-23',
        minutesUntil: 90,
      ),
      RaceStatusKind.paid,
    );
    expect(raceStatusLabel(RaceStatusKind.gate), '入閘中');
    expect(
      raceStatusColors(RaceStatusKind.running, Brightness.light).text,
      const Color(0xFFC0392B),
    );
    expect(
      raceStatusColors(RaceStatusKind.running, Brightness.light).dot,
      const Color(0xFFE74C3C),
    );
    expect(
      raceStatusColors(RaceStatusKind.wait, Brightness.dark).text,
      const Color(0xFF6EB3E0),
    );
    expect(
      raceStatusColors(RaceStatusKind.wait, Brightness.dark).dot,
      const Color(0xFF6EB3E0),
    );
  });

  test('meta line matches formatRaceInfoLine', () {
    expect(
      formatRaceInfoLine(
        dateIso: '2026-09-23',
        race: _race(),
        courseLabel: '跑馬地',
        weekdayLabel: '周三',
      ),
      '23/9 周三 20:40 谷草 四班 1650  "C" 好地 香港鄉村俱樂部挑戰盃（讓賽）',
    );
  });

  test('win water uses the demo formula and the race 1 horse 9 anchor', () {
    expect(jsRound(1.5), 2);
    expect(jsRound(2.5), 3);
    expect(jsRound(-1.5), -1);
    final favorite = _horse(no: 1, win: 12);
    expect(winWaterOf(favorite, 5), 82);
    final anchor = _horse(no: 9, win: 99, hw: 123);
    expect(winWaterOf(anchor, 1), 86);
    expect(winFlowOf(anchor, 1), 10);
    expect(winWaterOf(_horse(no: 7, win: 37, scratched: true), 6), isNull);

    final race = _race(
      runners: [
        _horse(no: 1, win: 12),
        _horse(no: 2, win: 5),
        _horse(no: 3, win: null, scratched: true),
      ],
    );
    expect(indexPicksForStrategy(race, 'composite'), [1, 2]);
    expect(indexPicksForStrategy(race, 'water'), [2, 1]);
  });

  test('scrub rotates picks and snaps to the nearest mark', () {
    final base = [1, 2, 3, 4, 5, 6];
    final points = buildScrubPicks(base);
    expect(points, hasLength(10));
    expect(points.last, [6, 1, 2, 3, 4, 5]);
    expect(activeScrubIndex(-1, 10), 9);
    expect(scrubLabFor(-1), "0'");
    expect(nearestScrubIndex(116, 8), 0);
    expect(nearestScrubIndex(116, 30), 1);
    expect(nearestScrubIndex(116, 116), 9);

    final race = _race(
      runners: [
        for (var no = 1; no <= 6; no++) _horse(no: no, win: no.toDouble()),
      ],
    );
    expect(
      activeIndexPicks(race: race, strategyId: 'composite', scrubPointIdx: -1),
      isNot(indexPicksForStrategy(race, 'composite')),
    );
  });

  test('payout order, demo pools, and dividend rows', () {
    final race = _race(
      paid: true,
      runners: [
        _horse(no: 1, win: 5),
        _horse(no: 2, win: 2),
        _horse(no: 3, win: 9),
        _horse(no: 4, win: 3),
        _horse(no: 7, scratched: true),
      ],
    );
    expect(payoutFinishNosForRace(race), [2, 4, 1, 3]);
    expect(raceHasPayout(race), isTrue);
    expect(raceHasPayout(_race()), isFalse);

    final sections = buildPayoutDetailSections(race);
    expect(sections.map((section) => section.pool), [
      '獨贏',
      '位置',
      '連贏',
      '位置Q',
      '二重彩',
      '三重彩',
      '單T',
      '四連環',
      '四重彩',
    ]);
    expect(sections.first.rows.single.combo, '2');
    expect(fmtPayoutAmt(sections.first.rows.single.pay), '118.50');
    expect(sections[2].rows.single.combo, '2,4');
    expect(sections.last.rows.single.combo, '2,4,1,3');
    expect(fmtPayoutAmt(15907), '15,907.00');
    expect(fmtPayoutAmt(null), '—');

    final ranked = _race(
      runners: [
        _horse(no: 1, win: 2, finish: 2),
        _horse(no: 2, win: 9, finish: 1),
      ],
    );
    expect(payoutFinishNosForRace(ranked), [2, 1]);

    final published = _race(
      dividends: const [
        RaceDividend(pool: '獨贏', combo: '8', pay: 12),
        RaceDividend(pool: '位置', combo: '8', pay: 3),
        RaceDividend(pool: '獨贏', combo: '1', pay: 4),
      ],
    );
    final grouped = buildPayoutDetailSections(published);
    expect(grouped.map((section) => section.pool), ['獨贏', '位置']);
    expect(grouped.first.rows.map((row) => row.combo), ['8', '1']);
    expect(raceHasPayout(published), isTrue);

    final parsed = Race.fromJson({
      'num': 5,
      'name': '測',
      'time': '20:40',
      'meta': '20:40 測',
      'runners': [
        {'no': 1, 'name': '馬', 'draw': 1, 'jockey': '騎', 'trainer': '練'},
      ],
    });
    expect(parsed.paid, isFalse);
    expect(parsed.dividends, isNull);
    expect(raceHasPayout(parsed), isFalse);
  });

  testWidgets('status, meta, and index capsule sit above the table', (
    tester,
  ) async {
    await _pumpApp(tester);

    expect(find.text('本領非凡'), findsOneWidget);
    final label = tester
        .widget<Text>(find.byKey(const Key('race-status-lab')))
        .data;
    expect({'待開賽', '出跑道', '入閘中', '開跑中', '已派彩'}, contains(label));
    final meta = tester.widget<Text>(find.byKey(const Key('race-meta')));
    expect(meta.maxLines, 1);
    expect(meta.overflow, TextOverflow.ellipsis);
    expect(meta.data, contains('1650'));
    expect(meta.data, contains('四班'));
    expect(
      tester.widget<Text>(find.byKey(const Key('scrub-active'))).data,
      "0'",
    );
    expect(find.byKey(const Key('index-cap-0')), findsOneWidget);
    expect(find.byKey(const Key('index-cap-5')), findsOneWidget);
    expect(find.byKey(const Key('payout-cap-0')), findsNothing);
    expect(find.byKey(const Key('capsule-drop')), findsNothing);
    expect(find.byType(RowBand), findsNWidgets(11));
  });

  testWidgets('scrub drag, capsule exclusion, and strategy reset', (
    tester,
  ) async {
    await _pumpApp(tester);

    final scrub = tester.getRect(find.byKey(const Key('time-scrub')));
    final gesture = await tester.startGesture(
      scrub.centerRight - const Offset(2, 0),
    );
    await gesture.moveBy(Offset(-scrub.width * 0.75, 0));
    await tester.pump();
    await gesture.up();
    await tester.pump();

    final moved = tester
        .widget<Text>(find.byKey(const Key('scrub-active')))
        .data;
    expect(moved, isNot("0'"));

    await tester.tap(find.byKey(const Key('race-pill-1')));
    await tester.pump();
    expect(
      tester.widget<Text>(find.byKey(const Key('scrub-active'))).data,
      moved,
    );
    expect(find.text('堅多福'), findsOneWidget);

    await tester.tap(find.byKey(const Key('race-pill-5')));
    await tester.pump();
    expect(
      tester.widget<Text>(find.byKey(const Key('scrub-active'))).data,
      moved,
    );

    await tester.tap(find.byKey(const Key('capsule-chev-index')));
    await tester.pump();
    expect(find.byKey(const Key('capsule-drop')), findsOneWidget);
    expect(find.text('能量蓄勢'), findsOneWidget);

    await tester.tap(find.byKey(const Key('strategy-expert')));
    await tester.pump();
    expect(
      tester.widget<Text>(find.byKey(const Key('scrub-active'))).data,
      "0'",
    );
    expect(find.byKey(const Key('capsule-drop')), findsOneWidget);
    expect(find.byKey(const Key('index-cap-0')), findsOneWidget);

    await tester.tap(find.byKey(const Key('capsule-payout')));
    await tester.pump();
    expect(find.byKey(const Key('index-cap-0')), findsNothing);
    expect(find.byKey(const Key('payout-cap-0')), findsOneWidget);
    expect(find.byKey(const Key('capsule-drop')), findsNothing);
    expect(find.text('未派彩'), findsOneWidget);

    await tester.tap(find.byKey(const Key('capsule-payout-status')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('payout-detail-sheet')), findsNothing);
    expect(find.text('118.50'), findsNothing);

    await tester.tap(find.byKey(const Key('capsule-index')));
    await tester.pump();
    expect(find.byKey(const Key('payout-cap-0')), findsNothing);
    expect(find.byKey(const Key('index-cap-0')), findsOneWidget);
  });

  testWidgets('number circles stay readable and hits keep W Q P 4 colors', (
    tester,
  ) async {
    await _pumpApp(tester);

    final plainKey = _plainIndexKey(tester);
    _expectCircle(
      tester,
      plainKey,
      background: const Color(0xFFFFFFFF),
      foreground: const Color(0xFF1E2A38),
      border: const Color(0xFFE88B2A),
    );

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    _expectCircle(
      tester,
      plainKey,
      background: const Color(0xFF2A313C),
      foreground: const Color(0xFFE8EEF6),
      border: const Color(0xFFE88B2A),
    );

    await tester.tap(find.byKey(const Key('capsule-payout')));
    await tester.pump();
    _expectCircle(
      tester,
      const Key('payout-cap-0'),
      background: const Color(0xFFCC453F),
      foreground: const Color(0xFFFFFFFF),
      border: const Color(0xFFCC453F),
    );
    _expectCircle(
      tester,
      const Key('payout-cap-1'),
      background: const Color(0xFF2F70CA),
      foreground: const Color(0xFFFFFFFF),
      border: const Color(0xFF2F70CA),
    );
    _expectCircle(
      tester,
      const Key('payout-cap-2'),
      background: const Color(0xFF3F8F4A),
      foreground: const Color(0xFFFFFFFF),
      border: const Color(0xFF3F8F4A),
    );
    _expectCircle(
      tester,
      const Key('payout-cap-3'),
      background: const Color(0xFF8A6BB8),
      foreground: const Color(0xFFFFFFFF),
      border: const Color(0xFF8A6BB8),
    );

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    _expectCircle(
      tester,
      const Key('payout-cap-0'),
      background: const Color(0xFFCC453F),
      foreground: const Color(0xFFFFFFFF),
      border: const Color(0xFFCC453F),
    );
    await tester.tap(find.byKey(const Key('capsule-index')));
    await tester.pump();
    _expectCircle(
      tester,
      plainKey,
      background: const Color(0xFFFFFFFF),
      foreground: const Color(0xFF1E2A38),
      border: const Color(0xFFE88B2A),
    );
  });

  testWidgets('race 6 payout skips the scratched horse', (tester) async {
    await _pumpApp(tester);
    await tester.tap(find.byKey(const Key('race-pill-6')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('capsule-payout')));
    await tester.pump();

    expect(find.byKey(const Key('payout-cap-8')), findsOneWidget);
    expect(find.byKey(const Key('payout-cap-9')), findsNothing);
    for (var i = 0; i < 9; i++) {
      final text = tester.widget<Text>(
        find.descendant(
          of: find.byKey(Key('payout-cap-$i')),
          matching: find.byType(Text),
        ),
      );
      expect(text.data, isNot('7'));
    }
    expect(find.text('雙劍合璧'), findsOneWidget);
  });

  testWidgets('a settled race opens the payout sheet', (tester) async {
    tester.view.physicalSize = const Size(430, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(preferences),
          raceRepositoryProvider.overrideWithValue(_PaidRace5Repository()),
        ],
        child: const J18App(),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      tester.widget<Text>(find.byKey(const Key('race-status-lab'))).data,
      '已派彩',
    );
    await tester.tap(find.byKey(const Key('capsule-payout')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('capsule-payout-status')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('payout-detail-sheet')), findsOneWidget);
    expect(find.text('彩池'), findsOneWidget);
    expect(find.text('勝出組合'), findsOneWidget);
    expect(find.text('118.50'), findsOneWidget);
    expect(find.text('15,907.00'), findsOneWidget);
    expect(find.text('獨贏'), findsWidgets);
    expect(find.text('四重彩'), findsOneWidget);
  });
}

Key _plainIndexKey(WidgetTester tester) {
  for (var i = 0; i < 6; i++) {
    final key = Key('index-cap-$i');
    final container = tester.widget<Container>(
      find.descendant(of: find.byKey(key), matching: find.byType(Container)),
    );
    final color = (container.decoration! as BoxDecoration).color;
    if (color == const Color(0xFFFFFFFF) || color == const Color(0xFF2A313C)) {
      final text = tester.widget<Text>(
        find.descendant(of: find.byKey(key), matching: find.byType(Text)),
      );
      if (text.data != '—') return key;
    }
  }
  fail('index capsule has no unsettled number');
}

void _expectCircle(
  WidgetTester tester,
  Key key, {
  required Color background,
  required Color foreground,
  required Color border,
}) {
  final container = tester.widget<Container>(
    find.descendant(of: find.byKey(key), matching: find.byType(Container)),
  );
  final decoration = container.decoration! as BoxDecoration;
  expect(decoration.color, background);
  expect((decoration.border! as Border).top.color, border);
  expect((decoration.border! as Border).top.width, 1.5);
  final text = tester.widget<Text>(
    find.descendant(of: find.byKey(key), matching: find.byType(Text)),
  );
  expect(text.style?.color, foreground);
}

Future<void> _pumpApp(WidgetTester tester) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [sharedPreferencesProvider.overrideWithValue(preferences)],
      child: const J18App(),
    ),
  );
  await tester.pumpAndSettle();
}

class _PaidRace5Repository implements RaceRepository {
  final DemoMeetingRepository _inner = DemoMeetingRepository();

  @override
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) async {
    final meeting = await _inner.load(date, scope: scope);
    final race = meeting.raceByNum(5);
    if (race == null) return meeting;
    return meeting.replaceRace(race.copyWith(paid: true));
  }
}

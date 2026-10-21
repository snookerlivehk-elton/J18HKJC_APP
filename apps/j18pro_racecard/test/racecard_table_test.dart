import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/racecard_table/racecard_table.dart';
import 'package:j18pro_racecard/features/racecard_table/row_chrome.dart';
import 'package:j18pro_racecard/features/racecard_table/scroll_columns.dart';
import 'package:j18pro_racecard/features/racecard_table/swallowtail_flag.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<Meeting> _meeting() {
  return DemoMeetingRepository().load(DemoMeetingRepository.snapshotDate);
}

Future<void> _pumpTable(
  WidgetTester tester, {
  required Race race,
  Map<String, int> marks = const {},
  ValueChanged<int>? onCycleMark,
  Size size = const Size(240, 360),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: J18Theme.light(),
      home: Scaffold(
        body: RacecardTable(
          race: race,
          marks: marks,
          onCycleMark: onCycleMark ?? (_) {},
        ),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('cycleMark is per race and returns to none on the third tap', (
    tester,
  ) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final initial = await container.read(racecardControllerProvider.future);
    expect(initial.currentRaceNum, 5);
    expect(initial.markFor(1), 0);

    final notifier = container.read(racecardControllerProvider.notifier);
    notifier.cycleMark(1);
    expect(
      container.read(racecardControllerProvider).requireValue.markFor(1),
      1,
    );
    notifier.selectRace(1);
    expect(
      container.read(racecardControllerProvider).requireValue.currentRaceNum,
      1,
    );
    expect(
      container.read(racecardControllerProvider).requireValue.markFor(1),
      0,
    );
    notifier.selectRace(5);
    expect(
      container.read(racecardControllerProvider).requireValue.markFor(1),
      1,
    );

    notifier.cycleMark(1);
    expect(
      container.read(racecardControllerProvider).requireValue.markFor(1),
      2,
    );
    notifier.cycleMark(1);
    expect(
      container.read(racecardControllerProvider).requireValue.markFor(1),
      0,
    );
    notifier.cycleMark(99);
    expect(
      container.read(racecardControllerProvider).requireValue.marks,
      isEmpty,
    );
  });

  testWidgets('right columns use the measured width of this race', (
    tester,
  ) async {
    final meeting = await _meeting();
    final race = meeting.raceByNum(5)!;
    await _pumpTable(tester, race: race, size: const Size(430, 640));

    final widths = fitScrollWidths(
      race: race,
      textScaler: TextScaler.noScaling,
    );
    final header = tester.renderObject<RenderBox>(
      find.byKey(const Key('scroll-header')),
    );
    expect(
      header.size.width,
      widths.fold<double>(0, (sum, width) => sum + width),
    );
    expect(find.text('檔位'), findsOneWidget);
    expect(find.text('獨贏'), findsOneWidget);
    expect(find.text('位置'), findsOneWidget);
    expect(find.text('近績'), findsOneWidget);
    expect(find.text('12'), findsWidgets);
    expect(find.text('4.2'), findsWidgets);
  });

  testWidgets(
    'horizontal drag moves header and body together and leaves the lock',
    (tester) async {
      final meeting = await _meeting();
      final race = meeting.raceByNum(5)!;
      await _pumpTable(tester, race: race);

      final header = find.byKey(const Key('scroll-header'));
      final body = find.byKey(const Key('scroll-row-1'));
      final lock = find.byKey(const Key('lock-1'));
      final headerStart = tester.getTopLeft(header);
      final bodyStart = tester.getTopLeft(body);
      final lockStart = tester.getTopLeft(lock);

      await _drag(tester, const Offset(-140, 0));

      final headerDelta = tester.getTopLeft(header) - headerStart;
      final bodyDelta = tester.getTopLeft(body) - bodyStart;
      expect(headerDelta.dx, lessThan(-10));
      expect(bodyDelta.dx, closeTo(headerDelta.dx, 0.5));
      expect(headerDelta.dy, closeTo(0, 0.5));
      expect(bodyDelta.dy, closeTo(0, 0.5));
      expect(tester.getTopLeft(lock).dx, closeTo(lockStart.dx, 0.5));
    },
  );

  testWidgets(
    'vertical drag keeps the lock and the right columns on the same row',
    (tester) async {
      final meeting = await _meeting();
      final race = meeting.raceByNum(5)!;
      await _pumpTable(tester, race: race);

      final body = find.byKey(const Key('scroll-row-1'));
      final lock = find.byKey(const Key('lock-1'));
      final bodyStart = tester.getTopLeft(body);
      final lockStart = tester.getTopLeft(lock);

      await _drag(tester, const Offset(0, -40));

      final bodyDelta = tester.getTopLeft(body) - bodyStart;
      final lockDelta = tester.getTopLeft(lock) - lockStart;
      expect(bodyDelta.dy, lessThan(-10));
      expect(lockDelta.dy, closeTo(bodyDelta.dy, 0.5));
      expect(lockDelta.dx, closeTo(0, 0.5));
      expect(bodyDelta.dx, closeTo(0, 0.5));
    },
  );

  testWidgets('switching race resets the horizontal offset', (tester) async {
    final meeting = await _meeting();
    final race5 = meeting.raceByNum(5)!;
    final race1 = meeting.raceByNum(1)!;
    await _pumpTable(tester, race: race5);

    final header = find.byKey(const Key('scroll-header'));
    final start = tester.getTopLeft(header).dx;
    await _drag(tester, const Offset(-140, 0));
    expect(tester.getTopLeft(header).dx, lessThan(start - 10));

    await _pumpTable(tester, race: race1);
    expect(tester.getTopLeft(header).dx, closeTo(start, 0.5));
    expect(find.text('堅多福'), findsOneWidget);
    expect(find.text('本領非凡'), findsNothing);
  });

  testWidgets('zebra stripes alternate and a marked row follows the flag', (
    tester,
  ) async {
    final meeting = await _meeting();
    final race = meeting.raceByNum(5)!;
    await _pumpTable(tester, race: race, marks: const {'5:2': 1});

    final first = tester.widget<RowBand>(find.byKey(const Key('row-5-1')));
    final second = tester.widget<RowBand>(find.byKey(const Key('row-5-2')));
    final fourth = tester.widget<RowBand>(find.byKey(const Key('row-5-4')));
    expect(first.color, RowChrome.lightRow);
    expect(fourth.color, RowChrome.lightAlt);
    expect(second.color, RowChrome.lightMark1Alt);
    expect(
      tester.widget<SwallowtailFlag>(find.byKey(const Key('flag-5-2'))).color,
      RowChrome.lightMark1Flag,
    );
  });

  testWidgets('swallowtail cycles and stays visible in light and dark', (
    tester,
  ) async {
    await _pumpApp(tester);

    expect(find.byType(RowBand), findsNWidgets(11));
    expect(find.text('載入賽事'), findsNothing);

    SwallowtailFlag flag() {
      return tester.widget<SwallowtailFlag>(find.byKey(const Key('flag-5-1')));
    }

    RowBand row() {
      return tester.widget<RowBand>(find.byKey(const Key('row-5-1')));
    }

    expect(flag().color, RowChrome.lightIdleFlag);
    expect(row().color, RowChrome.lightRow);
    expect(row().accent, isNull);

    await tester.tap(find.byKey(const Key('flag-5-1')));
    await tester.pump();
    expect(flag().color, RowChrome.lightMark1Flag);
    expect(flag().color, isNot(RowChrome.lightIdleFlag));
    expect(row().color, RowChrome.lightMark1);

    await tester.tap(find.byKey(const Key('flag-5-1')));
    await tester.pump();
    expect(flag().color, RowChrome.lightMark2Flag);
    expect(row().color, RowChrome.lightMark2);

    await tester.tap(find.byKey(const Key('flag-5-1')));
    await tester.pump();
    expect(flag().color, RowChrome.lightIdleFlag);
    expect(row().color, RowChrome.lightRow);

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(flag().color, RowChrome.darkIdleFlag);

    await tester.tap(find.byKey(const Key('flag-5-1')));
    await tester.pump();
    expect(flag().color, RowChrome.darkMark1Flag);
    expect(flag().color, isNot(RowChrome.darkIdleFlag));
    expect(row().color, RowChrome.darkMark1);
    expect(row().accent, RowChrome.darkMark1Flag);

    await tester.tap(find.byKey(const Key('flag-5-1')));
    await tester.pump();
    expect(flag().color, RowChrome.darkMark2Flag);
    expect(flag().color, isNot(RowChrome.darkIdleFlag));
    expect(row().color, RowChrome.darkMark2);
    expect(row().accent, RowChrome.darkMark2Flag);

    await tester.tap(find.byKey(const Key('race-pill-1')));
    await tester.pump();
    expect(find.text('載入賽事'), findsNothing);
    expect(find.text('堅多福'), findsOneWidget);
    expect(find.byType(RowBand), findsNWidgets(12));

    await tester.tap(find.byKey(const Key('race-pill-5')));
    await tester.pump();
    expect(flag().color, RowChrome.darkMark2Flag);
    expect(row().color, RowChrome.darkMark2);
  });

  testWidgets('menu stub opens without leaving the racecard', (tester) async {
    await _pumpApp(tester);
    await tester.tap(find.byKey(const Key('menu-stub')));
    await tester.pumpAndSettle();
    expect(find.text('選單'), findsOneWidget);
    expect(find.text('個人心水和戰績'), findsOneWidget);
    expect(find.text('名家'), findsOneWidget);
    expect(find.text('馬匹數據排序'), findsOneWidget);
    expect(find.text('查看賽期和歷史數據'), findsOneWidget);
    expect(find.text('稍後提供'), findsNothing);
    expect(find.text('排位'), findsOneWidget);
  });
}

Future<void> _drag(WidgetTester tester, Offset delta) async {
  final gesture = await tester.startGesture(
    tester.getCenter(find.byKey(const Key('runner-list'))),
  );
  await gesture.moveBy(delta);
  await gesture.up();
  await tester.pump();
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

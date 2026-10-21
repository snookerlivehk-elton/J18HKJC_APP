import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/data/jjjc_meeting_map.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';
import 'package:j18pro_racecard/widgets/silk_mark.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _GateRepository implements RaceRepository {
  final ready = Completer<void>();
  var offline = false;

  @override
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) async {
    if (!ready.isCompleted) await ready.future;
    if (offline || date == '2026-10-01') {
      throw RaceLoadException('未能連線，請檢查網絡');
    }
    return DemoMeetingRepository().load(date, scope: scope);
  }
}

class _EmptyRepository implements RaceRepository {
  @override
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) async {
    return mapJjjcMeeting(
      date: date,
      venue: 'ST',
      racecard: const {'schema': 'jjjc.racecard.v1', 'races': []},
      results: const {'schema': 'jjjc.results.v1', 'races': []},
    );
  }
}

class _BoomImage extends ImageProvider<_BoomImage> {
  const _BoomImage();

  @override
  Future<_BoomImage> obtainKey(ImageConfiguration configuration) {
    return Future<_BoomImage>.value(this);
  }

  @override
  ImageStreamCompleter loadImage(_BoomImage key, ImageDecoderCallback decode) {
    return OneFrameImageStreamCompleter(
      Future<ImageInfo>.error(Exception('silk')),
    );
  }
}

Future<void> _pump(
  WidgetTester tester, {
  required RaceRepository repository,
}) async {
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
        raceRepositoryProvider.overrideWithValue(repository),
      ],
      child: const J18App(),
    ),
  );
}

void main() {
  testWidgets('loading, offline, and retry stay on screen', (tester) async {
    final repository = _GateRepository();
    await _pump(tester, repository: repository);
    expect(find.byKey(const Key('racecard-loading')), findsOneWidget);
    expect(find.text('載入賽事'), findsOneWidget);

    repository.ready.complete();
    await tester.pumpAndSettle();
    expect(find.text('本領非凡'), findsOneWidget);

    await tester.tap(find.byKey(const Key('menu-stub')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('menu-race-date')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cal-next')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cal-day-2026-10-01')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('cal-close')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('racecard-error')), findsOneWidget);
    expect(find.text('未能連線，請檢查網絡'), findsOneWidget);
    expect(find.text('重試'), findsOneWidget);

    repository.offline = false;
    await tester.tap(find.byKey(const Key('racecard-retry')));
    await tester.pumpAndSettle();
    expect(find.text('本領非凡'), findsOneWidget);
    expect(find.byKey(const Key('racecard-error')), findsNothing);
  });

  testWidgets('an empty api meeting shows the empty race day', (tester) async {
    await _pump(tester, repository: _EmptyRepository());
    await tester.pumpAndSettle();
    expect(find.textContaining('該日暫無賽事'), findsWidgets);
    expect(find.byKey(const Key('empty-runners')), findsOneWidget);
    expect(find.text('暫無馬匹'), findsOneWidget);
    expect(find.text('沙田 · 2026-09-23'), findsOneWidget);
  });

  testWidgets('a failed silk image keeps the colour block', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: J18Theme.light(),
        home: const Scaffold(
          body: SilkMark(
            horseNo: 1,
            url: 'https://racing.hkjc.com/racing/content/Images/RaceColor/K306.gif',
            image: _BoomImage(),
            tokens: J18Tokens.light,
          ),
        ),
      ),
    );
    await tester.pump();
    expect(find.byKey(const Key('silk-fallback')), findsOneWidget);
  });
}

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/synth_review/horse_notes_controller.dart';
import 'package:j18pro_racecard/features/synth_review/synth_review.dart';
import 'package:shared_preferences/shared_preferences.dart';

Runner _runner(
  int no,
  String name, {
  bool scratched = false,
  String jockey = '',
  int? finish,
}) {
  return Runner(
    no: no,
    name: name,
    draw: 1,
    jockey: jockey,
    trainer: '',
    win: null,
    place: null,
    scratched: scratched,
    silk: null,
    form6: null,
    recent: null,
    age: null,
    rating: null,
    rtgDelta: null,
    hw: null,
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('snapshot review text matches the web demo', () async {
    final meeting = await DemoMeetingRepository().load(
      DemoMeetingRepository.snapshotDate,
    );
    final race5 = meeting.raceByNum(5)!;
    final first = race5.runners.firstWhere((runner) => runner.no == 1);
    final review = synthReviewText(
      runner: first,
      raceNum: 5,
      meetingDate: meeting.date,
    );
    expect(review.startsWith('本領非凡'), isTrue);
    expect(review, contains('模型勝率達22.56%'));

    final race1 = meeting.raceByNum(1)!;
    final empty = race1.runners.firstWhere((runner) => runner.no == 2);
    expect(empty.name, '一風雲');
    expect(
      synthReviewText(runner: empty, raceNum: 1, meetingDate: meeting.date),
      isEmpty,
    );

    final scratched = meeting
        .raceByNum(6)!
        .runners
        .firstWhere((runner) => runner.no == 7);
    expect(scratched.scratched, isTrue);
    expect(
      synthReviewText(runner: scratched, raceNum: 6, meetingDate: meeting.date),
      isEmpty,
    );
  });

  test('note dates pad both iso and slash forms', () {
    expect(formatHorseNoteDate('2026-09-23'), '23/09/2026');
    expect(formatHorseNoteDate('2026-9-3'), '03/09/2026');
    expect(formatHorseNoteDate('3/9/2026'), '03/09/2026');
    expect(formatHorseNoteDate(''), isEmpty);
    expect(formatHorseNoteDate(null), isEmpty);
    expect(formatHorseNoteDate('試閘'), '試閘');
  });

  test('demo history is seeded only for horses on the snapshot', () {
    final note = resolveHorseNote(
      saved: const {},
      date: synthReviewDemoDate,
      raceNum: 5,
      horseNo: 5,
      scratched: false,
    );
    expect(note.history, hasLength(1));
    expect(note.openingDraft, kHorseNoteDemo);
    expect(note.history.single.text, kHorseNoteDemo);
    expect(horseNoteMeta(note.history.single), '23/09/2026·第1名·周俊樂·1650米·跑馬地');

    final three = demoHorseNote(
      date: synthReviewDemoDate,
      raceNum: 1,
      horseNo: 3,
    );
    expect(three!.history, hasLength(3));
    expect(
      demoHorseNote(date: synthReviewDemoDate, raceNum: 2, horseNo: 4),
      isNull,
    );
    expect(
      resolveHorseNote(
        saved: const {},
        date: '2026-10-01',
        raceNum: 5,
        horseNo: 5,
        scratched: false,
      ).history,
      isEmpty,
    );
  });

  test('save prepends, and the same text on the same date replaces', () {
    final current = HorseNoteRecord(
      text: kHorseNoteDemo,
      history: [
        const HorseNoteEntry(
          id: 'old',
          date: '2026-09-23',
          text: '後期追前',
          finish: '1',
          jockey: '周俊樂',
          dist: '1650米',
          course: '跑馬地',
        ),
        const HorseNoteEntry(
          id: 'keep',
          date: '2026-08-17',
          text: '另一條',
          finish: '—',
          jockey: '潘頓',
          dist: '1200米',
          course: '沙田',
        ),
      ],
    );
    final runner = _runner(1, '本領非凡', jockey: '何澤堯', finish: 4);
    final saved = applyHorseNoteSave(
      current: current,
      draft: '  後期追前  ',
      meetingDate: '2026-09-23',
      runner: runner,
      raceMeta: '谷草 "C" 1650米',
      courseLabel: '跑馬地',
      id: 'new',
    );
    expect(saved.text, '後期追前');
    expect(saved.history, hasLength(2));
    expect(saved.history.first.id, 'new');
    expect(saved.history.first.finish, '4');
    expect(saved.history.first.jockey, '何澤堯');
    expect(saved.history.first.dist, '1650米');
    expect(saved.history.first.course, '跑馬地');
    expect(saved.history.last.id, 'keep');
    expect(horseNoteMeta(saved.history.last), '17/08/2026·—·潘頓·1200米·沙田');

    final cleared = applyHorseNoteSave(
      current: saved,
      draft: '   ',
      meetingDate: '2026-09-23',
      runner: runner,
      raceMeta: '',
      courseLabel: '跑馬地',
      id: 'ignored',
    );
    expect(cleared.text, isEmpty);
    expect(cleared.history, hasLength(2));
    expect(cleared.openingDraft, '後期追前');
  });

  test('a stored record replaces the demo seed, including an empty note', () {
    const key = '2026-09-23:5:5';
    final saved = resolveHorseNote(
      saved: {
        key: const HorseNoteRecord(
          text: '自訂',
          history: [
            HorseNoteEntry(
              id: 's',
              date: '2026-09-23',
              text: '自訂',
              finish: '',
              jockey: '',
              dist: '',
              course: '',
            ),
          ],
        ),
      },
      date: synthReviewDemoDate,
      raceNum: 5,
      horseNo: 5,
      scratched: false,
    );
    expect(saved.openingDraft, '自訂');
    expect(saved.history, hasLength(1));

    final cleared = resolveHorseNote(
      saved: {key: HorseNoteRecord.empty},
      date: synthReviewDemoDate,
      raceNum: 5,
      horseNo: 5,
      scratched: false,
    );
    expect(cleared.openingDraft, isEmpty);
    expect(cleared.history, isEmpty);
  });

  test('prefs round-trip keeps text and history', () {
    const original = {
      '2026-09-23:1:3': HorseNoteRecord(
        text: '自訂',
        history: [
          HorseNoteEntry(
            id: 'n1',
            date: '2026-09-23',
            text: '自訂',
            finish: '2',
            jockey: '霍宏聲',
            dist: '1650米',
            course: '跑馬地',
          ),
        ],
      ),
    };
    final decoded = decodeHorseNotes(encodeHorseNotes(original));
    expect(decoded.keys, ['2026-09-23:1:3']);
    expect(decoded['2026-09-23:1:3']!.text, '自訂');
    expect(decoded['2026-09-23:1:3']!.history.single.jockey, '霍宏聲');
    expect(decodeHorseNotes(''), isEmpty);
    expect(decodeHorseNotes('{'), isEmpty);
    expect(decodeHorseNotes('{"v":2,"notes":{}}'), isEmpty);
  });

  test(
    'the controller writes j18-horse-notes-v1 and ignores scratched',
    () async {
      SharedPreferences.setMockInitialValues({});
      final preferences = await SharedPreferences.getInstance();
      final container = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(preferences)],
      );
      addTearDown(container.dispose);

      final runner = _runner(1, '本領非凡', jockey: '何澤堯');
      final saved = await container
          .read(horseNotesProvider.notifier)
          .save(
            date: '2026-09-23',
            raceNum: 5,
            runner: runner,
            raceMeta: '20:40 谷草 "C" 1650米',
            courseLabel: '跑馬地',
            draft: '後期追前',
          );
      expect(saved, isTrue);
      final raw = preferences.getString(horseNotesPreferenceKey);
      expect(raw, contains('"v":1'));
      expect(raw, contains('2026-09-23:5:1'));
      expect(raw, contains('後期追前'));

      final again = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(preferences)],
      );
      addTearDown(again.dispose);
      final record = resolveHorseNote(
        saved: again.read(horseNotesProvider),
        date: '2026-09-23',
        raceNum: 5,
        horseNo: 1,
        scratched: false,
      );
      expect(record.openingDraft, '後期追前');
      expect(record.history, hasLength(1));

      await again
          .read(horseNotesProvider.notifier)
          .save(
            date: '2026-09-23',
            raceNum: 5,
            runner: runner,
            raceMeta: '20:40 谷草 "C" 1650米',
            courseLabel: '跑馬地',
            draft: '後期追前',
          );
      final deduped = resolveHorseNote(
        saved: again.read(horseNotesProvider),
        date: '2026-09-23',
        raceNum: 5,
        horseNo: 1,
        scratched: false,
      );
      expect(deduped.history, hasLength(1));

      final scratched = await again
          .read(horseNotesProvider.notifier)
          .save(
            date: '2026-09-23',
            raceNum: 6,
            runner: _runner(7, '雙劍合璧', scratched: true),
            raceMeta: '',
            courseLabel: '跑馬地',
            draft: '不該寫入',
          );
      expect(scratched, isFalse);
      expect(
        again.read(horseNotesProvider).containsKey('2026-09-23:6:7'),
        isFalse,
      );
    },
  );
}

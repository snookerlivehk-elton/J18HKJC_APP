import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/app/text_scale_controller.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/features/board_sheet/board_sheet.dart';
import 'package:j18pro_racecard/features/board_sheet/board_sheet_host.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/racecard_insight/race_insight_bar.dart';
import 'package:j18pro_racecard/features/col_sort/col_layout.dart';
import 'package:j18pro_racecard/features/racecard_table/racecard_table.dart';
import 'package:j18pro_racecard/features/racecard_table/race_pills.dart';
import 'package:j18pro_racecard/widgets/theme_toggle.dart';

class RacecardPage extends ConsumerWidget {
  const RacecardPage({super.key});

  static const routeName = '/';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final racecard = ref.watch(racecardControllerProvider);
    return ColoredBox(
      color: tokens.shell,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 430),
          child: Scaffold(
            appBar: AppBar(
              automaticallyImplyLeading: false,
              leading: IconButton(
                key: const Key('menu-stub'),
                tooltip: '選單',
                onPressed: () {
                  ref
                      .read(boardSheetProvider.notifier)
                      .open(const BoardSheetRequest.menu());
                },
                icon: const Icon(Icons.menu),
              ),
              title: const Text('排位'),
              backgroundColor: Colors.transparent,
              surfaceTintColor: Colors.transparent,
              flexibleSpace: Container(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [tokens.navTop, tokens.nav2],
                  ),
                ),
              ),
              actions: const [ThemeToggle(), SizedBox(width: 4)],
            ),
            body: Stack(
              children: [
                racecard.when(
                  loading: () => const Center(
                    child: Text(
                      '載入賽事',
                      key: Key('racecard-loading'),
                      style: TextStyle(
                        fontFamily: 'Noto Sans TC',
                        fontSize: 15,
                      ),
                    ),
                  ),
                  error: (error, _) => Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            error is RaceLoadException
                                ? error.message
                                : '未能載入賽事',
                            key: const Key('racecard-error'),
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: tokens.text,
                              fontFamily: 'Noto Sans TC',
                              fontSize: 15,
                            ),
                          ),
                          const SizedBox(height: 12),
                          TextButton(
                            key: const Key('racecard-retry'),
                            onPressed: () {
                              ref.invalidate(racecardControllerProvider);
                            },
                            child: const Text(
                              '重試',
                              style: TextStyle(fontFamily: 'Noto Sans TC'),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  data: (state) => _RaceBoard(state: state),
                ),
                const BoardSheetAnchor(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _RaceBoard extends ConsumerWidget {
  const _RaceBoard({required this.state});

  final RacecardViewState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final meeting = state.meeting;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 4, 0),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '${meeting.courseLabel} · ${meeting.date}',
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 13,
                    color: tokens.muted,
                  ),
                ),
              ),
              TextButton(
                key: const Key('open-speed-map'),
                style: TextButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  minimumSize: Size.zero,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                onPressed: () {
                  ref
                      .read(boardSheetProvider.notifier)
                      .open(BoardSheetRequest.speedMap(state.currentRaceNum));
                },
                child: const Text(
                  '走位圖',
                  style: TextStyle(fontFamily: 'Noto Sans TC', fontSize: 13),
                ),
              ),
            ],
          ),
        ),
        RacePills(races: meeting.races, currentRaceNum: state.currentRaceNum),
        const RaceInsightBar(),
        Expanded(child: _scaledTable(context, ref)),
      ],
    );
  }

  /// Web list zoom applies to the board table only, not the title or insight bar.
  Widget _scaledTable(BuildContext context, WidgetRef ref) {
    final factor = textScaleFactor(ref.watch(textScaleLevelProvider));
    final scaled = MediaQuery.textScalerOf(context).scale(factor);
    return MediaQuery(
      data: MediaQuery.of(context)
          .copyWith(textScaler: TextScaler.linear(scaled)),
      child: RacecardTable(
        race: state.currentRace,
        marks: state.marks,
        columns: ref.watch(visibleScrollColumnsProvider),
        onCycleMark: (horseNo) {
          ref.read(racecardControllerProvider.notifier).cycleMark(horseNo);
        },
        onOpenHorse: (horseNo) {
          ref
              .read(boardSheetProvider.notifier)
              .open(BoardSheetRequest.horse(horseNo));
        },
        onOpenJtCollab: (horseNo) {
          ref
              .read(boardSheetProvider.notifier)
              .open(BoardSheetRequest.jtCollab(horseNo));
        },
      ),
    );
  }
}

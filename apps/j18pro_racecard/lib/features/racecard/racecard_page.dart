import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
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
                onPressed: () => _openMenu(context),
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
              actions: const [
                ThemeToggle(),
                SizedBox(width: 4),
              ],
            ),
            body: racecard.when(
              loading: () => const Center(child: Text('載入賽事')),
              error: (error, _) => Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text(
                    error is RaceLoadException ? error.message : '未能載入賽事',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: tokens.text,
                      fontFamily: 'Noto Sans TC',
                      fontSize: 15,
                    ),
                  ),
                ),
              ),
              data: (state) => _RaceBoard(state: state),
            ),
          ),
        ),
      ),
    );
  }

  void _openMenu(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) {
        return const SafeArea(
          child: Padding(
            padding: EdgeInsets.fromLTRB(20, 0, 20, 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '選單',
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                SizedBox(height: 8),
                Text(
                  '稍後提供',
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 15,
                  ),
                ),
              ],
            ),
          ),
        );
      },
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
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 2),
          child: Text(
            '${meeting.courseLabel} · ${meeting.date}',
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 13,
              color: tokens.muted,
            ),
          ),
        ),
        RacePills(
          races: meeting.races,
          currentRaceNum: state.currentRaceNum,
        ),
        Expanded(
          child: RacecardTable(
            race: state.currentRace,
            marks: state.marks,
            onCycleMark: (horseNo) {
              ref.read(racecardControllerProvider.notifier).cycleMark(horseNo);
            },
          ),
        ),
      ],
    );
  }
}

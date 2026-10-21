import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/racecard/runner_odds_row.dart';
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
              data: (state) => _RaceList(state: state),
            ),
          ),
        ),
      ),
    );
  }
}

class _RaceList extends ConsumerWidget {
  const _RaceList({required this.state});

  final RacecardViewState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final meeting = state.meeting;
    final race = state.currentRace;
    final labelStyle = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 12,
      fontWeight: FontWeight.w700,
      color: tokens.muted,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
          child: Text(
            '${meeting.courseLabel} · ${meeting.date}',
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 13,
              color: tokens.muted,
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: DropdownButton<int>(
            key: const Key('race-selector'),
            isExpanded: true,
            value: state.currentRaceNum,
            underline: Container(height: 1, color: tokens.line),
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: tokens.text,
            ),
            items: [
              for (final item in meeting.races)
                DropdownMenuItem<int>(
                  value: item.num,
                  child: Text(
                    item.selectorLabel,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
            ],
            onChanged: (raceNum) {
              if (raceNum == null) return;
              ref.read(racecardControllerProvider.notifier).selectRace(raceNum);
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Row(
            children: [
              SizedBox(width: runnerNoWidth, child: Text('馬號', style: labelStyle)),
              Expanded(child: Text('馬名', style: labelStyle)),
              SizedBox(
                width: runnerOddsWidth,
                child: Text('獨贏', textAlign: TextAlign.end, style: labelStyle),
              ),
              SizedBox(
                width: runnerOddsWidth,
                child: Text('位置', textAlign: TextAlign.end, style: labelStyle),
              ),
            ],
          ),
        ),
        Divider(height: 1, color: tokens.line),
        Expanded(
          child: ListView.separated(
            key: const Key('runner-list'),
            itemCount: race.runners.length,
            separatorBuilder: (_, _) => Divider(height: 1, color: tokens.line),
            itemBuilder: (context, index) {
              return RunnerOddsRow(runner: race.runners[index]);
            },
          ),
        ),
      ],
    );
  }
}

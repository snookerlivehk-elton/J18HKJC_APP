import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';

/// Horizontal race numbers. Active pill uses Web `--blue`, the rest `--green`.
class RacePills extends ConsumerWidget {
  const RacePills({
    required this.races,
    required this.currentRaceNum,
    super.key,
  });

  final List<Race> races;
  final int currentRaceNum;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    return Semantics(
      label: '場次',
      container: true,
      child: SizedBox(
        height: 36,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.fromLTRB(8, 5, 8, 5),
          itemCount: races.length,
          separatorBuilder: (context, index) => const SizedBox(width: 6),
          itemBuilder: (context, index) {
            final race = races[index];
            final active = race.num == currentRaceNum;
            return Semantics(
              button: true,
              selected: active,
              label: '第${race.num}場',
              child: Material(
                color: active ? tokens.blue : tokens.green,
                borderRadius: BorderRadius.circular(6),
                child: InkWell(
                  key: Key('race-pill-${race.num}'),
                  onTap: () {
                    ref.read(racecardControllerProvider.notifier).selectRace(race.num);
                  },
                  child: SizedBox(
                    width: 32,
                    height: 26,
                    child: Center(
                      child: Text(
                        '${race.num}',
                        style: const TextStyle(
                          fontFamily: 'Noto Sans TC',
                          fontSize: 13,
                          fontWeight: FontWeight.w800,
                          color: Colors.white,
                          height: 1,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

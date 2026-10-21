import 'package:flutter/material.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';

const runnerNoWidth = 36.0;
const runnerOddsWidth = 56.0;

/// One horse on the Phase 1 list. Not the Phase 2 locked table.
class RunnerOddsRow extends StatelessWidget {
  const RunnerOddsRow({required this.runner, super.key});

  final Runner runner;

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final nameStyle = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 15,
      fontWeight: FontWeight.w700,
      color: runner.scratched ? tokens.muted : tokens.text,
      decoration: runner.scratched ? TextDecoration.lineThrough : TextDecoration.none,
      decorationColor: tokens.muted,
    );
    final oddsStyle = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 15,
      color: tokens.text,
    );
    return Semantics(
      label: runner.scratched ? '${runner.no} ${runner.name} 已退出' : '${runner.no} ${runner.name}',
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(
          children: [
            SizedBox(
              width: runnerNoWidth,
              child: Text(
                '${runner.no}',
                style: nameStyle,
              ),
            ),
            Expanded(
              child: Text(
                runner.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: nameStyle,
              ),
            ),
            if (runner.scratched)
              SizedBox(
                width: runnerOddsWidth * 2,
                child: Text(
                  '已退出',
                  textAlign: TextAlign.end,
                  style: oddsStyle.copyWith(color: tokens.muted),
                ),
              )
            else ...[
              SizedBox(
                width: runnerOddsWidth,
                child: Text(
                  formatOdds(runner.win),
                  textAlign: TextAlign.end,
                  style: oddsStyle,
                ),
              ),
              SizedBox(
                width: runnerOddsWidth,
                child: Text(
                  formatOdds(runner.place),
                  textAlign: TextAlign.end,
                  style: oddsStyle,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

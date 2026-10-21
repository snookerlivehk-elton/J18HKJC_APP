import 'package:flutter/material.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/widgets/theme_toggle.dart';

/// Route placeholder for the racecard. No meeting list and no table yet.
class RacecardPage extends StatelessWidget {
  const RacecardPage({super.key});

  static const routeName = '/';

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
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
            body: Padding(
              padding: const EdgeInsets.fromLTRB(20, 28, 20, 20),
              child: Align(
                alignment: Alignment.topCenter,
                child: Text(
                  '賽事資料將於後續階段加入。Web 排位頁仍是驗收真源。',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: tokens.muted,
                    fontSize: 15,
                    height: 1.5,
                    fontFamily: 'Noto Sans TC',
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

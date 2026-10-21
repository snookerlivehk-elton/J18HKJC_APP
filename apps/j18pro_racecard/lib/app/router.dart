import 'package:flutter/widgets.dart';
import 'package:j18pro_racecard/features/racecard/racecard_page.dart';

/// Named routes. Phase 0 only mounts the racecard placeholder.
class J18Routes {
  const J18Routes._();

  static const racecard = RacecardPage.routeName;

  static final Map<String, WidgetBuilder> builders = {
    racecard: (_) => const RacecardPage(),
  };
}

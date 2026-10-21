import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/data/jjjc_transport.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/speed_map/speed_map.dart';

/// Loads one SpeedPro chart. Cache hits skip the network.
///
/// Non-2xx and transport failures become [SpeedMapFailure.offline]. A JSON
/// body without a `data:image` RaceMap becomes [SpeedMapFailure.noChart].
/// Neither failure is cached, so the next open tries again.
class SpeedMapRepository {
  const SpeedMapRepository({required this.transport, required this.cache});

  final JjjcTransport transport;
  final SpeedMapCache cache;

  Future<SpeedMapChart> load(int raceNum) async {
    final cached = cache.get(raceNum);
    if (cached != null) return cached;
    final JjjcHttpResult result;
    try {
      result = await transport.get(
        speedMapUri(raceNum),
        headers: const {'Accept': 'application/json,text/plain,*/*'},
      );
    } catch (_) {
      throw const SpeedMapException.offline();
    }
    if (result.statusCode < 200 || result.statusCode >= 300) {
      throw const SpeedMapException.offline();
    }
    final SpeedMapChart chart;
    try {
      chart = parseSpeedMap(result.body);
    } on SpeedMapException {
      rethrow;
    } catch (_) {
      throw const SpeedMapException.offline();
    }
    cache.put(raceNum, chart);
    return chart;
  }
}

final speedMapCacheProvider = Provider<SpeedMapCache>((ref) {
  return SpeedMapCache();
});

final speedMapRepositoryProvider = Provider<SpeedMapRepository>((ref) {
  return SpeedMapRepository(
    transport: ref.watch(jjjcTransportProvider),
    cache: ref.watch(speedMapCacheProvider),
  );
});

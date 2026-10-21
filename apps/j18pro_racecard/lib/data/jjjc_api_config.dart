/// Compile-time seam for api_jjjc.
///
/// Leave [baseUrl] empty to keep [DemoMeetingRepository] as the only source.
/// Point at a host with:
/// `flutter run --dart-define=JJJC_API_BASE=https://apicc.up.railway.app`
///
/// `JJJC_RESULTS_API_BASE` is the optional alias used by the Python sync.
/// The published catalog does not require an API key. [apiKey] is sent as
/// `Authorization: Bearer` only when a deployment sets `JJJC_API_KEY`.
class JjjcApiConfig {
  const JjjcApiConfig({
    this.baseUrl = '',
    this.resultsBaseUrl = '',
    this.apiKey = '',
    this.silkBaseUrl = defaultSilkCdnBase,
  });

  /// HKJC silk CDN. Web's `/silk/{code}.gif` proxy is the HTML app's own host.
  static const defaultSilkCdnBase =
      'https://racing.hkjc.com/racing/content/Images/RaceColor';

  final String baseUrl;
  final String resultsBaseUrl;
  final String apiKey;
  final String silkBaseUrl;

  factory JjjcApiConfig.fromEnvironment() {
    return const JjjcApiConfig(
      baseUrl: String.fromEnvironment('JJJC_API_BASE'),
      resultsBaseUrl: String.fromEnvironment('JJJC_RESULTS_API_BASE'),
      apiKey: String.fromEnvironment('JJJC_API_KEY'),
      silkBaseUrl: String.fromEnvironment(
        'J18_SILK_BASE',
        defaultValue: defaultSilkCdnBase,
      ),
    );
  }

  bool get isConfigured => resolvedBase.isNotEmpty;

  /// Root with no trailing slash. Empty when neither base is set.
  String get resolvedBase {
    final raw = baseUrl.trim().isNotEmpty ? baseUrl : resultsBaseUrl;
    return raw.trim().replaceAll(RegExp(r'/+$'), '');
  }

  Map<String, String> get headers {
    final out = <String, String>{'Accept': 'application/json'};
    final key = apiKey.trim();
    if (key.isNotEmpty) out['Authorization'] = 'Bearer $key';
    return out;
  }
}

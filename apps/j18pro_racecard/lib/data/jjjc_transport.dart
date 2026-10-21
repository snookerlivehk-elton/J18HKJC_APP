import 'package:http/http.dart' as http;
import 'package:j18pro_racecard/data/race_repository.dart';

class JjjcHttpResult {
  const JjjcHttpResult({required this.statusCode, required this.body});

  final int statusCode;
  final String body;
}

/// GET seam so tests can answer with contract JSON and no live host.
abstract interface class JjjcTransport {
  Future<JjjcHttpResult> get(Uri uri, {Map<String, String>? headers});
}

class HttpJjjcTransport implements JjjcTransport {
  HttpJjjcTransport({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  @override
  Future<JjjcHttpResult> get(Uri uri, {Map<String, String>? headers}) async {
    try {
      final response = await _client.get(uri, headers: headers);
      return JjjcHttpResult(
        statusCode: response.statusCode,
        body: response.body,
      );
    } catch (error) {
      throw RaceLoadException('未能連線，請檢查網絡');
    }
  }
}

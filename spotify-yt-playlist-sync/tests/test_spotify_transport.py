import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

from syncer import app

class Response:
    def __init__(self, code, value):
        self.status_code, self.value = code, value
    def json(self):
        return self.value

class SpotifyTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = app.Client(0)
        self.client.http = Mock()

    def test_proxy_encodes_complete_url_and_forwards_auth(self):
        self.client.http.request.return_value = Response(200, {'items': [], 'next': None})
        self.assertEqual(self.client.existing_tracks('myplaylist', 'secret-token'), set())
        method, url = self.client.http.request.call_args.args
        kwargs = self.client.http.request.call_args.kwargs
        self.assertEqual(method, 'GET')
        self.assertEqual(parse_qs(urlparse(url).query)['url'][0],
                         'https://api.spotify.com/v1/playlists/myplaylist/items?limit=50')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer secret-token')
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(self.client.spotify_backend, 'rest')

    def test_429_switches_to_web_player_before_writes(self):
        self.client.http.request.side_effect = [
            Response(429, {}),
            Response(200, {'data': {'playlistV2': {'content': {'items': [], 'totalCount': 0}}}}),
            Response(200, {'data': {'searchV2': {'tracksV2': {'items': [
                {'item': {'data': {'uri': 'spotify:track:abc', 'name': 'Song',
                                   'artists': {'items': [{'profile': {'name': 'Artist'}}]}}}}
            ]}}}}),
            Response(200, {'data': {'addItemsToPlaylist': {'__typename': 'AddItemsToPlaylistPayload'}}}),
        ]
        self.assertEqual(self.client.existing_tracks('p', 'token'), set())
        self.assertEqual(self.client.spotify_backend, 'web-player')
        self.assertEqual(self.client.search('Artist', 'Song', 'token')[0],
                         {'id': 'abc', 'name': 'Song', 'artists': [{'name': 'Artist'}]})
        self.client.add('p', 'abc', 'token')
        calls = self.client.http.request.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[-1].kwargs['json']['operationName'], 'addToPlaylist')
        self.assertEqual(calls[-1].kwargs['json']['variables']['playlistItemUris'], ['spotify:track:abc'])

    def test_webplayer_search_extracts_duration_when_available(self):
        self.client.spotify_backend = 'web-player'
        self.client.gql = Mock(return_value={'searchV2': {'tracksV2': {'items': [
            {'item': {'data': {'uri': 'spotify:track:abc', 'name': 'Song',
                'duration': {'totalMilliseconds': 181000},
                'artists': {'items': [{'profile': {'name': 'Artist'}}]}}}}
        ]}}})
        result = self.client.search('Artist', 'Song', 'token')
        self.assertEqual(result[0]['duration_ms'], 181000)

    def test_proxy_rejects_post_then_direct_webplayer_read(self):
        self.client.http.request.side_effect = [Response(429, {}), Response(405, {}),
            Response(200, {'data': {'playlistV2': {'content': {'items': [], 'totalCount': 0}}}})]
        self.client.existing_tracks('p', 'token')
        self.assertFalse(self.client.partner_proxy)
        self.assertEqual(self.client.http.request.call_args.args[1], app.PARTNER_URL)

    def test_proxy_401_falls_back_to_direct_webplayer_read(self):
        self.client.http.request.side_effect = [Response(401, {}), Response(401, {}),
            Response(200, {'data': {'playlistV2': {'content': {'items': [], 'totalCount': 0}}}})]
        self.assertEqual(self.client.existing_tracks('p', 'token'), set())
        self.assertEqual(self.client.spotify_backend, 'web-player')
        self.assertFalse(self.client.partner_proxy)
        self.assertEqual(self.client.http.request.call_args.args[1], app.PARTNER_URL)
        self.assertEqual(self.client.http.request.call_count, 3)

    def test_direct_401_stops_before_writes(self):
        self.client.http.request.side_effect = [Response(401, {}), Response(401, {}), Response(401, {})]
        with self.assertRaises(app.HttpFatal) as error:
            self.client.existing_tracks('p', 'token')
        self.assertEqual(error.exception.status, 401)
        self.assertIn('(direct)', str(error.exception))
        self.assertIsNone(self.client.spotify_backend)
        self.assertEqual(self.client.http.request.call_count, 3)

    def test_write_401_never_falls_back_or_retries(self):
        self.client.spotify_backend = 'web-player'
        self.client.http.request.return_value = Response(401, {})
        with self.assertRaises(app.HttpFatal):
            self.client.add('p', 'track', 'token')
        self.assertEqual(self.client.http.request.call_count, 1)

    def test_graphql_pagination_and_incomplete_page(self):
        self.client.gql = Mock(side_effect=[
            {'playlistV2': {'content': {'items': [{'itemV2': {'data': {'uri': 'spotify:track:first'}}}], 'totalCount': 2}}},
            {'playlistV2': {'content': {'items': [{'itemV2': {'data': {'uri': 'spotify:track:second'}}}], 'totalCount': 2}}},
        ])
        self.assertEqual(self.client.gql_existing_tracks('p', 't'), {'first', 'second'})
        self.assertEqual(self.client.gql.call_args_list[1].args[1]['offset'], 1)
        self.client.gql = Mock(return_value={'playlistV2': {'content': {'items': [], 'totalCount': 1}}})
        with self.assertRaises(app.FatalError): self.client.gql_existing_tracks('p', 't')

    def test_unknown_mutation_response_never_retries(self):
        self.client.spotify_backend = 'web-player'
        self.client.http.request.return_value = Response(200, {'errors': [{'message': 'unknown'}]})
        with self.assertRaises(app.UncertainWrite): self.client.add('p', 'abc', 't')
        self.assertEqual(self.client.http.request.call_count, 1)

    def test_rejects_non_spotify_target_and_redirects(self):
        with self.assertRaises(app.FatalError):
            self.client.request('GET', 'https://evil.example/', proxy=True)
        self.client.http.request.return_value = Response(302, {})
        with self.assertRaises(app.HttpFatal):
            self.client.request('GET', 'https://api.spotify.com/v1/me', proxy=True)
        with self.assertRaises(app.UncertainWrite):
            self.client.request('POST', 'https://api.spotify.com/v1/me', proxy=True, write=True)

if __name__ == '__main__':
    unittest.main()

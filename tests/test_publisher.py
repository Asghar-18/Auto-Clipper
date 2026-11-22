import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campaigns import get as get_profile
from zernio_publish import (
    caption_for,
    post_body,
    publishing_status,
    requested_platforms,
    scheduled_local_time,
    selected_accounts,
)


class ZernioPublisherTests(unittest.TestCase):
    def test_scheduled_time_is_converted_to_ist(self):
        self.assertEqual(scheduled_local_time('2026-11-18T06:30:00+00:00'), '2026-11-18T12:00:00')

    def test_post_body_uses_platform_specific_caption_and_media(self):
        metadata = {
            'title': 'GTA moment',
            'youtube_description': 'YouTube copy',
            'instagram_caption': 'Instagram copy',
            'hashtags': ['#GTA6'],
        }
        body = post_body(
            metadata,
            'https://media.example/clip.mp4',
            [('youtube', 'yt-account'), ('instagram', 'ig-account')],
            '2026-11-18T12:00:00',
        )
        self.assertEqual([p['platform'] for p in body['platforms']], ['youtube', 'instagram'])
        self.assertEqual(body['platforms'][0]['customContent'], 'YouTube copy')
        self.assertEqual(body['platforms'][1]['customContent'], 'Instagram copy')
        self.assertEqual(body['media_items'][0]['url'], 'https://media.example/clip.mp4')
        self.assertEqual(body['scheduled_for'], '2026-11-18T12:00:00')
        self.assertNotIn('publish_now', body)

    def test_caption_for_uses_the_selected_platforms_own_field(self):
        metadata = {
            'youtube_description': 'yt',
            'instagram_caption': 'ig',
            'tiktok_caption': 'tt',
            'x_caption': 'x',
        }
        self.assertEqual(caption_for('youtube', metadata), 'yt')
        self.assertEqual(caption_for('instagram', metadata), 'ig')
        self.assertEqual(caption_for('tiktok', metadata), 'tt')
        self.assertEqual(caption_for('x', metadata), 'x')

    def test_publishing_status_distinguishes_scheduled_from_published(self):
        targets = [('instagram', 'ig'), ('youtube', 'yt')]
        scheduled = {
            'zernio_posts': {
                'instagram': {'post_id': 'ig-1', 'status': 'scheduled'},
                'youtube': {'post_id': 'yt-1', 'status': 'scheduled'},
            }
        }
        self.assertEqual(publishing_status(scheduled, targets), 'scheduled')

        scheduled['zernio_posts']['youtube']['status'] = 'published'
        self.assertEqual(publishing_status(scheduled, targets), 'mixed')

        scheduled['zernio_posts']['youtube']['status'] = 'published'
        scheduled['zernio_posts']['instagram']['status'] = 'published'
        self.assertEqual(publishing_status(scheduled, targets), 'published')

        scheduled['zernio_posts']['instagram']['post_id'] = None
        self.assertEqual(publishing_status(scheduled, targets), 'partial')

    def test_all_platforms_expands_to_the_campaign_allowlist(self):
        kreek = get_profile('kreekcraft')
        dylan = get_profile('dylan_page')
        self.assertEqual(requested_platforms('both', kreek), ['youtube', 'instagram'])
        self.assertEqual(requested_platforms('all', kreek),
                         ['tiktok', 'instagram', 'youtube'])
        self.assertEqual(requested_platforms('campaign', dylan),
                         ['tiktok', 'instagram', 'twitter', 'youtube'])

    def test_kreek_rejects_x_and_dylan_accepts_it_with_x_account(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'does not allow'):
                selected_accounts(['twitter'], get_profile('kreekcraft'))
        with patch.dict(os.environ, {'ZERNIO_X_ACCOUNT_ID': 'x-account'}, clear=True):
            self.assertEqual(
                selected_accounts(['x'], get_profile('dylan_page')),
                [('twitter', 'x-account')],
            )


if __name__ == '__main__':
    unittest.main()

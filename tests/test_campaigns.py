import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campaign import config, metadata, render, select, source as source_module
from campaigns import get as get_profile
from campaigns import ids
from campaigns.base import rule_check
from shared import focus, storage, thumbnails
from shared import publishing
from zernio_publish import load_metadata


def base_meta(campaign_id, caption, thumb, approved=True, platforms=('youtube',)):
    return {
        'campaign_id': campaign_id,
        'title': 'GTA moment',
        'caption_text': caption,
        'youtube_description': caption,
        'instagram_caption': caption,
        'tiktok_caption': caption,
        'x_caption': caption,
        'caption_language': 'English',
        'validation': {
            'passed': True,
            'checks': [
                rule_check('resolution_1080x1920', True),
                rule_check('duration_in_range', True),
                rule_check('audio_stream_present', True),
            ],
        },
        'review': {'status': 'approved' if approved else 'pending'},
        'approved': approved,
        'thumbnail': thumb,
        'posted': {},
    }


class CampaignProfileTests(unittest.TestCase):
    def test_registry_has_two_independent_profiles(self):
        self.assertEqual(set(ids()), {'kreekcraft', 'dylan_page'})
        kreek = get_profile('kreekcraft')
        dylan = get_profile('dylan_page')
        self.assertNotIn('twitter', kreek.publishing.platforms)
        self.assertIn('twitter', dylan.publishing.platforms)
        self.assertTrue(kreek.editing.logo_required)
        self.assertFalse(dylan.editing.logo_required)
        self.assertTrue(dylan.editing.subject_focus_required)
        self.assertEqual(kreek.source.waiting_template_end, 75.0)
        self.assertIsNone(dylan.source.waiting_template_end)

    def test_missing_or_mismatched_campaign_stamp_is_rejected(self):
        profile = get_profile('kreekcraft')
        self.assertFalse(profile.campaign_checks(None)[0]['passed'])
        self.assertFalse(profile.campaign_checks('dylan_page')[0]['passed'])
        self.assertTrue(profile.campaign_checks('kreekcraft')[0]['passed'])

    def test_metadata_never_borrows_the_other_campaigns_caption(self):
        src = {'channel': 'tester', 'url': 'https://example.invalid/watch?v=x'}
        report = {'transcript': 'look at that crazy car chase', 'clip_id': 'clip-9',
                  'video_path': 'output/final/clip-9.mp4',
                  'srt_path': 'output/final/clip-9.srt'}
        kreek = metadata.build(report, src, 'kreekcraft')
        dylan = metadata.build(report, src, 'dylan_page')
        self.assertIn('Watch KreekCraft on YouTube and Twitch', kreek['caption_text'])
        self.assertIn('#KreekCraft', kreek['caption_text'])
        self.assertNotIn('#DylanPage', kreek['caption_text'])
        self.assertIn('#DylanPage', dylan['caption_text'])
        self.assertNotIn('Watch KreekCraft on YouTube and Twitch', dylan['caption_text'])
        self.assertNotIn('#KreekCraft', dylan['caption_text'])
        self.assertEqual({kreek['campaign_id'], dylan['campaign_id']},
                         {'kreekcraft', 'dylan_page'})
        self.assertEqual(dylan['clip_id'], 'clip-9')
        self.assertEqual(dylan['video_path'], 'output/final/clip-9.mp4')
        self.assertIn('twitter', dylan['platforms'])
        self.assertEqual(dylan['publishing']['status'], 'not_published')

    def test_caption_checks_detect_foreign_campaign_copy(self):
        kreek = get_profile('kreekcraft')
        dylan = get_profile('dylan_page')
        borrowed = {'caption_text': 'Watch KreekCraft on YouTube and Twitch #GTA6 #KreekCraft',
                    'caption_language': 'English'}
        checks = {c['name']: c['passed'] for c in dylan.caption_checks(borrowed)}
        self.assertFalse(checks['foreign_caption_phrase_absent'])
        self.assertFalse(checks['foreign_hashtags_absent'])
        self.assertFalse(checks['required_hashtags_present'])
        checks = {c['name']: c['passed'] for c in kreek.caption_checks(
            {'caption_text': '#DylanPage', 'caption_language': 'English'})}
        self.assertFalse(checks['exact_campaign_phrase'])
        self.assertFalse(checks['foreign_hashtags_absent'])

    def test_source_rules_are_campaign_specific(self):
        kreek = get_profile('kreekcraft')
        dylan = get_profile('dylan_page')
        good = {'url': 'https://example.invalid/v', 'channel': 'KreekCraft',
                'platform': 'youtube', 'upload_date': '20261120'}
        self.assertTrue(all(c['passed'] for c in kreek.source_checks(good)))
        dylan_source = {'url': 'https://example.invalid/v', 'channel': 'Dylan Page',
                        'platform': 'youtube', 'upload_date': '20261118'}
        result = {c['name']: c for c in dylan.source_checks(dylan_source)}
        self.assertFalse(result['source_within_campaign_window']['passed'])
        result = {c['name']: c for c in dylan.source_checks(
            dict(dylan_source, upload_date='20261120', channel='KreekCraft'))}
        self.assertFalse(result['source_authorized']['passed'])
        self.assertFalse(result['foreign_creator_source_absent']['passed'])

    def test_logo_free_filtergraph_has_a_valid_output_label(self):
        graph = render.build_filter('captions.ass', logo_supported=False)
        self.assertIn(';[captioned]null[out]', graph)
        self.assertNotIn('[captioned][captioned]', graph)

    def test_video_checks_enforce_strict_vertical_for_both_campaigns(self):
        info = {
            'streams': [{'codec_type': 'video', 'width': 1080, 'height': 1920},
                        {'codec_type': 'audio'}],
            'format': {'duration': '30.0'},
        }
        self.assertTrue(all(c['passed'] for c in get_profile('dylan_page').video_checks(info)))
        info['streams'][0]['height'] = 1921
        self.assertFalse(get_profile('dylan_page').video_checks(info)[0]['passed'])

    def test_focus_analysis_flags_uncertainty_for_manual_review(self):
        checks = focus.focus_checks(
            {'status': 'unavailable', 'presence_ratio': 0.0,
             'longest_absence_seconds': 0.0},
            get_profile('dylan_page'))
        self.assertTrue(all(c['manual_review'] for c in checks))
        self.assertTrue(all(not c['passed'] for c in checks))
        self.assertFalse(focus.analyze_focus.__doc__ is None)
        self.assertIn('visibility check', focus.analyze_focus.__doc__)

    def test_thumbnail_uniqueness_and_provenance_are_checked(self):
        record = {'clip_id': 'a', 'path': 'x.jpg', 'sha256': 'abc',
                  'from_source_frame': True}
        known = [{'clip_id': 'b', 'sha256': 'abc'}]
        checks = {c['name']: c['passed'] for c in
                  get_profile('dylan_page').thumbnail_checks(record, known)}
        self.assertFalse(checks['thumbnail_unique'])
        self.assertTrue(checks['thumbnail_from_source_frame'])
        checks = {c['name']: c['passed'] for c in
                  get_profile('kreekcraft').thumbnail_checks(record, [])}
        self.assertTrue(checks['thumbnail_present'])

    def test_explicit_campaign_only_disambiguates_unstamped_clips(self):
        self.assertEqual(storage.require_campaign({}, 'legacy-name', 'kreekcraft'),
                         'kreekcraft')
        with self.assertRaisesRegex(ValueError, 'campaign mismatch'):
            storage.require_campaign({'campaign_id': 'dylan_page'}, 'x', 'kreekcraft')

    def test_legacy_timeline_fallback_is_kreek_only(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'abc-gameplay-timeline.json').write_text('{}', encoding='utf-8')
            with patch.object(config, 'METADATA', folder), \
                    patch.dict(os.environ, {'GTA_CAMPAIGN': 'kreekcraft'}):
                self.assertTrue(config.timeline_path('abc').endswith(
                    'abc-gameplay-timeline.json'))
            with patch.object(config, 'METADATA', folder), \
                    patch.dict(os.environ, {'GTA_CAMPAIGN': 'dylan_page'}):
                self.assertTrue(config.timeline_path('abc').endswith(
                    'dylan-abc-gameplay-timeline.json'))

    def test_legacy_campaign_inference_is_read_only(self):
        self.assertEqual(storage.infer_campaign({'campaign_id': 'dylan_page'}, 'kreek-old'),
                         'dylan_page')
        self.assertEqual(storage.infer_campaign({}, 'kreek-dy-source-01'), 'kreekcraft')
        self.assertEqual(storage.infer_campaign(
            {'caption_text': 'hello #DylanPage'}, 'unknown'), 'dylan_page')
        self.assertIsNone(storage.infer_campaign(
            {'caption_text': '#GTA6 #KreekCraft'}, 'dylan-old'))
        self.assertIsNone(storage.infer_campaign(
            {'campaign_id': 'kreekcraft', 'campaign': {'id': 'dylan_page'}}, 'clip'))

    def test_audio_cache_is_isolated_by_campaign(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'vod_audio.opus').write_bytes(b'legacy shared cache')
            Path(folder, 'vod_audio-dylan_page-abc.opus').write_bytes(b'dylan cache')
            # Build a Source directly so no decoder or network access is needed.
            src = source_module.Source(
                key='abc', label='abc', file=None, url='https://example.invalid/v',
                title='', channel='Dylan Page', duration=1.0, media_path=None,
                is_local=False, info={}, campaign_id='dylan_page')
            found = source_module.audio_files(folder, src)
            self.assertEqual(len(found), 1)
            self.assertIn('vod_audio-dylan_page-abc', found[0])
            self.assertNotIn('vod_audio.opus', found[0])

    def test_selection_exclusions_do_not_leak_across_campaigns(self):
        with tempfile.TemporaryDirectory() as folder:
            candidates = Path(folder, 'candidates')
            finals = Path(folder, 'final')
            candidates.mkdir()
            finals.mkdir()
            (candidates / 'kreek-old.json').write_text(json.dumps({
                'campaign_id': 'kreekcraft', 'source': {'key': 'k1', 'url': 'k'},
                'source_start': 100, 'source_end': 130,
            }), encoding='utf-8')
            (finals / 'dylan-old.json').write_text(json.dumps({
                'campaign_id': 'dylan_page', 'source': {'key': 'd1', 'url': 'd'},
                'source_start': 100, 'source_end': 130,
            }), encoding='utf-8')
            (candidates / 'dylan-unscoped.json').write_text(json.dumps({
                'campaign_id': 'dylan_page', 'source': {},
                'source_start': 100, 'source_end': 130,
            }), encoding='utf-8')
            with patch.object(select.config, 'CANDIDATES', str(candidates)), \
                    patch.object(select.config, 'FINAL', str(finals)):
                ranges = select.existing_ranges([], source_key='d1', source_url='d',
                                                campaign_id='dylan_page')
            self.assertEqual([name for _, _, name in ranges], ['dylan-old.json'])


class PublishingPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        image = Path(self.temp.name, 'clip-thumb.jpg')
        image.write_bytes(b'fake-jpeg-bytes')
        self.thumb = {
            'clip_id': 'clip-1', 'path': str(image), 'filename': image.name,
            'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
            'width': 1080, 'height': 1920, 'from_source_frame': True,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_dylan_clip_passes_with_explicit_approval_and_x(self):
        meta = base_meta('dylan_page', 'crazy moment #DylanPage', self.thumb)
        with patch.dict(os.environ, {'ZERNIO_X_ACCOUNT_ID': 'x-1'}), \
                patch.object(publishing.storage, 'known_thumbnails', return_value=[]):
            checks = publishing.preflight(meta, get_profile('dylan_page'), ['twitter'])
        self.assertTrue(all(c['passed'] for c in checks),
                        [c for c in checks if not c['passed']])

    def test_unapproved_and_rejected_clips_fail(self):
        meta = base_meta('dylan_page', 'crazy moment #DylanPage', self.thumb, approved=False)
        with patch.dict(os.environ, {'ZERNIO_X_ACCOUNT_ID': 'x-1'}), \
                patch.object(publishing.storage, 'known_thumbnails', return_value=[]):
            checks = {c['name']: c['passed'] for c in
                      publishing.preflight(meta, get_profile('dylan_page'), ['twitter'])}
        self.assertFalse(checks['explicit_manual_approval'])
        meta['rejected'] = True
        meta['approved'] = True
        with patch.dict(os.environ, {'ZERNIO_X_ACCOUNT_ID': 'x-1'}), \
                patch.object(publishing.storage, 'known_thumbnails', return_value=[]):
            checks = {c['name']: c['passed'] for c in
                      publishing.preflight(meta, get_profile('dylan_page'), ['twitter'])}
        self.assertFalse(checks['not_rejected_or_test'])

    def test_kreek_cannot_be_published_to_x(self):
        caption = 'Watch KreekCraft on YouTube and Twitch #GTA6 #KreekCraft #GrandTheftAutoVI'
        meta = base_meta('kreekcraft', caption, self.thumb)
        with patch.object(publishing.storage, 'known_thumbnails', return_value=[]):
            checks = {c['name']: c['passed'] for c in
                      publishing.preflight(meta, get_profile('kreekcraft'), ['twitter'])}
        self.assertFalse(checks['platforms_allowed_for_campaign'])

    def test_missing_thumbnail_blocks_publishing(self):
        meta = base_meta('dylan_page', 'crazy moment #DylanPage', None)
        with patch.dict(os.environ, {'ZERNIO_X_ACCOUNT_ID': 'x-1'}), \
                patch.object(publishing.storage, 'known_thumbnails', return_value=[]):
            checks = {c['name']: c['passed'] for c in
                      publishing.preflight(meta, get_profile('dylan_page'), ['twitter'])}
        self.assertFalse(checks['thumbnail_present'])

    def test_load_metadata_refuses_campaign_mismatch(self):
        meta = base_meta('dylan_page', '#DylanPage', self.thumb, approved=False)
        path = Path(self.temp.name, 'clip.json')
        path.write_text(json.dumps(meta), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'campaign mismatch'):
            load_metadata(path, campaign_id='kreekcraft', name='clip')


if __name__ == '__main__':
    unittest.main()

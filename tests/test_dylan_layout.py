import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campaign import dylan_layout, render
from campaigns import get as get_profile


class DylanLayoutTests(unittest.TestCase):
    def test_profile_layouts_are_isolated(self):
        self.assertEqual(get_profile('dylan_page').video.layout, 'adaptive-stacked')
        self.assertEqual(get_profile('kreekcraft').video.layout, 'fit')
        self.assertFalse(get_profile('dylan_page').editing.logo_required)
        self.assertTrue(get_profile('kreekcraft').editing.logo_required)

    def test_crop_offset_centres_face_and_clamps_to_frame(self):
        self.assertAlmostEqual(
            dylan_layout.crop_offset_for_x(960, 1920, 1080), 0.5, places=4)
        self.assertEqual(dylan_layout.crop_offset_for_x(0, 1920, 1080), 0.0)
        self.assertEqual(dylan_layout.crop_offset_for_x(1920, 1920, 1080), 1.0)

    def test_smooth_offsets_limits_pan_speed(self):
        keys = dylan_layout.smooth_offsets([(0.0, 0.0), (1.0, 1.0)])
        self.assertEqual(keys[0][1], 0.0)
        self.assertLessEqual(keys[-1][1], dylan_layout.MAX_CROP_SPEED + 1e-9)
        self.assertGreater(keys[-1][1], 0.0)

    def test_adaptive_keys_requires_confident_visible_face_signal(self):
        good = {
            'status': 'ok',
            'presence_ratio': 1.0,
            'observations': [
                {'time': float(i), 'faces': 1, 'area': 0.01,
                 'cx': 960 + i, 'cy': 540}
                for i in range(10)
            ],
        }
        with patch.object(dylan_layout.focus, 'analyze_focus', return_value=good), \
                patch.object(dylan_layout, 'source_dimensions',
                             return_value=(1920, 1080)):
            keys = dylan_layout.adaptive_keys('sample.mp4', 0.0, 10.0)
        self.assertIsNotNone(keys)
        self.assertEqual(len(keys), 10)
        self.assertAlmostEqual(keys[0][1], 0.5, places=4)

        tiny = dict(good, observations=[
            dict(item, area=0.0005) for item in good['observations']])
        with patch.object(dylan_layout.focus, 'analyze_focus', return_value=tiny), \
                patch.object(dylan_layout, 'source_dimensions',
                             return_value=(1920, 1080)):
            self.assertIsNone(dylan_layout.adaptive_keys('sample.mp4', 0.0, 10.0))

        uncertain = dict(good, status='needs_manual_review')
        with patch.object(dylan_layout.focus, 'analyze_focus', return_value=uncertain):
            self.assertIsNone(dylan_layout.adaptive_keys('sample.mp4', 0.0, 10.0))

    def test_adaptive_filter_is_vertical_logo_free_and_pans(self):
        graph = dylan_layout.build_filter('cap.ass', [(0.0, 0.4), (2.0, 0.6)])
        self.assertIn('scale=1080:1920:force_original_aspect_ratio=increase', graph)
        self.assertIn('crop=1080:1920:', graph)
        self.assertIn('ass=cap.ass[out]', graph)
        self.assertNotIn('boxblur', graph)
        self.assertNotIn('overlay', graph)
        self.assertTrue(graph.endswith('[out]'))

    def test_stacked_face_panel_uses_exact_facecam_box_and_gameplay_is_wide(self):
        graph = dylan_layout.build_stacked_filter('cap.ass', (120, 80, 260, 260))
        self.assertIn('vstack=inputs=2', graph)
        self.assertIn('crop=260:260:120:80', graph)
        self.assertIn('scale=1080:960:force_original_aspect_ratio=increase', graph)
        self.assertIn('ass=cap.ass[out]', graph)
        self.assertNotIn('if(lt(t', graph)
        self.assertNotIn('boxblur', graph)
        self.assertNotIn('overlay', graph)
        self.assertTrue(graph.endswith('[out]'))

    def test_compose_filter_is_campaign_isolated_and_falls_back_to_fit(self):
        keys = [(0.0, 0.5), (1.0, 0.6)]
        with patch.object(dylan_layout, 'adaptive_keys', return_value=keys), \
                patch.object(dylan_layout, 'facecam_box', return_value=(120, 80, 260, 260)):
            graph, adaptive = render.compose_filter(
                get_profile('dylan_page'), 'cap.ass', 'sample.mp4', 0.0, 10.0)
        self.assertTrue(adaptive)
        self.assertIn('vstack=inputs=2', graph)
        self.assertIn('crop=260:260:120:80', graph)
        self.assertNotIn('boxblur', graph)

        with patch.object(dylan_layout, 'adaptive_keys', return_value=keys), \
                patch.object(dylan_layout, 'facecam_box', return_value=None):
            graph, adaptive = render.compose_filter(
                get_profile('dylan_page'), 'cap.ass', 'sample.mp4', 0.0, 10.0)
        self.assertFalse(adaptive)
        self.assertIn('boxblur=30:5', graph)

        with patch.object(dylan_layout, 'adaptive_keys', return_value=keys) as mocked:
            graph, adaptive = render.compose_filter(
                get_profile('kreekcraft'), 'cap.ass', 'sample.mp4', 0.0, 10.0,
                has_logo=True)
        mocked.assert_not_called()
        self.assertFalse(adaptive)
        self.assertIn('[1:v]scale=1080:-2[logo]', graph)
        self.assertIn('overlay=0:24:shortest=0[out]', graph)

    def test_stacked_filter_top_chain_is_unchanged(self):
        graph = dylan_layout.build_stacked_filter('cap.ass', (960, 0, 960, 540))
        self.assertIn('[face]crop=960:540:960:0,'
                      'scale=1080:960:force_original_aspect_ratio=increase,'
                      'crop=1080:960[top]', graph)

    def test_visible_source_box_shows_16x9_region_loses_its_sides(self):
        x, y, w, h = dylan_layout.visible_source_box((960, 0, 960, 540))
        self.assertAlmostEqual(x, 1136.25, places=2)
        self.assertAlmostEqual(w, 607.5, places=2)
        self.assertAlmostEqual(y, 0.0, places=2)
        self.assertAlmostEqual(h, 540.0, places=2)
        # A 9:8 region is shown whole.
        self.assertEqual(tuple(round(v) for v in
                               dylan_layout.visible_source_box((100, 50, 540, 480))),
                         (100, 50, 540, 480))

    def test_preview_parses_grid_cells(self):
        from campaign import top_panel_preview as preview
        self.assertEqual(preview.parse_cells('A5:D8'), (0.5, 0.0, 0.5, 0.5))
        self.assertEqual(preview.parse_cells('d8:a5'), (0.5, 0.0, 0.5, 0.5))
        self.assertEqual(preview.parse_cells('B6:B6'), (0.625, 0.125, 0.125, 0.125))
        with self.assertRaises(ValueError):
            preview.parse_cells('Z9:A1')

    def test_confirmed_regions_are_9x8_and_fully_visible(self):
        with patch.object(dylan_layout, 'source_dimensions', return_value=(1920, 1080)):
            live = dylan_layout.facecam_box('s.mp4', 0, 30, video_id='xFcI47X15Lo')
            best = dylan_layout.facecam_box('s.mp4', 0, 30, video_id='i1zUT_gKQzA')
            default = dylan_layout.facecam_box('s.mp4', 0, 30)
        self.assertEqual(live, (1316, 0, 604, 537))
        self.assertEqual(default, live)
        self.assertEqual(best, (1200, 0, 640, 569))
        for box in (live, best):
            self.assertLessEqual(box[0] + box[2], 1920)
            visible = dylan_layout.visible_source_box(box)
            self.assertLess(abs(visible[0] - box[0]), 1.5)
            self.assertLess(abs(visible[2] - box[2]), 1.5)

    def test_compose_filter_passes_video_id_to_facecam_box(self):
        profile = get_profile('dylan_page')
        with patch.object(dylan_layout, 'adaptive_keys', return_value=[(0, 0.5), (1, 0.5)]), \
                patch.object(dylan_layout, 'source_dimensions', return_value=(1920, 1080)):
            graph, adaptive = render.compose_filter(
                profile, 'cap.ass', 's.mp4', 0.0, 30.0, video_id='i1zUT_gKQzA')
        self.assertTrue(adaptive)
        self.assertIn('[face]crop=640:569:1200:0,', graph)

    def test_gameplay_region_crops_bottom_panel_only_when_set(self):
        self.assertIsNone(dylan_layout.gameplay_box(1920, 1080))
        box = dylan_layout.gameplay_box(1920, 1080, (101 / 1920, 0.0, 1215 / 1920, 1.0))
        self.assertEqual(box, (101, 0, 1215, 1080))
        self.assertLessEqual(box[0] + box[2], 1316)   # stops before the webcam window
        graph = dylan_layout.build_stacked_filter('c.ass', (1316, 0, 604, 537), box)
        self.assertIn('[game]crop=1215:1080:101:0,scale=1080:960', graph)
        default = dylan_layout.build_stacked_filter('c.ass', (1316, 0, 604, 537))
        self.assertIn('[game]scale=1080:960:force_original_aspect_ratio=increase,'
                      'crop=1080:960[bottom]', default)

    def test_preview_parses_pixel_region(self):
        from campaign import top_panel_preview as preview
        self.assertEqual(preview.parse_region('960, 0, 960, 540'), (0.5, 0.0, 0.5, 0.5))
        with self.assertRaises(ValueError):
            preview.parse_region('1500,0,604,537')   # past the right edge
        with self.assertRaises(ValueError):
            preview.parse_region('1,2,3')


if __name__ == '__main__':
    unittest.main()

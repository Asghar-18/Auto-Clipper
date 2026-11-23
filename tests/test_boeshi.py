"""Boeshi campaign + three-way isolation tests. No network, no rendering."""
import dataclasses
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import zernio_publish
from campaign import config, dylan_layout, metadata, render
from campaigns import get as get_profile
from campaigns import ids
from shared import storage

LINK = "twitch.tv/darealboeshi"


def checks(profile, text):
    return {c["name"]: c["passed"] for c in profile.caption_checks(
        {"caption_text": text, "caption_language": "English"})}


class StrictCampaignResolutionTests(unittest.TestCase):
    def test_missing_or_unknown_campaign_is_an_error(self):
        for value in (None, "", "  ", "boeshi_gta", "kreek"):
            with self.assertRaises(ValueError):
                get_profile(value)
            with self.assertRaises(ValueError):
                config.active_profile(value)

    def test_gta_campaign_environment_no_longer_selects_a_campaign(self):
        with patch.dict("os.environ", {"GTA_CAMPAIGN": "kreekcraft"}):
            with self.assertRaises(ValueError):
                config.active_profile(None)

    def test_every_campaign_stage_requires_campaign_flag(self):
        from campaign import analyze, gameplay, refine, select
        from campaign import render as render_module
        stages = (gameplay.main, analyze.main, select.main, render_module.main, refine.main)
        for stage in stages:
            err = io.StringIO()
            with self.assertRaises(SystemExit), patch("sys.stderr", err):
                stage(["--url", "https://example.invalid/v", "--timestamps", "t.json"])
            self.assertIn("--campaign", err.getvalue(), stage.__module__)


class BoeshiProfileTests(unittest.TestCase):
    def setUp(self):
        self.boeshi = get_profile("boeshi")

    def test_profile_basics(self):
        self.assertIn("boeshi", ids())
        self.assertEqual(self.boeshi.clip_prefix, "boeshi")
        self.assertEqual(self.boeshi.source.platforms, ("twitch",))
        self.assertTrue(self.boeshi.editing.logo_required)
        self.assertEqual(self.boeshi.editing.max_reposts, 5)
        self.assertFalse(self.boeshi.publishing.allow_unattended)
        self.assertEqual(self.boeshi.publishing.platforms, ())  # draft: cannot publish

    def test_every_template_contains_the_twitch_link_and_passes(self):
        self.assertTrue(self.boeshi.captions.templates)
        for template in self.boeshi.captions.templates:
            self.assertIn(LINK, template)
            self.assertTrue(all(checks(self.boeshi, template).values()), template)

    def test_caption_without_link_fails(self):
        self.assertFalse(checks(self.boeshi, "Boeshi goes crazy")["required_caption_text_present"])

    def test_generated_metadata_always_has_link_and_is_deterministic(self):
        src = {"channel": "DaRealBoeshi", "url": "https://www.twitch.tv/videos/1", "platform": "twitch"}
        for index in range(20):
            report = {"transcript": "bro my voice cracked again chat", "clip_id": f"boeshi-x-{index}"}
            first = metadata.build(report, src, "boeshi")
            second = metadata.build(report, src, "boeshi")
            self.assertIn(LINK, first["caption_text"])
            self.assertEqual(first["caption_text"], second["caption_text"])
            self.assertIn(first["caption_template"], self.boeshi.captions.templates)
            self.assertEqual(first["campaign_id"], "boeshi")
            self.assertTrue(all(checks(self.boeshi, first["caption_text"]).values()))

    def test_source_rules(self):
        good = {"url": "https://www.twitch.tv/videos/1", "channel": "DaRealBoeshi",
                "platform": "twitch", "upload_date": "20261120"}
        result = {c["name"]: c["passed"] for c in self.boeshi.source_checks(good)}
        self.assertTrue(result["source_authorized"])
        self.assertTrue(result["source_platform_allowed"])
        self.assertFalse(result["source_within_campaign_window"])  # cutoff not set yet
        for bad in (dict(good, channel="Dylan Page"), dict(good, channel="KreekCraft"),
                    dict(good, platform="youtube")):
            result = {c["name"]: c["passed"] for c in self.boeshi.source_checks(bad)}
            self.assertFalse(result["source_authorized"] and result["source_platform_allowed"])

    def test_draft_profile_refuses_every_publishing_platform(self):
        for platform in ("tiktok", "instagram", "youtube", "twitter"):
            self.assertFalse(self.boeshi.platform_checks([platform])[0]["passed"])

    def test_legacy_inference_knows_boeshi(self):
        self.assertEqual(storage.infer_campaign({}, "boeshi-abc-20261123-01"), "boeshi")
        self.assertEqual(storage.infer_campaign({"caption_text": f"FULL STREAM at {LINK}"}), "boeshi")


class ThreeWayCaptionIsolationTests(unittest.TestCase):
    SAMPLES = {
        "kreekcraft": "Watch KreekCraft on YouTube and Twitch #GTA6 #KreekCraft #GrandTheftAutoVI",
        "dylan_page": "\"what a run\" #DylanPage",
        "boeshi": f"\"what a run\" FULL STREAM at {LINK}",
    }

    def test_each_campaigns_own_sample_passes(self):
        for campaign_id, text in self.SAMPLES.items():
            self.assertTrue(all(checks(get_profile(campaign_id), text).values()), campaign_id)

    def test_each_campaign_rejects_the_other_two(self):
        for campaign_id in self.SAMPLES:
            profile = get_profile(campaign_id)
            for other_id, other_text in self.SAMPLES.items():
                if other_id == campaign_id:
                    continue
                own = self.SAMPLES[campaign_id]
                result = checks(profile, own + " " + other_text)
                self.assertFalse(all(result.values()),
                                 f"{campaign_id} accepted {other_id} copy: {result}")

    def test_kreek_still_forbids_urls_and_dylan_forbids_boeshi_link(self):
        kreek = checks(get_profile("kreekcraft"), self.SAMPLES["kreekcraft"] + " " + LINK)
        self.assertFalse(kreek["foreign_caption_phrase_absent"])
        dylan = checks(get_profile("dylan_page"), "#DylanPage " + LINK.upper())
        self.assertFalse(dylan["foreign_caption_phrase_absent"])


class LayoutIsolationTests(unittest.TestCase):
    def test_boeshi_has_no_stacked_regions(self):
        video = get_profile("boeshi").video
        self.assertIsNone(video.stacked_top_region)
        self.assertEqual(video.stacked_top_overrides, ())
        self.assertIsNone(video.stacked_bottom_region)

    def test_stacked_layout_without_profile_regions_falls_back_to_fit(self):
        boeshi = get_profile("boeshi")
        stacked = dataclasses.replace(boeshi, video=dataclasses.replace(
            boeshi.video, layout="adaptive-stacked"))
        with patch.object(dylan_layout, "adaptive_keys", return_value=[(0, 0.5), (1, 0.5)]), \
                patch.object(dylan_layout, "source_dimensions", return_value=(1920, 1080)):
            graph, adaptive = render.compose_filter(stacked, "cap.ass", "s.mp4", 0.0, 30.0,
                                                    video_id="xFcI47X15Lo")
        self.assertFalse(adaptive)
        self.assertNotIn("crop=604:537:1316:0", graph)

    def test_dylan_filtergraph_is_unchanged(self):
        dylan = get_profile("dylan_page")
        with patch.object(dylan_layout, "adaptive_keys", return_value=[(0, 0.5), (1, 0.5)]), \
                patch.object(dylan_layout, "source_dimensions", return_value=(1920, 1080)):
            graph, adaptive = render.compose_filter(dylan, "cap.ass", "s.mp4", 0.0, 30.0,
                                                    video_id="xFcI47X15Lo")
        self.assertTrue(adaptive)
        self.assertEqual(graph, (
            "[0:v]setpts=PTS-STARTPTS,split=2[face][game];"
            "[face]crop=604:537:1316:0,scale=1080:960:force_original_aspect_ratio=increase,"
            "crop=1080:960[top];"
            "[game]crop=1215:1080:101:0,scale=1080:960:force_original_aspect_ratio=increase,"
            "crop=1080:960[bottom];"
            "[top][bottom]vstack=inputs=2,ass=cap.ass[out]"))


class PublisherIsolationTests(unittest.TestCase):
    def test_boeshi_account_variables_are_loadable_from_env_file(self):
        for name in get_profile("boeshi").publishing.account_env.values():
            self.assertIn(name, zernio_publish.ENV_NAMES)
        self.assertNotIn("GTA_CAMPAIGN", zernio_publish.ENV_NAMES)

    def test_boeshi_accounts_are_separate_from_other_campaigns(self):
        boeshi = set(get_profile("boeshi").publishing.account_env.values())
        for other in ("kreekcraft", "dylan_page"):
            self.assertFalse(boeshi & set(get_profile(other).publishing.account_env.values()))

    def test_unattended_mode_is_refused_for_boeshi(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder, "boeshi-x-20261123-01.mp4")
            video.write_bytes(b"not really a video")
            meta = {"campaign_id": "boeshi", "title": "t", "youtube_description": "d " + LINK,
                    "instagram_caption": "c " + LINK, "approved": True,
                    "review": {"status": "approved"},
                    "integrity": {"content_sha256": hashlib.sha256(video.read_bytes()).hexdigest()}}
            video.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
            argv = ["zernio_publish.py", str(video.with_suffix("")), "--platform", "tiktok",
                    "--scheduled-for", "2030-01-01T12:00:00+05:00", "--unattended", "--publish"]
            with patch.object(sys, "argv", argv), patch.object(zernio_publish, "load_dotenv"), \
                    patch.dict("os.environ", {"GTA_UNATTENDED_POSTS": "1"}):
                with self.assertRaises(SystemExit) as raised:
                    zernio_publish.main()
        self.assertIn("does not allow unattended", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

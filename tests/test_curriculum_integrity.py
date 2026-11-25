"""Structural checks on curriculum content, with the maths actually evaluated.

Written when Quantitative Aptitude was added for the real-learner pilot. These
questions go in front of people doing a favour, and an answer marked correct
that is not correct destroys their trust in everything else on the page - the
adaptive difficulty, the diagnosis, the advice. A typo here is not cosmetic.

The arithmetic checks recompute each answer from its premise rather than
asserting the stored index, so the test fails if the stored answer is wrong
rather than agreeing with it.
"""
import pytest

from utils.constants import SUBMODULE_DEFINITIONS, STATIC_CHEAT_SHEETS


ALL_MODULES = [(topic, module)
               for topic, modules in SUBMODULE_DEFINITIONS.items()
               for module in modules]


class TestEveryCheckpointIsWellFormed:
    @pytest.mark.parametrize("topic,module", ALL_MODULES,
                             ids=[f"{t}-{m['title'][:18]}" for t, m in ALL_MODULES])
    def test_checkpoint_structure(self, topic, module):
        for cp in module["checkpoints"]:
            assert cp["options"], f"{cp['id']} has no options"
            assert 0 <= cp["correct_index"] < len(cp["options"]), \
                f"{cp['id']} correct_index points outside its options"
            assert len(set(cp["options"])) == len(cp["options"]), \
                f"{cp['id']} has a duplicate option, so two answers are 'correct'"
            assert cp["question"].strip(), f"{cp['id']} has an empty question"
            assert cp["explanation"].strip(), f"{cp['id']} has no explanation"
            for option in cp["options"]:
                assert option.strip(), f"{cp['id']} has a blank option"

    @pytest.mark.parametrize("topic,module", ALL_MODULES,
                             ids=[f"{t}-{m['title'][:18]}" for t, m in ALL_MODULES])
    def test_playback_window_is_sane(self, topic, module):
        assert module["start_sec"] >= 0
        assert module["end_sec"] > module["start_sec"], \
            f"{module['title']} ends before it starts"
        assert module["video_id"], f"{module['title']} has no video"

    def test_checkpoint_ids_are_unique_across_the_curriculum(self):
        ids = [cp["id"] for _, m in ALL_MODULES for cp in m["checkpoints"]]
        duplicates = {i for i in ids if ids.count(i) > 1}
        assert not duplicates, f"duplicate checkpoint ids: {sorted(duplicates)}"


class TestAptitudeAnswersAreArithmeticallyCorrect:
    """Each answer is recomputed from its premise. These are the only
    questions in the curriculum whose correctness a test can actually
    establish rather than assume.
    """

    @staticmethod
    def _answer(cp_id):
        for _, module in ALL_MODULES:
            for cp in module["checkpoints"]:
                if cp["id"] == cp_id:
                    return cp["options"][cp["correct_index"]]
        raise AssertionError(f"{cp_id} not found")

    def test_successive_percentage_change(self):
        final = 100 * 1.20 * 0.80
        assert final == 96
        assert self._answer("qa-cp1-1") == "4% lower"

    def test_percentage_of_a_number(self):
        assert 0.15 * 240 == 36
        assert self._answer("qa-cp1-2") == "36"

    def test_percentage_increase_uses_the_original(self):
        assert (50 - 40) / 40 * 100 == 25
        assert self._answer("qa-cp1-3") == "25%"

    def test_dividing_in_a_ratio(self):
        assert 350 * 3 / 7 == 150
        assert self._answer("qa-cp2-1") == "150"

    def test_chaining_two_ratios(self):
        assert (2 * 4, 3 * 4, 3 * 5) == (8, 12, 15)
        assert self._answer("qa-cp2-2") == "8:12:15"

    def test_recovering_a_part_from_a_ratio(self):
        assert 56 * 5 / 7 == 40
        assert self._answer("qa-cp2-3") == "40"

    def test_kmh_to_ms(self):
        assert 72 * 5 / 18 == 20
        assert self._answer("qa-cp3-1") == "20 m/s"

    def test_time_from_distance_and_speed(self):
        assert 150 / 50 == 3
        assert self._answer("qa-cp3-2") == "3 hours"

    def test_average_speed_is_the_harmonic_mean(self):
        assert 2 * 60 * 40 / (60 + 40) == 48
        assert self._answer("qa-cp3-3") == "48 km/h"

    def test_combined_work_rate(self):
        assert round(1 / (1 / 10 + 1 / 15), 6) == 6
        assert self._answer("qa-cp4-1") == "6 days"

    def test_scaling_workers(self):
        assert 6 * 12 / 8 == 9
        assert self._answer("qa-cp4-2") == "9 days"

    def test_relative_rates(self):
        # B takes x; A takes x/2; 2/x + 1/x = 1/8 -> x = 24
        x = 24
        assert round(2 / x + 1 / x, 10) == round(1 / 8, 10)
        assert self._answer("qa-cp4-3") == "24 days"


class TestTopicWiring:
    def test_aptitude_is_in_the_catalogue(self):
        import json
        videos = json.load(open("data/videos.json"))
        qa = next((v for v in videos if v["id"] == "qa"), None)
        assert qa is not None, "qa missing from videos.json"
        assert qa["video_id"], "qa has no video, so its page renders an empty player"

    def test_aptitude_has_its_own_cheat_sheet(self):
        """Without one it falls back to generic filler naming the topic."""
        assert "qa" in STATIC_CHEAT_SHEETS

    def test_aptitude_is_in_the_skill_tree(self):
        """The dashboard tree is a hardcoded list; a topic absent from it is
        invisible there even though it appears in the course list."""
        source = open("app.py").read()
        assert '_node("qa"' in source


class TestCatalogueMatchesTheCurriculum:
    def test_each_topic_video_is_one_of_its_submodule_videos(self):
        # The catalogue's video_id is what quiz generation retrieves a
        # transcript for. Operating Systems kept a replaced lecture (a history
        # of Multics and MS-DOS) here after its submodules moved on, so its
        # quizzes were grounded in content the learner was never shown.
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "data", "videos.json")
        with open(path) as fh:
            catalogue = json.load(fh)
        for topic in catalogue:
            modules = SUBMODULE_DEFINITIONS.get(topic["id"])
            if not modules:
                continue
            served = {m.get("video_id") for m in modules}
            assert topic.get("video_id") in served, (
                f"{topic['id']}: catalogue video {topic.get('video_id')} is not "
                f"one the learner watches ({sorted(served)})")

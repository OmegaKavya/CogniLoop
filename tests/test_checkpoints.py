"""
Tests for in-video checkpoint questions.

Checkpoints are formative: the learner sees the verdict immediately and nothing
is posted back, so they do not feed mastery estimation. Their only job is to
force retrieval. That job fails if the answer can be found without reading the
question, which is what the authored data allows: every checkpoint lists its
correct answer first, so "always click the first option" scores full marks.
"""
import collections

from app import build_topic_submodules, shuffle_checkpoint_options
from utils.constants import SUBMODULE_DEFINITIONS


def all_checkpoints():
    for topic_id, modules in SUBMODULE_DEFINITIONS.items():
        for module in modules:
            for checkpoint in module["checkpoints"]:
                yield topic_id, module, checkpoint


class TestAuthoredCheckpointData:
    def test_every_checkpoint_is_well_formed(self):
        for topic_id, module, cp in all_checkpoints():
            where = f"{topic_id}/{cp['id']}"
            assert cp.get("question"), where
            assert cp.get("explanation"), where
            assert len(cp["options"]) == 4, where
            assert len(set(cp["options"])) == 4, f"{where} has duplicate options"
            assert 0 <= cp["correct_index"] < 4, where

    def test_trigger_points_are_ordered_within_a_module(self):
        for topic_id, modules in SUBMODULE_DEFINITIONS.items():
            for module in modules:
                pcts = [cp["trigger_pct"] for cp in module["checkpoints"]]
                assert pcts == sorted(pcts), f"{topic_id}/{module['title']}"
                assert all(0 < p < 100 for p in pcts)

    def test_every_submodule_has_a_video(self):
        for topic_id, modules in SUBMODULE_DEFINITIONS.items():
            for module in modules:
                assert module.get("video_id"), f"{topic_id}/{module['title']}"


class TestOptionShuffling:
    """The authored data always lists the answer first; the rendered data must
    not, or the checkpoint is a clicking exercise rather than a recall one."""

    def test_rendered_answer_positions_are_spread(self):
        positions = collections.Counter()
        for _ in range(60):
            for module in build_topic_submodules({"id": "os", "video_id": "v",
                                                  "title": "Operating Systems"}):
                for cp in module["checkpoints"]:
                    positions[cp["correct_index"]] += 1
        assert len(positions) == 4, f"answer never appears in some slots: {dict(positions)}"
        # No slot should carry anything close to the 100% the authored data had.
        assert max(positions.values()) / sum(positions.values()) < 0.45

    def test_shuffling_preserves_the_correct_answer(self):
        for _ in range(50):
            for module in build_topic_submodules({"id": "cn", "video_id": "v",
                                                  "title": "Computer Networks"}):
                for cp in module["checkpoints"]:
                    authored = next(c for _, _, c in all_checkpoints() if c["id"] == cp["id"])
                    expected = authored["options"][authored["correct_index"]]
                    assert cp["options"][cp["correct_index"]] == expected

    def test_shuffling_does_not_lose_or_add_options(self):
        original = {"id": "x", "options": ["a", "b", "c", "d"], "correct_index": 0}
        for _ in range(25):
            out = shuffle_checkpoint_options([original])[0]
            assert sorted(out["options"]) == ["a", "b", "c", "d"]
            assert out["options"][out["correct_index"]] == "a"

    def test_authored_data_is_not_mutated(self):
        """Shuffling a rendered copy must not reorder the module definition."""
        before = list(SUBMODULE_DEFINITIONS["os"][0]["checkpoints"][0]["options"])
        build_topic_submodules({"id": "os", "video_id": "v", "title": "OS"})
        assert SUBMODULE_DEFINITIONS["os"][0]["checkpoints"][0]["options"] == before

    def test_single_option_checkpoint_is_left_alone(self):
        out = shuffle_checkpoint_options([{"id": "y", "options": ["only"], "correct_index": 0}])[0]
        assert out["options"] == ["only"]
        assert out["correct_index"] == 0


class TestSubmoduleScopeMatchesItsVideo:
    """Two submodules previously promised topics their replacement video does
    not teach, which meant checkpoints tested untaught material."""

    def test_os_synchronisation_module_does_not_claim_deadlock(self):
        module = SUBMODULE_DEFINITIONS["os"][2]
        text = (module["title"] + module["objective"] + module["exam_angle"]).lower()
        assert "deadlock" not in text
        questions = " ".join(c["question"] for c in module["checkpoints"]).lower()
        assert "coffman" not in questions

    def test_cn_application_layer_module_does_not_claim_routing(self):
        module = SUBMODULE_DEFINITIONS["cn"][2]
        text = (module["title"] + module["objective"] + module["exam_angle"]).lower()
        assert "routing" not in text
        questions = " ".join(c["question"] for c in module["checkpoints"]).lower()
        assert "ospf" not in questions

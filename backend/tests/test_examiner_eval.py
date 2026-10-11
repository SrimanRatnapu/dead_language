import asyncio
import csv
import json
from collections import defaultdict

import pytest

from deadlang import config, llm
from deadlang.eval import examiner_eval as ev
from deadlang.llm import BudgetExceeded
from deadlang.specialists import material
from deadlang.specialists.material import QuickExaminer, ThoroughExaminer

LABELS = [("i1", "elephant_ivory"), ("i2", "elephant_ivory"), ("b1", "bone"), ("b2", "bone"),
          ("w1", "wood"), ("a1", "other")]
# what the fake model says per image; thorough runs get two answers (first run, second run)
QUICK = {"i1": "elephant_ivory", "i2": "bone", "b1": "bone", "b2": "elephant_ivory", "w1": "cannot_tell",
         "a1": "other"}
THOROUGH = {"i1": ("elephant_ivory", "elephant_ivory"), "i2": ("elephant_ivory", "bone"),
            "b1": ("bone", "bone"), "b2": ("bone", "bone"), "w1": ("wood", "wood"), "a1": ("other", "other")}


class FakeVision:
    """Stands in for llm.call_vision_json. Answers by object id (the image file name)."""

    def __init__(self, quick=QUICK, thorough=THOROUGH, fail_after=None, error=None):
        self.quick, self.thorough = quick, thorough
        self.fail_after, self.error = fail_after, error
        self.calls = []
        self.seen = defaultdict(int)

    async def __call__(self, **kw):
        self.calls.append(kw)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise self.error
        oid = kw["image_paths"][0].stem
        k = self.seen[kw["model"], oid]
        self.seen[kw["model"], oid] += 1
        answer = self.quick[oid] if kw["model"] == config.MODEL_FAST else self.thorough[oid][k % 2]
        return {"photos": [{"index": 0, "material": answer, "confidence": 0.9,
                            "visible_features": ["a feature"], "best_region": "base"}]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "museum").mkdir(parents=True)
    with (data / "museum" / "museum_labels.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["object_id", "label", "medium", "title", "object_url", "image_path"])
        for oid, label in LABELS:
            (data / "museum" / f"{oid}.jpg").write_bytes(b"x")
            w.writerow([oid, label, "Ivory (SECRET MEDIUM)", "SECRET TITLE", "http://x", f"museum/{oid}.jpg"])
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.json")
    return tmp_path


def run_main(monkeypatch, argv, fake=None, ask=lambda p: "y"):
    fake = fake or FakeVision()
    monkeypatch.setattr(llm, "call_vision_json", fake)
    return asyncio.run(ev.main(argv, ask=ask)), fake


def rows(pairs, mode="quick"):
    return [{"mode": mode, "object_id": f"o{i}", "truth": t, "predicted": p, "confidence": 0.9}
            for i, (t, p) in enumerate(pairs)]


# ---------------- metrics ----------------

def test_metrics_by_hand():
    m = ev.compute_metrics(rows([(t, QUICK[o]) for o, t in LABELS]))
    assert m["n"] == 6
    assert m["decisive"] == 5 and m["correct"] == 3
    assert m["accuracy_on_decisive"] == 0.6
    assert m["cannot_tell_rate"] == 0.167
    assert m["ivory_precision"] == 0.5 and m["ivory_recall"] == 0.5
    assert m["confusion"] == {"elephant_ivory": {"elephant_ivory": 1, "bone": 1},
                              "bone": {"bone": 1, "elephant_ivory": 1},
                              "wood": {"cannot_tell": 1}, "other": {"other": 1}}


def test_metrics_with_nothing_to_divide_by_are_none_not_errors():
    m = ev.compute_metrics(rows([("wood", "cannot_tell"), ("bone", "cannot_tell")]))
    assert m["accuracy_on_decisive"] is None and m["ivory_precision"] is None and m["ivory_recall"] is None
    assert m["cannot_tell_rate"] == 1.0
    empty = ev.compute_metrics([])
    assert empty["n"] == 0 and empty["cannot_tell_rate"] is None and empty["confusion"] == {}


# ---------------- reading the set ----------------

def test_load_items_finds_images_and_reports_missing_ones(world):
    (config.DATA_DIR / "museum" / "w1.jpg").unlink()
    items, missing = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")
    assert [i.object_id for i in items] == ["i1", "i2", "b1", "b2", "a1"] and missing == ["w1"]
    assert items[0].truth == "elephant_ivory" and items[0].path == config.DATA_DIR / "museum" / "i1.jpg"


def test_load_items_accepts_paths_relative_to_the_repo_root(world, tmp_path):
    repo = config.REPO_ROOT
    (repo / "data" / "museum").mkdir(parents=True)
    (repo / "data" / "museum" / "z1.jpg").write_bytes(b"x")
    csv_path = tmp_path / "labels.csv"
    csv_path.write_text("object_id,label,medium,title,object_url,image_path\nz1,bone,,,,data/museum/z1.jpg\n")
    items, missing = ev.load_items(csv_path)
    assert [i.path for i in items] == [repo / "data" / "museum" / "z1.jpg"] and missing == []


def test_select_items_takes_a_spread_across_labels_when_limited(world):
    items, _ = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")
    assert [i.object_id for i in ev.select_items(items, 4)] == ["i1", "b1", "w1", "a1"]
    assert [i.object_id for i in ev.select_items(items, None)] == [i.object_id for i in items]
    assert [i.object_id for i in ev.select_items(items, 5)][-1] == "i2"


# ---------------- running a mode ----------------

async def test_quick_mode_one_call_per_image_with_sharded_case_ids(world, monkeypatch):
    fake = FakeVision()
    monkeypatch.setattr(llm, "call_vision_json", fake)
    monkeypatch.setattr(ev, "SHARD", 4)
    items, _ = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")

    result = await ev.evaluate("quick", QuickExaminer(None), items, done=set(), concurrency=1)

    assert len(fake.calls) == 6 and all(c["model"] == config.MODEL_FAST for c in fake.calls)
    assert [c["case_id"] for c in fake.calls] == ["examiner_eval-quick-0"] * 4 + ["examiner_eval-quick-1"] * 2
    assert all(c["user"] == material.USER_MESSAGE for c in fake.calls)       # only the photo, never the labels
    assert {r["object_id"]: r["predicted"] for r in result.rows} == QUICK
    assert all(r["mode"] == "quick" and r["truth"] for r in result.rows)


async def test_thorough_mode_looks_twice_and_disagreement_is_cannot_tell(world, monkeypatch):
    fake = FakeVision()
    monkeypatch.setattr(llm, "call_vision_json", fake)
    items, _ = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")

    result = await ev.evaluate("thorough", ThoroughExaminer(None), items, done=set(), concurrency=1)

    assert len(fake.calls) == 12 and all(c["model"] == config.MODEL_STRONG for c in fake.calls)
    predicted = {r["object_id"]: r["predicted"] for r in result.rows}
    assert predicted["i2"] == "cannot_tell" and predicted["i1"] == "elephant_ivory"
    m = ev.compute_metrics(result.rows)
    assert (m["accuracy_on_decisive"], m["ivory_precision"], m["ivory_recall"]) == (1.0, 1.0, 0.5)


async def test_images_already_done_are_not_run_again(world, monkeypatch):
    fake = FakeVision()
    monkeypatch.setattr(llm, "call_vision_json", fake)
    items, _ = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")
    result = await ev.evaluate("quick", QuickExaminer(None), items, done={"i1", "i2", "b1"}, concurrency=1)
    assert len(fake.calls) == 3 and sorted(r["object_id"] for r in result.rows) == ["a1", "b2", "w1"]


async def test_budget_stop_keeps_finished_rows_and_calls_nothing_more(world, monkeypatch):
    fake = FakeVision(fail_after=2, error=BudgetExceeded("cap"))
    monkeypatch.setattr(llm, "call_vision_json", fake)
    items, _ = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")
    result = await ev.evaluate("quick", QuickExaminer(None), items, done=set(), concurrency=1)
    assert len(result.rows) == 2 and result.stopped == "budget" and len(fake.calls) == 3


async def test_gives_up_when_every_call_fails(world, monkeypatch):
    fake = FakeVision(fail_after=0, error=RuntimeError("401 bad key"))
    monkeypatch.setattr(llm, "call_vision_json", fake)
    items, _ = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")
    result = await ev.evaluate("quick", QuickExaminer(None), items, done=set(), concurrency=1)
    assert result.rows == [] and result.stopped == "errors" and len(fake.calls) == ev.GIVE_UP_AFTER
    assert "401 bad key" in result.last_error


# ---------------- command line ----------------

def test_full_run_writes_both_modes_in_quick_then_thorough_order(world, monkeypatch, capsys):
    code, fake = run_main(monkeypatch, ["--concurrency", "1"])
    assert code == 0 and len(fake.calls) == 6 + 12
    models = [c["model"] for c in fake.calls]
    assert models == [config.MODEL_FAST] * 6 + [config.MODEL_STRONG] * 12          # cheap mode first
    out = json.loads((config.REPO_ROOT / "results" / "examiner_eval.json").read_text())
    assert out["quick"]["accuracy_on_decisive"] == 0.6 and out["thorough"]["accuracy_on_decisive"] == 1.0
    assert out["quick"]["n"] == out["thorough"]["n"] == 6
    assert out["meta"]["images_in_set"] == 6 and out["meta"]["labels"] == {
        "elephant_ivory": 2, "bone": 2, "wood": 1, "other": 1}
    # one row per photo and mode (6 + 6); the 18 API calls are higher because thorough looks twice
    assert len((config.REPO_ROOT / "results" / "examiner_eval_rows.jsonl").read_text().splitlines()) == 12
    printed = capsys.readouterr().out
    assert "18 real API calls" in printed and "quick" in printed and "thorough" in printed


def test_declining_makes_no_calls_and_writes_nothing(world, monkeypatch, capsys):
    code, fake = run_main(monkeypatch, [], ask=lambda p: "n")
    assert code == 1 and fake.calls == [] and not (config.REPO_ROOT / "results").exists()
    assert "No calls were made" in capsys.readouterr().out


def test_dry_run_prints_the_estimate_for_both_modes_and_stops(world, monkeypatch, capsys):
    def never(prompt):
        raise AssertionError("dry run must not ask")

    code, fake = run_main(monkeypatch, ["--dry-run"], ask=never)
    out = capsys.readouterr().out
    assert code == 0 and fake.calls == [] and "18 real API calls" in out and "Estimated" in out


def test_yes_flag_skips_the_question(world, monkeypatch):
    def never(prompt):
        raise AssertionError("--yes must not ask")

    code, fake = run_main(monkeypatch, ["--yes", "--modes", "quick"], ask=never)
    assert code == 0 and len(fake.calls) == 6
    out = json.loads((config.REPO_ROOT / "results" / "examiner_eval.json").read_text())
    assert "quick" in out and "thorough" not in out


def test_limit_runs_a_spread_of_images(world, monkeypatch):
    code, fake = run_main(monkeypatch, ["--yes", "--modes", "quick", "--limit", "4"])
    assert code == 0 and sorted(c["image_paths"][0].stem for c in fake.calls) == ["a1", "b1", "i1", "w1"]


def test_rerun_after_a_stop_only_runs_the_missing_images(world, monkeypatch):
    stop = FakeVision(fail_after=2, error=BudgetExceeded("cap"))
    code, _ = run_main(monkeypatch, ["--yes", "--modes", "quick", "--concurrency", "1"], fake=stop)
    assert code == 2
    partial = json.loads((config.REPO_ROOT / "results" / "examiner_eval.json").read_text())
    assert partial["quick"]["n"] == 2                                  # saved what finished

    code, fake = run_main(monkeypatch, ["--yes", "--modes", "quick"])
    assert code == 0 and len(fake.calls) == 4                          # the 2 finished images are not repeated
    assert json.loads((config.REPO_ROOT / "results" / "examiner_eval.json").read_text())["quick"]["n"] == 6


def test_everything_already_done_makes_no_calls(world, monkeypatch, capsys):
    run_main(monkeypatch, ["--yes", "--modes", "quick"])
    code, fake = run_main(monkeypatch, ["--modes", "quick"], ask=lambda p: pytest.fail("asked"))
    assert code == 0 and fake.calls == [] and "Nothing to run" in capsys.readouterr().out


def test_missing_label_file_is_a_clear_message(world, monkeypatch, capsys):
    (config.DATA_DIR / "museum" / "museum_labels.csv").unlink()
    code, fake = run_main(monkeypatch, [])
    assert code == 2 and fake.calls == [] and "museum_labels.csv" in capsys.readouterr().out


def test_unknown_mode_is_rejected_before_anything_runs(world, monkeypatch, capsys):
    code, fake = run_main(monkeypatch, ["--modes", "quick,medium"])
    assert code == 2 and fake.calls == [] and "medium" in capsys.readouterr().out


def test_images_missing_from_disk_are_reported_in_the_output(world, monkeypatch):
    (config.DATA_DIR / "museum" / "w1.jpg").unlink()
    code, fake = run_main(monkeypatch, ["--yes", "--modes", "quick"])
    out = json.loads((config.REPO_ROOT / "results" / "examiner_eval.json").read_text())
    assert code == 0 and len(fake.calls) == 5
    assert out["meta"]["missing_images"] == ["w1"] and out["quick"]["n"] == 5


# ---------------- diagnostics: rows keep the model's reasons and, for thorough, each look ----------------

async def test_rows_keep_the_visible_features_and_best_region(world, monkeypatch):
    monkeypatch.setattr(llm, "call_vision_json", FakeVision())
    items, _ = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")

    result = await ev.evaluate("quick", QuickExaminer(None), items, done=set(), concurrency=1)

    for row in result.rows:
        assert row["visible_features"] == ["a feature"] and row["best_region"] == "base"
        assert row["looks"] is None                       # quick makes a single look; nothing extra to record
    assert {"mode", "object_id", "truth", "predicted", "confidence"} <= set(result.rows[0])


async def test_thorough_rows_record_what_each_look_said(world, monkeypatch):
    monkeypatch.setattr(llm, "call_vision_json", FakeVision())
    items, _ = ev.load_items(config.DATA_DIR / "museum" / "museum_labels.csv")

    result = await ev.evaluate("thorough", ThoroughExaminer(None), items, done=set(), concurrency=1)

    by_id = {r["object_id"]: r for r in result.rows}
    assert by_id["i2"]["predicted"] == "cannot_tell"          # the looks disagreed...
    assert [look["material"] for look in by_id["i2"]["looks"]] == ["elephant_ivory", "bone"]   # ...and now we can see how
    assert [look["material"] for look in by_id["i1"]["looks"]] == ["elephant_ivory", "elephant_ivory"]
    assert all({"material", "confidence"} == set(look) for look in by_id["i1"]["looks"])


def test_the_saved_rows_file_contains_the_new_fields(world, monkeypatch):
    code, _ = run_main(monkeypatch, ["--yes", "--modes", "thorough"])
    saved = [json.loads(line) for line in (config.REPO_ROOT / "results" / "examiner_eval_rows.jsonl").read_text().splitlines()]
    assert code == 0 and len(saved) == 6
    assert all("visible_features" in r and "best_region" in r and len(r["looks"]) == 2 for r in saved)
    metrics = json.loads((config.REPO_ROOT / "results" / "examiner_eval.json").read_text())
    assert metrics["thorough"]["accuracy_on_decisive"] == 1.0          # the numbers themselves are unchanged

# Experiment: Laya as the tag Step's tie-break

Reproduces [docs/experiments/laya-tagging-tiebreak.md](../../docs/experiments/laya-tagging-tiebreak.md). Nothing here
is imported by `ytbrain`, the plugins or the tests. Everything it writes goes to `data/experiments/laya/`
(git-ignored): the sample holds your Library's text.

Needs a tagged Library (`ytbrain tag` has run, so the tie-break answers are cached) and judge models reachable through
your `.env` (`YTBRAIN_EVAL_JUDGES`). Run from the repo root, in the repo's environment:

```bash
python experiments/laya/sample.py               # 2,400 close calls + 400 single-candidate items; embedding and deepseek arms; spends nothing
python experiments/laya/jury.py                 # three blind judges label every item; resumable, --max-cost 3
python experiments/laya/fetch_model.py          # Laya's code and configs only, at the pinned revision: read them first
python experiments/laya/fetch_model.py --weights   # then the English checkpoint (843 MB)
python experiments/laya/laya_run.py             # both Laya arms, offline (MPS, CUDA or CPU); refuses files that differ from the reviewed hashes
python experiments/laya/score.py                # REPORT.md with the verdict, by rules fixed in score.py before the run
```

`score.py` also writes `disputed.md`: up to 50 items the judges split on, with their text, for a hand check of the
panel. Both stay in `data/`.

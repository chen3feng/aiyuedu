#!/usr/bin/env python3
"""复现欧路词典（dict.eudic.net）词汇量测试的算法。

本文件是对 ``https://dict.eudic.net/areas/exam/en/`` 的黑盒复现，不包含欧路
的任何源代码。算法通过抓取前端 bundle、观察 ``startvocabtest`` / ``CalcVocab``
接口的行为反推得到，核心是一个 Elo/IRT 式的自适应估计器：

    p = sigmoid((V - (1000 * level + 100)) / 2500)
    K = 2000 / (1 + n / 14) ** 1.5

    correct : V += K * (1 - p)
    wrong   : V -= K * p
    unknown : V -= 0.625 * K * p

其中 V 就是最终展示的「词汇量」，level 是题目的词频档位（每档约 1000 词），
n 是已答题数。参数由 5 组真实接口轨迹拟合得到（整体 RMSE ≈ 90 分，留出集
RMSE ≈ 128 分），并四舍五入到一组很可能是服务端真实常数的整数：

    2500 / 1000 / 100 / 2000 / 14 / 1.5 / 0.625

题目形式也与线上一致：3 个中文释义 + 「以上都不对」+「不认识」。正确答案
在 0~3 之间近似均匀分布——即约 75% 的题会放入正确释义，25% 的题三个释义
全错、正确答案是「以上都不对」。

用法::

    # 交互式测试（终端答题）
    python scripts/eudic_vocab_repro.py --interactive

    # 模拟一个「认识 0~8 档、9 档以上不认识」的用户
    python scripts/eudic_vocab_repro.py --simulate 8

    # 用抓到的真实接口轨迹校验分数更新公式
    python scripts/eudic_vocab_repro.py --validate

只依赖标准库；词库读取仓库内的 ``data/wordlists/wordlist.csv``。
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 算法常数（由黑盒轨迹拟合，四舍五入到整数）
# ---------------------------------------------------------------------------
LEVEL_WIDTH = 1000          # 每个词频档约 1000 词
LEVEL_OFFSET = 100          # 档位难度偏移
SCALE = 2500                # logistic 斜率（分）
K0 = 2000                   # 初始步长（分）
TAU = 14                    # 步长衰减时间常数
GAIN_EXP = 1.5              # 步长衰减指数
UNKNOWN_FACTOR = 0.625      # 「不认识」相对「答错」的负向权重
MIN_DELTA = 0.01            # 置信区间相对宽度下限
MAX_LEVEL = 24              # wordlist.csv 覆盖 0~24 档（每档约 1000 词）
MAX_SCORE = 25000           # 词库上限
CORRECT_PRESENT_RATE = 0.75 # 正确释义出现在 3 个选项中的概率
MIN_QUESTIONS = 20          # 线上「最少测满 20 题才能查看结果」

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORDLIST = ROOT / "data" / "wordlists" / "wordlist.csv"


def sigmoid(x: float) -> float:
    x = max(-50.0, min(50.0, x))
    return 1.0 / (1.0 + math.exp(-x))


# ---------------------------------------------------------------------------
# 词库与题目生成
# ---------------------------------------------------------------------------
def gloss(translation: str) -> str:
    """把 ECDICT 的 translation 压成适合做选项的短释义。

    例: "n. 公司, 友伴, 交往, 连队, 朋友, 一群；vt. 陪伴" -> "n. 公司，友伴，交往"
    """
    if not translation:
        return ""
    text = translation.replace("\\n", "\n")
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("[网络]"):
            continue
        # 去掉领域标签
        for left, right in (("[", "]"), ("【", "】")):
            while left in line and right in line:
                a = line.find(left)
                b = line.find(right, a)
                if b < 0:
                    break
                line = line[:a] + line[b + 1:]
        group = line.split("；")[0].split(";")[0].strip()
        if not group:
            continue
        pos = ""
        body = group
        if "." in group[:8]:
            head, rest = group.split(".", 1)
            if head.strip().lower() in {
                "n", "v", "vt", "vi", "adj", "adv", "a", "ad", "prep",
                "pron", "conj", "num", "art", "int", "aux", "abbr", "pl",
            }:
                pos = head.strip().lower() + "."
                body = rest
        senses = [s.strip() for s in body.replace("，", ",").split(",") if s.strip()]
        out = (pos + " " if pos else "") + "，".join(senses[:3])
        out = out.strip()
        if len(out) > 32:
            out = out[:32].rstrip("，,;； ") + "…"
        return out
    return ""


@dataclass(frozen=True)
class Word:
    lemma: str
    rank: int
    level: int
    gloss: str
    pos: str
    tags: frozenset[str]


class WordBank:
    """按词频档位组织的词库。"""

    def __init__(self, path: Path = DEFAULT_WORDLIST):
        self.by_level: dict[int, list[Word]] = {i: [] for i in range(MAX_LEVEL + 1)}
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    rank = int(row.get("rank") or 0)
                except ValueError:
                    continue
                lemma = (row.get("lemma") or "").strip()
                if rank <= 0 or not lemma or not lemma.isascii():
                    continue
                g = gloss(row.get("translation") or "")
                if not g:
                    continue
                level = min(MAX_LEVEL, (rank - 1) // LEVEL_WIDTH)
                pos = g.split(" ", 1)[0] if " " in g else ""
                tags = frozenset((row.get("tag") or "").split())
                self.by_level[level].append(Word(lemma, rank, level, g, pos, tags))
        self._all = [w for ws in self.by_level.values() for w in ws]
        if not self._all:
            raise SystemExit(f"词库为空或格式不符: {path}")

    def pick(self, level: int, rng: random.Random, avoid: set[str]) -> Word:
        pool = self.by_level[max(0, min(MAX_LEVEL, level))] or self._all
        for _ in range(40):
            w = rng.choice(pool)
            if w.lemma not in avoid:
                return w
        return rng.choice(pool)

    def distractors(self, target: Word, n: int, rng: random.Random) -> list[str]:
        """取 n 个干扰释义：优先同档、同词性，避免与正确释义互相包含。"""
        pools = [self.by_level[target.level]]
        for d in (1, -1, 2, -2):
            lv = target.level + d
            if 0 <= lv <= MAX_LEVEL:
                pools.append(self.by_level[lv])
        pools.append(self._all)

        chosen: list[str] = []
        seen = {target.gloss}
        for pool in pools:
            # 同词性的候选优先
            same_pos = [w for w in pool if w.pos == target.pos and w.gloss not in seen]
            mixed = [w for w in pool if w.gloss not in seen]
            for candidates in (same_pos, mixed):
                rng.shuffle(candidates)
                for w in candidates:
                    if len(chosen) >= n:
                        break
                    g = w.gloss
                    if not g or g in seen:
                        continue
                    if g in target.gloss or target.gloss in g:
                        continue
                    seen.add(g)
                    chosen.append(g)
            if len(chosen) >= n:
                break
        while len(chosen) < n:
            g = rng.choice(self._all).gloss
            if g not in seen:
                seen.add(g)
                chosen.append(g)
        return chosen[:n]


@dataclass
class Question:
    word: Word
    options: list[str]
    correct_index: int

    @property
    def level(self) -> int:
        return self.word.level


def make_question(bank: WordBank, level: int, rng: random.Random,
                  avoid: set[str]) -> Question:
    """生成一道与线上同构的题：3 个释义 + 以上都不对 + 不认识。"""
    word = bank.pick(level, rng, avoid)
    include_correct = rng.random() < CORRECT_PRESENT_RATE
    n_distractors = 2 if include_correct else 3
    glosses = bank.distractors(word, n_distractors, rng)
    if include_correct:
        glosses.append(word.gloss)
    rng.shuffle(glosses)
    options = glosses + ["以上都不对", "不认识"]
    correct_index = glosses.index(word.gloss) if include_correct else 3
    return Question(word, options, correct_index)


# ---------------------------------------------------------------------------
# 自适应测试
# ---------------------------------------------------------------------------
@dataclass
class EudicVocabTest:
    """一次词汇量测试。

    ``score`` 就是最终词汇量；``interval`` 是线上 ``score_interval`` 的复现；
    ``delta`` 是 ``[-(score-lower)/score, 0.0]``。
    """

    bank: WordBank
    seed: Optional[int] = None
    max_level: int = MAX_LEVEL
    max_questions: Optional[int] = None   # None = 可无限继续（线上行为）

    rng: random.Random = field(init=False)
    score: float = 0.0
    n: int = 0
    n_eff: float = 0.0
    streak: int = 0
    probe_remaining: int = 0
    probe_level: int = 0
    probes_used: int = 0
    last_probe_failed: bool = False
    last_probe_end_n: int = 0
    current: Optional[Question] = None
    recent: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    correct: int = 0
    wrong: int = 0
    unknown: int = 0
    _answered: list[tuple[Word, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.current = self._make_next()

    # -- 难度选择 ---------------------------------------------------------
    def _base_level(self) -> int:
        # 线上基本是 round(score / 1000)，偶尔向下偏一档
        return max(0, min(self.max_level, int(round(self.score / LEVEL_WIDTH))))

    def _select_level(self) -> int:
        if self.n == 0:
            # 线上第一题固定在 3~4 档
            return 3 + self.rng.choice([0, 1])
        if self.probe_remaining > 0:
            return self.probe_level
        can_probe = self.probes_used == 0 or (
            self.probes_used == 1
            and self.last_probe_failed
            and self.n - self.last_probe_end_n <= 6
        )
        if self.streak >= 4 and can_probe and self.probes_used < 2:
            # 连续答对 4 题后开始「探顶」：跳到当前档位上方 3~4 档。
            # 探顶最多 6 题；失败后 6 题内允许再探一次（与线上轨迹一致）。
            self.probe_remaining = 6
            self.probe_level = min(
                self.max_level,
                self._base_level() + 3 + self.rng.choice([0, 1]),
            )
            return self.probe_level
        offset = self.rng.choices([-1, 0, 1], weights=[0.25, 0.60, 0.15])[0]
        return max(0, min(self.max_level, self._base_level() + offset))

    def _make_next(self) -> Question:
        level = self._select_level()
        q = make_question(self.bank, level, self.rng, set(self.recent[-20:]))
        self.recent.append(q.word.lemma)
        if len(self.recent) > 40:
            self.recent = self.recent[-40:]
        return q

    # -- 分数更新 ---------------------------------------------------------
    def _update_score(self, question: Question, outcome: str) -> None:
        n = self.n + 1
        difficulty = LEVEL_WIDTH * question.level + LEVEL_OFFSET
        p = sigmoid((self.score - difficulty) / SCALE)
        gain = K0 / (1.0 + n / TAU) ** GAIN_EXP
        if outcome == "correct":
            self.score += gain * (1.0 - p)
        elif outcome == "unknown":
            self.score -= UNKNOWN_FACTOR * gain * p
        else:
            self.score -= gain * p
        self.score = max(0.0, min(float(MAX_SCORE), self.score))
        self.n = n

    def _update_uncertainty(self, outcome: str) -> float:
        if outcome == "correct":
            self.n_eff = 1.0 if self.n_eff == 0.0 else self.n_eff + 0.5
        else:
            self.n_eff = max(1.0, self.n_eff * 0.5)
        return min(1.0, max(MIN_DELTA, 0.8 / (2.0 * self.n_eff)))

    # -- 对外接口 ---------------------------------------------------------
    def submit(self, choice: Optional[int], unknown: bool = False) -> dict:
        """提交答案，返回本题反馈与下一题。"""
        if self.current is None:
            raise RuntimeError("测试已结束")
        q = self.current
        if unknown:
            outcome = "unknown"
            self.unknown += 1
        elif choice == q.correct_index:
            outcome = "correct"
            self.correct += 1
        else:
            outcome = "wrong"
            self.wrong += 1

        # 探顶阶段：答对继续抬升，答错/不认识立即退出
        probe_ended = False
        probe_failed = False
        if self.probe_remaining > 0:
            if outcome == "correct":
                self.probe_level = min(
                    self.max_level,
                    self.probe_level + self.rng.choice([1, 1, 2]),
                )
                self.probe_remaining -= 1
                if self.probe_remaining == 0:
                    probe_ended = True
            else:
                self.probe_remaining = 0
                probe_ended = True
                probe_failed = True

        self.streak = self.streak + 1 if outcome == "correct" else 0
        self._update_score(q, outcome)
        if probe_ended:
            self.probes_used += 1
            self.last_probe_failed = probe_failed
            self.last_probe_end_n = self.n
        delta = self._update_uncertainty(outcome)
        p_know = sigmoid((self.score - (LEVEL_WIDTH * q.level + LEVEL_OFFSET)) / SCALE)
        self._answered.append((q.word, p_know))

        lower = self.score * (1.0 - delta)
        feedback = {
            "outcome": outcome,
            "correct_index": q.correct_index,
            "correct_gloss": q.word.gloss,
            "word": q.word.lemma,
        }
        progress = {
            "score": int(round(self.score)),
            "level": self._base_level(),
            "total": self.n,
            "correct": self.correct,
            "wrong": self.wrong,
            "unknown": self.unknown,
            "delta": [-round(delta, 4), 0.0],
            "score_interval": [int(round(lower)), int(round(self.score))],
            "finished": self.max_questions is not None and self.n >= self.max_questions,
        }
        if progress["finished"]:
            self.current = None
            return {"feedback": feedback, **progress, "result": self.result()}

        self.current = self._make_next()
        return {
            "feedback": feedback,
            **progress,
            "question": {
                "word": self.current.word.lemma,
                "level": self.current.level,
                "options": self.current.options,
            },
        }

    def result(self) -> dict:
        return {
            "vocab_size": int(round(self.score / 10) * 10),
            "score": int(round(self.score)),
            "total": self.n,
            "correct": self.correct,
            "wrong": self.wrong,
            "unknown": self.unknown,
            "ready": self.n >= MIN_QUESTIONS,   # 线上最少 20 题才展示结果
            "coverage": self.coverage(),
        }

    def coverage(self) -> dict[str, float]:
        """按 ECDICT tag 估算各词表认识率（线上还有 3 个自建词表，未复现）。

        线上覆盖率是模型估计值，不是「已答题里的正确率」。这里对每个词表抽样，
        用最终词汇量 V 和词频档位 L 计算 ``sigmoid((V - (1000L+100))/2500)`` 的均值。
        """
        mapping = {
            "小学英语": "zk",
            "英语四级": "cet4",
            "英语六级": "cet6",
            "研究生英语": "ky",
            "雅思词汇": "ielts",
            "托福词汇": "toefl",
            "GRE词汇": "gre",
        }
        out: dict[str, float] = {}
        for name, tag in mapping.items():
            words = [w for w in self.bank._all if tag in w.tags]
            if not words:
                continue
            sample = words if len(words) <= 300 else self.rng.sample(words, 300)
            vals = [
                sigmoid((self.score - (LEVEL_WIDTH * w.level + LEVEL_OFFSET)) / SCALE)
                for w in sample
            ]
            out[name] = round(sum(vals) / len(vals), 3)
        return out


# ---------------------------------------------------------------------------
# 校验：用真实接口轨迹回放分数更新公式
# ---------------------------------------------------------------------------
# (level, outcome, 真实 score)；outcome: 1=正确, 0=错误, 2=不认识
VALIDATION_SMART = [
    (3, 1, 1166), (1, 1, 1995), (2, 0, 1338), (1, 1, 1938), (1, 1, 2517),
    (2, 1, 3080), (2, 1, 3581), (8, 1, 4454), (9, 1, 5269), (10, 1, 6047),
    (10, 1, 6774), (12, 1, 7497), (13, 1, 8191), (8, 1, 8567), (8, 1, 8936),
    (9, 0, 8637), (8, 1, 8915), (9, 1, 9206), (9, 1, 9470), (9, 1, 9694),
    (9, 1, 9879), (9, 1, 10072), (10, 1, 10263), (9, 1, 10436), (10, 0, 10261),
    (10, 1, 10443), (10, 1, 10620), (10, 1, 10802), (10, 1, 10974), (11, 1, 11143),
    (11, 1, 11311), (11, 1, 11486), (11, 1, 11659), (11, 1, 11812), (11, 1, 11956),
    (11, 1, 12104), (12, 1, 12255), (11, 1, 12392), (12, 1, 12534), (12, 0, 12385),
    (12, 1, 12533), (12, 1, 12669), (12, 1, 12795), (13, 0, 12670), (12, 0, 12538),
    (12, 1, 12659), (12, 1, 12784), (13, 1, 12918), (13, 0, 12806), (12, 1, 12923),
]

VALIDATION_K10 = [
    (4, 1, 1258), (1, 1, 2010), (2, 1, 2744), (3, 1, 3454), (7, 1, 4518),
    (10, 1, 5595), (9, 1, 6549), (11, 2, 6428), (6, 1, 6967), (6, 1, 7379),
    (7, 1, 7854), (8, 1, 8308), (12, 2, 8190), (8, 1, 8561), (8, 1, 8906),
    (8, 1, 9203), (8, 1, 9483), (9, 1, 9749), (10, 1, 10028), (9, 1, 10245),
    (10, 0, 10054), (9, 1, 10240), (10, 1, 10421), (10, 1, 10602), (10, 1, 10791),
    (10, 1, 10976), (10, 1, 11143), (11, 2, 10975), (11, 2, 10809), (11, 2, 10653),
]


def replay(trace: list[tuple[int, int, int]]) -> tuple[float, list[int]]:
    """只回放分数更新（难度选择用真实 level），返回 RMSE 与预测序列。"""
    score = 0.0
    preds: list[int] = []
    for n, (level, outcome, _expected) in enumerate(trace, start=1):
        p = sigmoid((score - (LEVEL_WIDTH * level + LEVEL_OFFSET)) / SCALE)
        gain = K0 / (1.0 + n / TAU) ** GAIN_EXP
        if outcome == 1:
            score += gain * (1.0 - p)
        elif outcome == 2:
            score -= UNKNOWN_FACTOR * gain * p
        else:
            score -= gain * p
        score = max(0.0, min(float(MAX_SCORE), score))
        preds.append(int(round(score)))
    expected = [e for _, _, e in trace]
    rmse = math.sqrt(sum((a - b) ** 2 for a, b in zip(preds, expected)) / len(expected))
    return rmse, preds


def validate() -> None:
    for name, trace in (("smart(50 题, 高正确率)", VALIDATION_SMART),
                        ("K10(30 题, 认识 0~10 档)", VALIDATION_K10)):
        rmse, preds = replay(trace)
        print(f"{name}: RMSE={rmse:.1f}  最终真实={trace[-1][2]}  复现={preds[-1]}")
        for i in range(0, len(trace), max(1, len(trace) // 6)):
            print(f"  n={i + 1:2d} 真实={trace[i][2]:5d} 复现={preds[i]:5d}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def run_interactive(bank: WordBank, seed: Optional[int]) -> None:
    test = EudicVocabTest(bank, seed=seed)
    print("欧路词汇量测试复现（输入 1-5 选项编号，q 退出）")
    while test.current is not None:
        q = test.current
        print(f"\n第 {test.n + 1} 题  [档位 {q.level}]  {q.word.lemma}")
        for i, opt in enumerate(q.options, start=1):
            print(f"  {i}. {opt}")
        raw = input("> ").strip().lower()
        if raw in {"q", "quit", "exit"}:
            break
        if not raw.isdigit() or not (1 <= int(raw) <= len(q.options)):
            print("请输入 1-5")
            continue
        choice = int(raw) - 1
        res = test.submit(choice=None if choice == 4 else choice, unknown=choice == 4)
        fb = res["feedback"]
        mark = {"correct": "✓", "wrong": "✗", "unknown": "—"}[fb["outcome"]]
        print(f"{mark} 正确答案：{fb['correct_gloss']}")
        print(f"当前词汇量：{res['score']}  区间：{res['score_interval']}")
        if res.get("result"):
            print("\n最终结果：", res["result"])
    if test.n >= MIN_QUESTIONS:
        print("\n最终结果：", test.result())
    elif test.n:
        print(f"\n已答 {test.n} 题；线上至少答满 {MIN_QUESTIONS} 题才展示结果。")


def run_simulation(bank: WordBank, ability_level: int, questions: int,
                   seed: Optional[int]) -> None:
    """模拟一个「认识 <= ability_level 档、以上不认识」的用户。"""
    test = EudicVocabTest(bank, seed=seed)
    print(f"模拟用户：认识 0~{ability_level} 档，{ability_level + 1} 档以上点「不认识」")
    while test.current is not None and test.n < questions:
        q = test.current
        unknown = q.level > ability_level
        # 认识的词：有 75% 概率选对（模拟真实用户的正确率）
        if unknown:
            choice = None
        elif test.rng.random() < 0.85:
            choice = q.correct_index
        else:
            choice = next(i for i in range(4) if i != q.correct_index)
        res = test.submit(choice=choice, unknown=unknown)
        if test.n % 5 == 0 or res.get("result"):
            print(f"n={test.n:2d} 档位={q.level:2d} 词汇量={res['score']:5d} "
                  f"区间={res['score_interval']} 正/错/不认识="
                  f"{res['correct']}/{res['wrong']}/{res['unknown']}")
    print("\n最终结果：", test.result())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="复现欧路词典词汇量测试算法")
    parser.add_argument("--wordlist", type=Path, default=DEFAULT_WORDLIST)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--interactive", action="store_true", help="终端交互答题")
    parser.add_argument("--simulate", type=int, metavar="LEVEL",
                        help="模拟认识 0~LEVEL 档的用户")
    parser.add_argument("--questions", type=int, default=50, help="模拟题量")
    parser.add_argument("--validate", action="store_true",
                        help="用真实接口轨迹校验分数公式")
    args = parser.parse_args(argv)

    if args.validate:
        validate()
        return 0
    bank = WordBank(args.wordlist)
    if args.interactive:
        run_interactive(bank, args.seed)
    elif args.simulate is not None:
        run_simulation(bank, args.simulate, args.questions, args.seed)
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

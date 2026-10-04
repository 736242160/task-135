#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""couplet_check.py — 对联校验工具（纯 Python 标准库，单文件）

用法：
    python3 couplet_check.py 输入文件          # 校验并打印报告
    python3 couplet_check.py - < 输入文件      # 从标准输入读取
    退出码：0 = 全部通过；1 = 存在错误（含解析错误）

输入格式（一个文本文件，分两个小节，# 开头为注释，空行忽略）：

    @rules                      # 平仄规则小节（也可用 @规则）
    春 平 名                    # 每行：字 声调 [词性]
    看 两可 动                  # 声调：平 / 仄 / 两可（或写作 平仄、仄平）
    @couplets                   # 对联流小节（也可用 @对联）
    春风吹柳绿 | 暮雨润花红     # 每行一联：上联 | 下联（字间可有空格，自动忽略）

自定规则及理由（重要，先读）：
 1. 平仄相对：上下联同位置必须一平一仄。严格校验每一位（不采用"一三五不论"，
    因为题目要求逐位校验）；多音字标"两可"时，只要存在一种读法能使该位
    平仄相对即判通过——理由：多音字在联中可按需取音，取最宽松解释不误伤。
 2. 词性对仗：词性分为 名/动/形/数/量/代/副/介/连/助/叹 十一类，要求同类
    相对（工对）；唯一宽对兼容组为 {数, 量}——理由：古汉语数量词常连用
    对仗（"两个黄鹂"对"一行白鹭"），视为合格但给出提示。词性为可选项：
    整联无词性信息则跳过词性校验（给提示）；部分缺失则逐位给警告。
 3. 重字：上下联同一位置出现同一个字为"同位重字"，是联家大忌，记错误；
    一联之内某字重复出现且未与对句形成"规则重字"（对句同位置同样重复），
    记警告——理由：规则重字（如"风声雨声"对"山色水色"式的错位不在此例，
    经典联律允许对句同位同步重复）是合法修辞，不规则重字才是病。
 4. 末字声调：上联末字宜仄、下联末字宜平，违反记警告——理由：这是通行
    联律但非绝对，故降级为警告。
 5. 未定义字：联中引用了规则表里没有的字，逐字记错误。
 6. 空联：上下联均为空、或任一侧为空，记错误；整条对联流为空也记错误。
 7. 跨联状态延续：校验器实例在整条对联流上持续工作——规则表全程有效，
    错误/警告计数逐联累积，并记录所有被使用过的字，最后汇总报告"规则中
    定义但从未被任何联使用的字"（提示级），便于发现规则表与联文脱节。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

PING, ZE = "平", "仄"
POLY_TOKENS = {"两可", "平仄", "仄平"}
VALID_TONES = {PING, ZE}

POS_CATEGORIES = {"名", "动", "形", "数", "量", "代", "副", "介", "连", "助", "叹"}
POS_COMPAT_GROUPS = [frozenset({"数", "量"})]  # 宽对兼容组

ERROR, WARNING, INFO = "错误", "警告", "提示"


@dataclass
class Issue:
    severity: str
    kind: str
    message: str
    couplet_no: int | None = None
    position: int | None = None


@dataclass
class CharRule:
    tones: frozenset  # {'平'}、{'仄'} 或 {'平','仄'}（两可）
    pos: str | None
    line_no: int


def tone_str(tones: frozenset) -> str:
    return "平仄两可" if len(tones) > 1 else next(iter(tones))


def tones_opposite(upper: frozenset, lower: frozenset) -> bool:
    """存在一种读法使上下联平仄相对即通过（多音字取最宽松解释）。"""
    return any(u != l for u in upper for l in lower)


def pos_match(a: str, b: str) -> bool:
    if a == b:
        return True
    return any(a in g and b in g for g in POS_COMPAT_GROUPS)


# ---------------------------------------------------------------- 输入解析

def parse_input(text: str):
    rules: dict[str, CharRule] = {}
    couplets: list[tuple[str, str, int]] = []
    issues: list[Issue] = []
    section = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            tag = line[1:].strip()
            if tag in ("rules", "规则", "平仄规则"):
                section = "rules"
            elif tag in ("couplets", "对联", "对联流"):
                section = "couplets"
            else:
                issues.append(Issue(ERROR, "格式", f"第{lineno}行：未知小节 '@{tag}'"))
            continue

        if section == "rules":
            parts = line.split()
            if len(parts) < 2:
                issues.append(Issue(ERROR, "格式", f"第{lineno}行：规则至少需要'字 声调'两列，已跳过"))
                continue
            char, tone_token = parts[0], parts[1]
            if len(char) != 1:
                issues.append(Issue(ERROR, "格式", f"第{lineno}行：'{char}'不是单个字，已跳过"))
                continue
            if tone_token in POLY_TOKENS:
                tones = frozenset({PING, ZE})
            elif tone_token in VALID_TONES:
                tones = frozenset({tone_token})
            else:
                issues.append(Issue(ERROR, "格式", f"第{lineno}行：'{char}'的声调'{tone_token}'非法（应为 平/仄/两可），已跳过"))
                continue
            pos = parts[2] if len(parts) >= 3 else None
            if len(parts) > 3:
                issues.append(Issue(WARNING, "格式", f"第{lineno}行：多余列已忽略"))
            if pos is not None and pos not in POS_CATEGORIES:
                issues.append(Issue(WARNING, "格式", f"第{lineno}行：'{char}'的词性'{pos}'不在常用十一类中，仍按原样记录"))
            if char in rules:
                issues.append(Issue(WARNING, "规则冲突", f"第{lineno}行：'{char}'重复定义（首见于第{rules[char].line_no}行），以先出现者为准"))
                continue
            rules[char] = CharRule(tones, pos, lineno)

        elif section == "couplets":
            if "|" not in line:
                issues.append(Issue(ERROR, "格式", f"第{lineno}行：对联缺少'|'分隔符，已跳过"))
                continue
            upper, lower = (seg.replace(" ", "").replace("\t", "") for seg in line.split("|", 1))
            couplets.append((upper, lower, lineno))
        else:
            issues.append(Issue(ERROR, "格式", f"第{lineno}行：内容出现在任何小节之前，已跳过"))

    return rules, couplets, issues


# ---------------------------------------------------------------- 校验器

class CoupletChecker:
    """跨联状态延续：规则表、用字集合、统计计数在整条对联流上持续累积。"""

    def __init__(self, rules: dict[str, CharRule]):
        self.rules = rules
        self.used_chars: set[str] = set()

    def check_couplet(self, no: int, upper: str, lower: str) -> list[Issue]:
        issues: list[Issue] = []

        def add(sev, kind, msg, pos=None):
            issues.append(Issue(sev, kind, msg, couplet_no=no, position=pos))

        # 空联
        if not upper and not lower:
            add(ERROR, "空联", "上下联均为空")
            return issues
        if not upper:
            add(ERROR, "空联", "上联为空")
        if not lower:
            add(ERROR, "空联", "下联为空")

        # 字数相等
        if len(upper) != len(lower):
            add(ERROR, "字数不等", f"上联{len(upper)}字，下联{len(lower)}字")

        # 跨联状态：累积用字
        self.used_chars.update(upper)
        self.used_chars.update(lower)

        n = min(len(upper), len(lower))
        has_pos_info = any(
            self.rules.get(c) and self.rules[c].pos for c in upper + lower
        )

        for i in range(n):
            pos = i + 1
            uc, lc = upper[i], lower[i]
            ur, lr = self.rules.get(uc), self.rules.get(lc)

            # 规则引用不存在的字
            if ur is None:
                add(ERROR, "未定义字", f"上联'{uc}'未在规则中定义平仄", pos)
            if lr is None:
                add(ERROR, "未定义字", f"下联'{lc}'未在规则中定义平仄", pos)

            if ur and lr:
                # 平仄相对
                if not tones_opposite(ur.tones, lr.tones):
                    add(ERROR, "平仄不相对",
                        f"上联'{uc}'为{tone_str(ur.tones)}，下联'{lc}'为{tone_str(lr.tones)}，"
                        f"同为{tone_str(ur.tones)}，应一平一仄", pos)
                # 词性对仗
                if ur.pos and lr.pos:
                    if not pos_match(ur.pos, lr.pos):
                        add(ERROR, "词性不相对",
                            f"上联'{uc}'为{ur.pos}词，下联'{lc}'为{lr.pos}词", pos)
                    elif ur.pos != lr.pos:
                        add(INFO, "宽对",
                            f"'{uc}'({ur.pos})对'{lc}'({lr.pos})，属数量宽对，合格", pos)
                elif ur.pos or lr.pos:
                    missing = uc if not ur.pos else lc
                    add(WARNING, "词性缺失", f"'{missing}'未标注词性，该位词性对仗无法校验", pos)

            # 同位重字
            if uc == lc:
                add(ERROR, "同位重字", f"上下联第{pos}字同为'{uc}'", pos)

        if not has_pos_info:
            add(INFO, "词性校验跳过", "该联所用字均未标注词性，跳过词性对仗校验")

        # 末字声调（警告级）
        if upper:
            r = self.rules.get(upper[-1])
            if r and r.tones == frozenset({PING}):
                add(WARNING, "末字声调", f"上联末字'{upper[-1]}'为平声，宜仄")
        if lower:
            r = self.rules.get(lower[-1])
            if r and r.tones == frozenset({ZE}):
                add(WARNING, "末字声调", f"下联末字'{lower[-1]}'为仄声，宜平")

        # 联内不规则重字（警告级）
        for side, line, other in (("上联", upper, lower), ("下联", lower, upper)):
            positions: dict[str, list[int]] = {}
            for i, c in enumerate(line):
                positions.setdefault(c, []).append(i + 1)
            for c, pos_list in positions.items():
                if len(pos_list) > 1:
                    other_pos = [i + 1 for i, x in enumerate(other) if x == c]
                    if other_pos != pos_list:
                        add(WARNING, "联内重字",
                            f"{side}'{c}'重复出现于第{'、'.join(map(str, pos_list))}字，"
                            f"且未与对句形成规则重字")

        return issues


# ---------------------------------------------------------------- 报告

def render_report(rules, couplets, parse_issues, results, checker) -> tuple[str, bool]:
    lines: list[str] = ["===== 对联校验报告 =====", f"规则：加载 {len(rules)} 条字规则"]
    has_error = False

    if parse_issues:
        lines.append("解析问题：")
        for it in parse_issues:
            lines.append(f"  [{it.severity}] {it.kind}：{it.message}")
            has_error |= it.severity == ERROR
    else:
        lines.append("解析问题：无")

    if not couplets:
        lines.append("  [错误] 空对联流：没有任何可校验的联")
        has_error = True

    total_err = total_warn = passed = 0
    for no, upper, lower, issues in results:
        errs = [i for i in issues if i.severity == ERROR]
        warns = [i for i in issues if i.severity == WARNING]
        total_err += len(errs)
        total_warn += len(warns)
        ok = not errs
        passed += ok
        lines.append("")
        lines.append(f"第 {no} 联：{upper or '(空)'} / {lower or '(空)'} —— {'通过' if ok else '未通过'}")
        for it in issues:
            pos = f"第{it.position}字 " if it.position else ""
            lines.append(f"  [{it.severity}] {pos}{it.kind}：{it.message}")
        has_error |= bool(errs)

    lines.append("")
    lines.append(f"汇总：共 {len(results)} 联，通过 {passed}，未通过 {len(results) - passed}；"
                 f"错误 {total_err} 个，警告 {total_warn} 个")

    unused = sorted(set(rules) - checker.used_chars)
    if unused:
        lines.append(f"提示：以下规则字未被任何联使用（跨联统计）：{'、'.join(unused)}")

    return "\n".join(lines), has_error


# ---------------------------------------------------------------- 入口

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="对联校验工具（平仄/字数/词性/重字）")
    ap.add_argument("input", help="输入文件路径，'-' 表示标准输入")
    args = ap.parse_args(argv)

    try:
        text = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    except OSError as exc:
        print(f"无法读取输入：{exc}", file=sys.stderr)
        return 2

    rules, couplets, parse_issues = parse_input(text)
    checker = CoupletChecker(rules)
    results = [
        (no, upper, lower, checker.check_couplet(no, upper, lower))
        for no, (upper, lower, _lineno) in enumerate(couplets, 1)
    ]
    report, has_error = render_report(rules, couplets, parse_issues, results, checker)
    print(report)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())

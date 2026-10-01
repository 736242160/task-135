#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
couplet_check.py — 对联校验工具（纯 Python 标准库，单文件，开箱即用）

校验内容
========
1. 上下联字数相等；
2. 对应位置平仄相对（该仄用平 / 该平用仄均报错）；
3. 词性对仗（名词对名词等，规则自定，见下）；
4. 重复字位置（同位重字、不规则重字）；
5. 对联引用了规则中不存在的字（未定义声调的字）；
6. 空对联 / 空半联；
7. 同字多音（平仄两可，规则自定，见下）；
8. 跨联状态延续：规则一次载入、对联逐条流式校验，
   联号、错误/警告统计在整个对联流上累计。

输入格式
========
文件分两节（节可反复出现），以节标题开头；空行与 # 开头行为注释：

    [规则]
    春 平 名词
    长 仄 动词
    长 平 形容词        # 同字登记多条声调 => 平仄两可（多音字）

    [对联]
    春风吹柳绿 | 夜雨润花红
    好雨知时节 当春乃发生      # 也支持空白分隔的两列写法

规则行：字 声调(平|仄|两可) [词性]      词性可省略（省略则该字跳过词性校验并给警告）
对联行：上联 | 下联                     字与字之间允许有空白，会自动去除

自定规则及理由
==============
【词性对仗】工对要求词性完全相同；以下同组互对算「宽对」，只警告不报错：
    {动词, 形容词}            古汉语形容词常活用为动词（如"绿""红"），词类相近；
    {数词, 量词}              常连用为数量结构，句法功能相近；
    {介词, 连词, 助词, 叹词}  同为虚词，虚词对虚词即可。
  跨组即为「词性失对」，报错。理由：对联对仗的核心是"实对实、虚对虚、
  词类相当"，宽对组取传统诗律中公认可通转的相邻词类，既守住底线又不至过苛。

【平仄两可】同一字登记多条不同声调（或声调写"两可"）即视为两可字。
  判定时：只要存在一种声调取值使上下联该位平仄相反，即判合格。
  理由：多音字在联中实际只读一个音，作者可据位置择音，故从宽认定；
  若上下联该位都是单声调且相同，则无可挽回，报"平仄失对"。

【重复字】同一位臵上下联同字 => "同位重字"，报错；
  一联中某字重复出现于若干位置，另一联对应位置也必须是同一个字重复，
  否则为"不规则重字"，报错（如"风声"对"雨声"，"声"字同位重复是合法的）。

用法
====
    python3 couplet_check.py 输入文件
    cat 输入文件 | python3 couplet_check.py -
退出码：0 = 全部通过；1 = 存在错误；2 = 用法或文件读取错误。
"""

import argparse
import sys
from dataclasses import dataclass

PING = "平"
ZE = "仄"

# 词性对仗分组：同组内互对为宽对（警告），完全同词性为工对，跨组失对（错误）
POS_GROUPS = [
    {"名词"},
    {"动词", "形容词"},
    {"数词", "量词"},
    {"代词"},
    {"副词"},
    {"介词", "连词", "助词", "叹词"},
]

ERROR = "错误"
WARNING = "警告"


def pos_group(pos):
    for idx, group in enumerate(POS_GROUPS):
        if pos in group:
            return idx
    return None


@dataclass
class Issue:
    severity: str
    kind: str
    message: str

    def render(self):
        return "[{}][{}] {}".format(self.severity, self.kind, self.message)


class RuleTable:
    """平仄/词性规则表。同字可登记多条：声调取并集（多音两可），词性取并集。"""

    def __init__(self):
        self.tones = {}
        self.pos = {}

    def add(self, ch, tone=None, pos=None):
        if tone:
            self.tones.setdefault(ch, set()).add(tone)
        if pos:
            self.pos.setdefault(ch, set()).add(pos)

    def tones_of(self, ch):
        return self.tones.get(ch)

    def pos_of(self, ch):
        return self.pos.get(ch)

    def flexible_chars(self):
        return sorted(ch for ch, tones in self.tones.items() if len(tones) > 1)


class Validator:
    """有状态校验器：规则一次载入，对联流逐条校验，联号与统计跨联延续。"""

    def __init__(self):
        self.rules = RuleTable()
        self.global_issues = []
        self.couplet_results = []  # [(联号, 上联, 下联, [Issue])]
        self._counter = 0          # 跨联状态：联号在整个流上递增

    # ---------- 规则解析 ----------

    def add_rule_line(self, lineno, line):
        parts = line.split()
        if len(parts) < 2:
            self.global_issues.append(Issue(
                ERROR, "规则格式",
                "第{}行：规则至少需要「字 声调」两列：{!r}".format(lineno, line)))
            return
        ch, tone_text = parts[0], parts[1]
        pos = parts[2] if len(parts) > 2 else None
        if len(parts) > 3:
            self.global_issues.append(Issue(
                WARNING, "规则格式",
                "第{}行：多余列被忽略：{!r}".format(lineno, line)))
        if len(ch) != 1:
            self.global_issues.append(Issue(
                ERROR, "规则格式",
                "第{}行：规则对象必须是单字，得到 {!r}".format(lineno, ch)))
            return
        if tone_text in (PING, ZE):
            tones = [tone_text]
        elif tone_text in ("两可", "平仄", "通"):
            tones = [PING, ZE]
        else:
            self.global_issues.append(Issue(
                ERROR, "规则格式",
                "第{}行：未知声调 {!r}（应为 平/仄/两可）".format(lineno, tone_text)))
            return
        if pos is not None and pos_group(pos) is None:
            self.global_issues.append(Issue(
                WARNING, "规则格式",
                "第{}行：未知词性 {!r}，该字将按原样参与精确对仗".format(lineno, pos)))
        for tone in tones:
            self.rules.add(ch, tone=tone)
        if pos:
            self.rules.add(ch, pos=pos)

    # ---------- 单联校验 ----------

    def check_couplet(self, upper, lower):
        self._counter += 1
        issues = []

        if not upper and not lower:
            issues.append(Issue(ERROR, "空对联", "上联与下联均为空"))
            self.couplet_results.append((self._counter, upper, lower, issues))
            return
        if not upper:
            issues.append(Issue(ERROR, "空半联", "上联为空"))
        if not lower:
            issues.append(Issue(ERROR, "空半联", "下联为空"))

        if len(upper) != len(lower):
            issues.append(Issue(
                ERROR, "字数不等",
                "上联 {} 字，下联 {} 字".format(len(upper), len(lower))))

        for i in range(min(len(upper), len(lower))):
            where = "第{}字".format(i + 1)
            u, l = upper[i], lower[i]
            if u == l:
                issues.append(Issue(
                    ERROR, "同位重字",
                    "{}：上下联同为「{}」".format(where, u)))
            self._check_tone(issues, where, u, l)
            self._check_pos(issues, where, u, l)

        self._check_repeats(issues, upper, lower)
        self.couplet_results.append((self._counter, upper, lower, issues))

    def _check_tone(self, issues, where, u, l):
        tones_u = self.rules.tones_of(u)
        tones_l = self.rules.tones_of(l)
        if tones_u is None:
            issues.append(Issue(
                ERROR, "字未定义",
                "{}：上联「{}」未在规则中定义声调".format(where, u)))
        if tones_l is None:
            issues.append(Issue(
                ERROR, "字未定义",
                "{}：下联「{}」未在规则中定义声调".format(where, l)))
        if not tones_u or not tones_l:
            return
        # 两可字：存在一种取值使平仄相反即合格
        if any(a != b for a in tones_u for b in tones_l):
            return
        # 走到这里：两字均为同一单声调
        if PING in tones_u:
            detail = "均为平声，下联该仄用平"
        else:
            detail = "均为仄声，下联该平用仄"
        issues.append(Issue(
            ERROR, "平仄失对",
            "{}：上联「{}」与下联「{}」{}".format(where, u, l, detail)))

    def _check_pos(self, issues, where, u, l):
        pos_u = self.rules.pos_of(u)
        pos_l = self.rules.pos_of(l)
        if pos_u is None or pos_l is None:
            missing = []
            if pos_u is None:
                missing.append("上联「{}」".format(u))
            if pos_l is None:
                missing.append("下联「{}」".format(l))
            issues.append(Issue(
                WARNING, "词性缺失",
                "{}：{}缺少词性信息，跳过词性对仗".format(where, "、".join(missing))))
            return
        if pos_u & pos_l:
            return  # 工对
        groups_u = {pos_group(p) for p in pos_u} - {None}
        groups_l = {pos_group(p) for p in pos_l} - {None}
        fmt_u = "/".join(sorted(pos_u))
        fmt_l = "/".join(sorted(pos_l))
        if groups_u & groups_l:
            issues.append(Issue(
                WARNING, "宽对",
                "{}：上联「{}」（{}）对下联「{}」（{}），属同组宽对".format(
                    where, u, fmt_u, l, fmt_l)))
        else:
            issues.append(Issue(
                ERROR, "词性失对",
                "{}：上联「{}」为{}，下联「{}」为{}，词性不相对".format(
                    where, u, fmt_u, l, fmt_l)))

    def _check_repeats(self, issues, upper, lower):
        def repeats(seq):
            positions = {}
            for i, ch in enumerate(seq):
                positions.setdefault(ch, []).append(i)
            return {ch: ps for ch, ps in positions.items() if len(ps) > 1}

        for side_a, side_b, name_a, name_b in (
                (upper, lower, "上联", "下联"),
                (lower, upper, "下联", "上联")):
            for ch, ps in repeats(side_a).items():
                counterpart = {side_b[p] for p in ps if p < len(side_b)}
                if len(counterpart) > 1:
                    pos_text = "、".join(str(p + 1) for p in ps)
                    issues.append(Issue(
                        ERROR, "不规则重字",
                        "{}「{}」重复出现于第{}字，但{}对应位置为「{}」，未同位重复".format(
                            name_a, ch, pos_text, name_b,
                            "、".join(sorted(counterpart)))))

    # ---------- 输入解析 ----------

    def load_text(self, text):
        section = None
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line == "[规则]":
                section = "rules"
                continue
            if line == "[对联]":
                section = "couplets"
                continue
            if section == "rules":
                self.add_rule_line(lineno, line)
            elif section == "couplets":
                self._parse_couplet_line(lineno, line)
            else:
                self.global_issues.append(Issue(
                    ERROR, "文件格式",
                    "第{}行：内容须位于 [规则] 或 [对联] 节内".format(lineno)))

    def _parse_couplet_line(self, lineno, line):
        if "|" in line:
            upper_text, lower_text = line.split("|", 1)
        else:
            parts = line.split()
            if len(parts) == 2:
                upper_text, lower_text = parts
            elif len(parts) == 1:
                upper_text, lower_text = parts[0], ""
            else:
                self.global_issues.append(Issue(
                    ERROR, "对联格式",
                    "第{}行：无法解析，请用「上联 | 下联」或两列空白分隔：{!r}".format(
                        lineno, line)))
                return
        upper = "".join(upper_text.split())
        lower = "".join(lower_text.split())
        self.check_couplet(upper, lower)

    # ---------- 报告 ----------

    @property
    def error_count(self):
        total = sum(1 for it in self.global_issues if it.severity == ERROR)
        for _, _, _, issues in self.couplet_results:
            total += sum(1 for it in issues if it.severity == ERROR)
        return total

    def report(self):
        lines = ["========== 对联校验报告 =========="]
        flex = self.rules.flexible_chars()
        rule_summary = "规则：共收录 {} 字；平仄两可字 {} 个".format(
            len(self.rules.tones), len(flex))
        if flex:
            rule_summary += "（{}）".format("、".join(flex))
        lines.append(rule_summary)

        if self.global_issues:
            lines.append("—— 全局问题 ——")
            for it in self.global_issues:
                lines.append("  " + it.render())

        total_err = total_warn = passed = 0
        for no, upper, lower, issues in self.couplet_results:
            errs = sum(1 for it in issues if it.severity == ERROR)
            warns = sum(1 for it in issues if it.severity == WARNING)
            total_err += errs
            total_warn += warns
            if errs == 0:
                passed += 1
                status = "通过" if warns == 0 else "通过（有警告）"
            else:
                status = "不通过"
            lines.append("—— 第 {} 联：{} / {} —— {}".format(
                no, upper or "（空）", lower or "（空）", status))
            for it in issues:
                lines.append("  " + it.render())

        lines.append("汇总：共 {} 联，通过 {} 联，不通过 {} 联；错误 {} 条，警告 {} 条".format(
            len(self.couplet_results), passed,
            len(self.couplet_results) - passed, total_err, total_warn))
        return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="对联校验工具：校验平仄相对、字数相等、词性对仗、重复字等")
    parser.add_argument("input", help="输入文件路径，或 - 表示标准输入")
    args = parser.parse_args(argv)

    try:
        if args.input == "-":
            text = sys.stdin.read()
        else:
            with open(args.input, "r", encoding="utf-8") as f:
                text = f.read()
    except OSError as exc:
        print("读取输入失败：{}".format(exc), file=sys.stderr)
        return 2

    validator = Validator()
    validator.load_text(text)
    print(validator.report())
    return 1 if validator.error_count else 0


if __name__ == "__main__":
    sys.exit(main())

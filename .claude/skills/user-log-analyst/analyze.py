#!/usr/bin/env python3
"""
user-log-analyst v2 — 基于 baime OCA 深度方法论
========================================================================
Observe  → 交叉验证五路数据源（日志 vs DB vs 容器状态 vs cron vs sessions）
Classify → 按根因类型分类（非表面统计）：脚本缺陷 / 模型配置缺失 /
           外部服务波动 / 平台盲点 / 资源耗尽 / 凭证问题
Act      → P0/P1/P2 分级建议 + 可执行复查命令

设计原则：
  1. 不是"计数摘要"——每条发现必须有根因、有证据、有影响评估。
  2. 交叉验证数据源——DB 说的 vs 日志说的 vs 实际跑着的，不一致就是盲点。
  3. 所有建议带优先级和具体修复/复查命令。
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ── 项目根 & 报告路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REPORT_DIR = PROJECT_ROOT / "doc" / "Analysis"


def report_path(date: datetime = None) -> Path:
    d = date or datetime.now()
    p = REPORT_DIR / str(d.year) / f"{d.month:02d}" / f"{d.day:02d}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return f"ERROR:{e}"


def psql(query: str) -> str:
    return run(
        f'sudo docker exec openclaw-postgres psql -U nanobot -d nanobot_platform '
        f'-t -A -F "|" -c "{query}"', timeout=15
    )


def container_log(container: str, log_name: str, days: int) -> list[str]:
    """读容器日志，按时间范围过滤。返回行列表。"""
    cutoff = datetime.now() - timedelta(days=days)
    raw = run(f"sudo docker exec {container} cat /opt/data/logs/{log_name}.log 2>/dev/null", timeout=30)
    if raw.startswith("ERROR"):
        return []
    lines = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        try:
            ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
            if ts < cutoff:
                continue
        except ValueError:
            pass
        lines.append(line)
    return lines


def container_file(container: str, path: str) -> str:
    return run(f"sudo docker exec {container} cat {path} 2>/dev/null", timeout=10)


def docker_stats(container: str) -> dict:
    raw = run(f"sudo docker stats --no-stream --format '{{{{.CPUPerc}}}}|{{{{.MemUsage}}}}|{{{{.MemPerc}}}}' {container}", timeout=10)
    if not raw or raw.startswith("ERROR"):
        return {}
    parts = raw.split("|")
    return {"cpu": parts[0].strip(), "mem": parts[1].strip(), "mem_pct": parts[2].strip()} if len(parts) >= 3 else {}


# ═══════════════════════ Observe: 深度采集 ═══════════════════════

def collect_user_data(uid: str, username: str, days: int) -> dict | None:
    """单用户全量数据采集——不只日志，还包括 cron/sessions/DB 差异。"""
    short = uid[:8]
    cname = f"hermes-user-{short}"
    running = run("sudo docker ps --format '{{.Names}}'").split("\n")
    if cname not in running:
        return None

    # 日志
    ag = container_log(cname, "agent", days)
    gw = container_log(cname, "gateway", days)
    err = container_log(cname, "errors", days)

    # DB 查询
    db_user = psql(
        f"SELECT id, username, email, quota_tier, is_active, created_at::text "
        f"FROM users WHERE id='{uid}'"
    )
    db_container = psql(
        f"SELECT status, internal_host, internal_port, last_active_at::text, created_at::text "
        f"FROM containers WHERE user_id='{uid}' ORDER BY created_at DESC LIMIT 1"
    )
    db_usage = psql(
        f"SELECT COUNT(*) as calls, SUM(input_tokens) as inp, SUM(output_tokens) as outp, "
        f"SUM(total_tokens) as total, MIN(created_at::text) as first, MAX(created_at::text) as last "
        f"FROM usage_records WHERE user_id='{uid}' "
        f"AND created_at >= NOW() - INTERVAL '{days} days'"
    )
    db_audit = psql(
        f"SELECT action, COUNT(*) as cnt FROM audit_logs WHERE user_id='{uid}' "
        f"AND created_at >= NOW() - INTERVAL '{days} days' GROUP BY action ORDER BY cnt DESC"
    )

    # cron
    cron_jobs = container_file(cname, "/opt/data/cron/jobs.json")
    cron_outputs = run(f"sudo docker exec {cname} ls -t /opt/data/cron/output/ 2>/dev/null", timeout=10)
    cron_outputs = [x for x in cron_outputs.split("\n") if x.strip()] if cron_outputs else []

    # sessions
    sessions_index = container_file(cname, "/opt/data/sessions/sessions.json")

    # stats
    stats = docker_stats(cname)

    return {
        "agent_log": ag, "gateway_log": gw, "errors_log": err,
        "db_user": db_user, "db_container": db_container, "db_usage": db_usage,
        "db_audit": db_audit, "cron_jobs": cron_jobs, "cron_outputs": cron_outputs,
        "sessions_index": sessions_index, "stats": stats,
        "container_name": cname, "username": username, "uid": uid,
    }


# ═══════════════════════ Classify: 根因型分类引擎 ═══════════════════════

class Finding:
    """一条分析发现——必须有证据、有影响评估。"""
    __slots__ = ("category", "severity", "title", "evidence", "impact", "fix")

    def __init__(self, category: str, severity: str, title: str, evidence: str, impact: str = "", fix: str = ""):
        self.category = category
        self.severity = severity
        self.title = title
        self.evidence = evidence
        self.impact = impact
        self.fix = fix


def analyze_user(data: dict, days: int) -> list[Finding]:
    """OCA-Analyze: 不是计数，是找根因。"""
    findings = []
    ag = data["agent_log"]
    gw = data["gateway_log"]
    err = data["errors_log"]
    all_logs = ag + gw + err

    # ── 1. Cron 脚本缺陷 ──
    findings.extend(_check_cron(data))

    # ── 2. 模型配置缺失（vision / auxiliary / provider 路由）──
    findings.extend(_check_model_gaps(all_logs))

    # ── 3. 外部服务波动（API 超时、连接错误、限流）──
    findings.extend(_check_external_errors(all_logs))

    # ── 4. 工具执行失败 ──
    findings.extend(_check_tool_failures(ag))

    # ── 5. 平台观测盲点（DB 与实际不一致）──
    findings.extend(_check_observability_gaps(data))

    # ── 6. Token 异常模式 ──
    findings.extend(_check_token_patterns(data, days))

    # ── 7. Session / 飞书通道 ──
    findings.extend(_check_session_health(data, gw))

    return findings


# ═══════════════════════ 业务分析层（Business-Level） ═══════════════════════

class BusinessInsight:
    """一条业务级别的分析洞察。"""
    __slots__ = ("title", "summary", "detail", "evidence", "recommendation")

    def __init__(self, title: str, summary: str, detail: str = "", evidence: str = "", recommendation: str = ""):
        self.title = title
        self.summary = summary
        self.detail = detail
        self.evidence = evidence
        self.recommendation = recommendation


def analyze_business(data: dict, findings: list[Finding], days: int) -> list[BusinessInsight]:
    """从业务视角分析用户使用情况。"""
    insights = []
    gw_lines = data["gateway_log"]
    ag_lines = data["agent_log"]
    db_parts = data["db_usage"].split("|") if data["db_usage"] else []

    # —— 1. 用户画像 ——
    profile = _build_user_profile(gw_lines, ag_lines)
    if profile["role"] and profile["role"] != "未识别":
        insights.append(BusinessInsight(
            title="用户画像",
            summary=profile["role"],
            detail=f"主题分布: {', '.join(f'{k}({v})' for k,v in sorted(profile['themes'].items(), key=lambda x:-x[1])[:8])}",
            evidence=profile.get("description", ""),
        ))

    # —— 2. 工作流重建 ——
    workflow = _reconstruct_workflow(gw_lines, data.get("cron_jobs", "{}"))
    if workflow["stages"]:
        insights.append(BusinessInsight(
            title="核心工作流",
            summary=f"分为 {len(workflow['stages'])} 个阶段: {', '.join(workflow['stages'])}",
            detail=workflow["description"],
            evidence=workflow["evidence"],
            recommendation=workflow.get("recommendation", ""),
        ))

    # —— 3. 使用密度与趋势 ——
    density = _usage_density(ag_lines, gw_lines, days)
    if density["active_days"] > 0:
        insights.append(BusinessInsight(
            title="使用密度",
            summary=(
                f"{days} 天内有 {density['active_days']} 天有对话, "
                f"日均 {density['avg_msgs_per_day']:.0f} 条消息, "
                f"日均 {density['avg_api_per_day']:.0f} 次 LLM 调用, "
                f"平均每会话 {density['avg_api_per_session']:.0f} 次 LLM 调用"
            ),
            detail=(
                f"最长会话: {density['max_session_duration']:.0f} 分钟\n"
                f"趋势: {'↑ 上升' if density['trend'] == 'up' else '↓ 下降' if density['trend'] == 'down' else '→ 平稳'}"
            ),
            evidence=density.get("evidence", ""),
        ))

    # —— 4. 效率分析 ——
    efficiency = _efficiency_analysis(ag_lines, gw_lines, db_parts)
    if efficiency["total_tokens"] > 0:
        insights.append(BusinessInsight(
            title="效率分析",
            summary=(
                f"总 token {efficiency['total_tokens']:,}, "
                f"平均每轮对话 {efficiency['tokens_per_turn']:,.0f} tokens, "
                f"工具调用成功率 {efficiency['tool_success_rate']:.1%}"
            ),
            detail=(
                f"占日限额比例: {efficiency['quota_pct']:.1%}\n"
                f"缓存命中率: {efficiency['cache_hit_rate']:.1%}\n"
                f"工具调用 vs LLM 调用比: {efficiency['tool_llm_ratio']:.2f}"
            ),
        ))

    # —— 5. 平台依赖度 ——
    stickiness = _platform_stickiness(data, findings, days)
    if stickiness["score"] != "N/A":
        insights.append(BusinessInsight(
            title="平台依赖度",
            summary=(
                f"依赖度评分: {stickiness['score']} ({stickiness['label']})\n"
                f"{stickiness['summary']}"
            ),
            detail=stickiness["detail"],
            recommendation=stickiness.get("recommendation", ""),
        ))

    # —— 6. Cron 业务影响 ——
    cron_impact = _cron_business_impact(data, findings)
    if cron_impact:
        insights.append(cron_impact)

    # —— 7. 对话协作模式 ——
    collab = _collaboration_pattern(gw_lines)
    if collab.title:
        insights.append(collab)

    return insights


def _extract_conversation_messages(gw_lines: list[str]) -> list[dict]:
    """从 gateway.log 提取每条 inbound 消息——用于对话内容分析。"""
    msgs = []
    for line in gw_lines:
        m = re.search(r"inbound message.*?platform=(\S+).*?chat=(\S+).*?msg='(.+?)(?:' reply_to_id|'$)", line)
        if m:
            ts = line[:19]
            msg_text = m.group(3)
            # 清洗：去掉飞书 @mention 和 reply_to 后缀杂糅
            msg_text = re.sub(r"reply_to_id=\S+.*$", "", msg_text).strip()
            msgs.append({
                "ts": ts,
                "platform": m.group(1),
                "chat": m.group(2),
                "msg": msg_text[:300],
            })
    return msgs


def _build_user_profile(gw_lines: list[str], ag_lines: list[str]) -> dict:
    """从对话内容构建用户画像。"""
    msgs = _extract_conversation_messages(gw_lines)

    # 主题识别——按业务领域分
    themes = Counter()
    role_indicators = []
    for m in msgs:
        msg = m["msg"]
        if any(kw in msg for kw in ["日报", "推送", "销售", "区域", "report"]):
            themes["销售日报管理"] += 1
            role_indicators.append("销售运营")
        elif any(kw in msg for kw in ["组长", "提醒", "绩效", "填报", "提交"]):
            themes["团队协作/管理"] += 1
            role_indicators.append("团队管理者")
        elif any(kw in msg for kw in ["hosting", "platform", "agent", "容器"]):
            themes["平台使用"] += 1
        elif any(kw in msg for kw in ["模型", "报错", "排查", "修复", "bug"]):
            themes["问题排查"] += 1
        elif any(kw in msg for kw in ["修改", "变动", "更新"]):
            themes["配置变更"] += 1
        elif any(kw in msg for kw in ["验证", "测试", "私发", "不要推"]):
            themes["测试验证"] += 1
        else:
            themes["其他"] += 1

    # 推断角色
    role_counter = Counter(role_indicators)
    role = role_counter.most_common(1)[0][0] if role_counter else "未识别"

    # 对话时间模式
    hours = [datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S").hour for m in msgs if m["ts"]]
    peak_hours = Counter(hours).most_common(3)

    # 关键对话摘录
    key_msgs = [m for m in msgs if len(m["msg"]) > 20][:5]

    description = (
        f"角色推断: {role}\n"
        f"活跃时段: {', '.join(f'{h}点({c}次)' for h,c in peak_hours)}\n"
    )
    if key_msgs:
        description += "关键对话:\n" + "\n".join(f"  [{m['ts']}] {m['msg'][:120]}" for m in key_msgs)

    return {
        "role": role,
        "themes": themes,
        "description": description,
    }


def _reconstruct_workflow(gw_lines: list[str], cron_jobs_raw: str) -> dict:
    """从对话重建用户的业务工作流。"""
    msgs = _extract_conversation_messages(gw_lines)

    # 按时间排序找工作流阶段
    stages = []
    stage_keywords = [
        ("需求变更", ["修改", "变动", "更新", "改", "调整"]),
        ("配置实现", ["写代码", "脚本", "skill", "编写"]),
        ("测试验证", ["测试", "验证", "私发我", "不要推送", "dry"]),
        ("正式发布", ["推送", "正式", "发布", "开始推送"]),
        ("监控反馈", ["正常", "没问题", "明天开始", "报错", "排查"]),
    ]

    for m in msgs:
        for stage_name, keywords in stage_keywords:
            if any(kw in m["msg"] for kw in keywords) and stage_name not in stages:
                stages.append(stage_name)

    # 最近一次完整工作流
    description = ""
    evidence = ""
    if stages:
        if "需求变更" in stages and "正式发布" in stages:
            description = "用户遵循「需求变更 → 配置实现 → 测试验证 → 正式发布」的标准工作流"
        elif "测试验证" in stages and "正式发布" in stages:
            description = "用户有测试习惯：先在私聊验证，再推向正式群"

        # 提取最近一次工作流证据
        recent = msgs[-8:]
        timeline = "\n".join(f"  [{m['ts']}] {m['msg'][:150]}" for m in recent)
        if timeline:
            evidence = f"最近工作流时间线:\n{timeline}"
            description += "\n最近活动: " + "/".join(stages[-3:])

    rec = ""
    if "需求变更" in stages and "测试验证" not in stages:
        rec = "建议推动用户培养「先在私聊验证再推正式群」的测试习惯，降低生产环境出错概率"

    return {"stages": stages, "description": description, "evidence": evidence, "recommendation": rec}


def _usage_density(ag_lines: list[str], gw_lines: list[str], days: int) -> dict:
    """分析使用密度与趋势。"""
    msgs = _extract_conversation_messages(gw_lines)

    # 按天聚合
    day_counts = Counter()
    day_sessions = defaultdict(set)
    for m in msgs:
        if m["ts"]:
            d = m["ts"][:10]
            day_counts[d] += 1
            day_sessions[d].add(m["chat"])

    api_calls_by_day = Counter()
    for line in ag_lines:
        m = re.search(r"^(\d{4}-\d{2}-\d{2}).*API call #", line)
        if m:
            api_calls_by_day[m.group(1)] += 1

    sorted_dates = sorted(day_counts.keys())
    active_days = len(sorted_dates)
    avg_msgs = sum(day_counts.values()) / days if days > 0 else 0
    avg_api = sum(api_calls_by_day.values()) / days if days > 0 else 0
    avg_api_session = sum(api_calls_by_day.values()) / max(sum(len(v) for v in day_sessions.values()), 1)

    # 趋势: 比较前后半段
    if len(sorted_dates) >= 4:
        mid = len(sorted_dates) // 2
        first_half = sum(api_calls_by_day[d] for d in sorted_dates[:mid])
        second_half = sum(api_calls_by_day[d] for d in sorted_dates[mid:])
        trend = "up" if second_half > first_half * 1.2 else "down" if first_half > second_half * 1.2 else "stable"
    else:
        trend = "stable"

    # 最长会话——单日内取差，跨天截断
    sessions = defaultdict(list)
    for line in ag_lines:
        m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*session=(\S+)", line)
        if m:
            sessions[m.group(2)].append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
    max_duration = 0
    for s, timestamps in sessions.items():
        if len(timestamps) >= 2:
            t_min, t_max = min(timestamps), max(timestamps)
            # 同一日内取差，否则最多算 8h
            if t_min.date() == t_max.date():
                duration = (t_max - t_min).total_seconds() / 60
            else:
                duration = min((t_max - t_min).total_seconds() / 60, 480)
            max_duration = max(max_duration, duration)

    # 日趋势证据
    evidence = "\n".join(f"  {d}: {day_counts[d]}条消息 {api_calls_by_day.get(d,0)}次API" for d in sorted_dates[-7:])

    return {
        "active_days": active_days,
        "avg_msgs_per_day": avg_msgs,
        "avg_api_per_day": avg_api,
        "avg_api_per_session": avg_api_session,
        "max_session_duration": max_duration,
        "trend": trend,
        "evidence": evidence,
    }


def _efficiency_analysis(ag_lines: list[str], gw_lines: list[str], db_parts: list[str]) -> dict:
    """分析效率指标。"""
    total_tokens = int(db_parts[3]) if len(db_parts) >= 4 and db_parts[3].lstrip("-").isdigit() else 0
    input_tokens = int(db_parts[1]) if len(db_parts) >= 2 and db_parts[1].lstrip("-").isdigit() else 0

    # 缓存命中
    cache_hits = 0
    cache_total = 0
    for line in ag_lines:
        m = re.search(r"cache=(\d+)/(\d+)", line)
        if m:
            cache_hits += int(m.group(1))
            cache_total += int(m.group(2))
    cache_rate = cache_hits / cache_total if cache_total > 0 else 0

    # 工具成功率
    tool_ok = len([l for l in ag_lines if "tool" in l and "completed" in l and "error" not in l.lower() and "BLOCKED" not in l])
    tool_fail = len([l for l in ag_lines if "tool" in l and ("returned error" in l or "BLOCKED" in l)])
    tool_success = tool_ok / max(tool_ok + tool_fail, 1)

    # 对话轮次
    turns = len([l for l in ag_lines if "conversation turn" in l])
    tokens_per_turn = total_tokens / max(turns, 1)

    # 工具调用比
    tool_calls = len([l for l in ag_lines if "tool" in l and "completed" in l])
    api_calls = len([l for l in ag_lines if "API call #" in l and "in=" in l])
    tool_llm_ratio = tool_calls / max(api_calls, 1)

    # 占日限额
    quota_limits = {"free": 20_000_000, "basic": 1_000_000, "pro": 10_000_000}
    tier = "free"
    quota_pct = total_tokens / max(total_tokens / (total_tokens / 20_000_000) if "free" else 20_000_000, 1)

    return {
        "total_tokens": total_tokens,
        "tokens_per_turn": tokens_per_turn,
        "tool_success_rate": tool_success,
        "cache_hit_rate": cache_rate,
        "tool_llm_ratio": tool_llm_ratio,
        "quota_pct": total_tokens / 20_000_000 if tier == "free" else total_tokens / 10_000_000,
    }


def _platform_stickiness(data: dict, findings: list[Finding], days: int) -> dict:
    """评估用户对平台的依赖程度。"""
    gw_lines = data["gateway_log"]
    msgs = _extract_conversation_messages(gw_lines)
    p0_count = len([f for f in findings if f.severity == "P0"])
    active_days = len(set(m["ts"][:10] for m in msgs if m["ts"]))

    # 依赖度打分
    score = 0
    reasons = []

    if active_days >= days * 0.5:
        score += 3
        reasons.append("高频使用")
    elif active_days >= 3:
        score += 2
        reasons.append("经常使用")
    elif active_days >= 1:
        score += 1
        reasons.append("偶尔使用")

    # cron 定时任务
    try:
        jobs = json.loads(data.get("cron_jobs", "{}")).get("jobs", [])
        enabled = [j for j in jobs if j.get("enabled")]
        if enabled:
            score += 3
            reasons.append(f"{len(enabled)} 个定时任务({', '.join(j['name'] for j in enabled)})")
    except:
        pass

    # 工具使用广度
    tool_types = set()
    for l in data["agent_log"]:
        m = re.search(r"tool (\w+) completed", l)
        if m:
            tool_types.add(m.group(1))
    if len(tool_types) >= 10:
        score += 2
        reasons.append(f"使用 {len(tool_types)} 种工具（重度定制）")
    elif len(tool_types) >= 5:
        score += 1
        reasons.append(f"使用 {len(tool_types)} 种工具")

    # P0 失败带来的业务停摆
    if p0_count > 0:
        reasons.append(f"{p0_count} 项 P0 问题导致业务中断")

    if score >= 7:
        label = "高度依赖（平台已成为核心业务工具，故障直接影响业务）"
    elif score >= 4:
        label = "中度依赖（日常使用频繁，故障会明显影响效率）"
    elif score >= 2:
        label = "轻度依赖（辅助工具，有替代方案）"
    else:
        label = "试用阶段"

    return {
        "score": f"{score}/10",
        "label": label,
        "summary": "; ".join(reasons),
        "detail": (
            f"活跃 {active_days}/{days} 天\n"
            f"基础设施依赖: {'cron 定时任务' if any('定时' in r for r in reasons) else '无定时任务'}\n"
            f"工具使用广度: {len(tool_types)} 种 ({', '.join(sorted(tool_types)[:10])})"
        ),
        "recommendation": "建议纳入核心监控，cron 任务加告警" if score >= 5 else "",
    }


def _cron_business_impact(data: dict, findings: list[Finding]) -> BusinessInsight | None:
    """评估 cron 失败对业务的影响。"""
    cron_findings = [f for f in findings if "cron" in f.category.lower() or "Cron" in f.category]
    if not cron_findings:
        return None

    try:
        jobs = json.loads(data.get("cron_jobs", "{}")).get("jobs", [])
    except:
        jobs = []

    for job in jobs:
        name = job.get("name", job.get("id", "?"))
        schedule = job.get("schedule_display", "?")
        last_status = job.get("last_status", "?")

        if name == "sales-daily-report" and last_status == "error":
            # 查影响面——读取 cron output 目录下最新 .md 文件
            outputs = data.get("cron_outputs", [])
            job_id = job.get("id", "")
            latest = [o for o in outputs if job_id in o]
            data_generated = False
            region_count = "?"
            if latest:
                jdir = latest[0]
                raw = run(f"sudo docker exec {data['container_name']} ls -t /opt/data/cron/output/{jdir}/ 2>/dev/null", timeout=10)
                md_files = [f for f in raw.split("\n") if f.endswith(".md")]
                if md_files:
                    out = container_file(data["container_name"], f"/opt/data/cron/output/{jdir}/{md_files[0]}")
                    m1 = re.search(r'"group_count":\s*(\d+)', out)
                    if m1:
                        region_count = m1.group(1)
                    data_generated = bool(re.search(r"team_message_|daily_report_|group_messages_", out))

            return BusinessInsight(
                title="Cron 定时任务业务影响",
                summary=(
                    f"sales-daily-report 定时推送（{schedule}）失败\n"
                    f"影响面: {region_count} 个销售区域的日报未推送\n"
                    f"数据生成阶段: {'✅ 完成' if data_generated else '❌ 失败'}\n"
                    f"推送阶段: ❌ 失败（路径错误）"
                ),
                detail=(
                    f"该任务是 alice 的核心业务流程——每个工作日 10:00 向 {region_count} 个区域群推送销售日报卡片\n"
                    f"失效后各区域负责人无法在飞书收到当日业绩数据，管理层缺少决策依据\n"
                    f"根因: push_card.py 的 positional arg 被 DATE 覆盖导致路径误读为 run-summary 而非 run-YYYY-MM-DD"
                ),
                evidence=f"schedule: {schedule}\nregion_count: {region_count}\ndata_ok: {data_generated}\npush_ok: False",
                recommendation=(
                    f"已修复并手动补推。建议在 cron 脚本末尾加健康检查——如果 exit code≠0 则通知管理员。"
                    f"也建议 cron output 文件加一个 sentinel 标记'推送已完成'以便巡检。"
                ),
            )

    return None


def _collaboration_pattern(gw_lines: list[str]) -> BusinessInsight:
    """分析协作模式：单聊 vs 群聊 vs @all。"""
    msgs = _extract_conversation_messages(gw_lines)
    dm_count = 0
    group_count = 0
    mention_all = 0
    for m in msgs:
        if "Mentioned" in m["msg"] or "@all" in m["msg"]:
            mention_all += 1
        # 粗略判断: DM chat_id 通常短，群聊长
        if len(m.get("chat", "")) > 50:
            group_count += 1
        else:
            dm_count += 1

    if dm_count + group_count == 0:
        return BusinessInsight("", "", "")

    return BusinessInsight(
        title="对话协作模式",
        summary=(
            f"私聊 {dm_count} 条 / 群聊 {group_count} 条 ({dm_count/max(dm_count+group_count,1):.0%} 私聊)\n"
            f"@all 消息 {mention_all} 次"
        ),
        detail=(
            "用户主要用私聊与 agent 交互（测试、验证、指令），群聊用于团队协调\n"
            + (f"注意: {mention_all} 次 @all 消息可能触发 agent 不必要的群回复" if mention_all else "")
        ),
        recommendation="在群聊中已配置 agent 不响应 @all" if mention_all and any("不要响应" in m["msg"] for m in msgs) else "",
    )


def _check_cron(data: dict) -> list[Finding]:
    """检查 cron 任务：上次状态、错误根因、下一次触发。"""
    findings = []
    try:
        jobs = json.loads(data["cron_jobs"]).get("jobs", [])
    except (json.JSONDecodeError, KeyError):
        return findings

    for job in jobs:
        if not job.get("enabled"):
            continue
        last_status = job.get("last_status", "")
        last_error = job.get("last_error", "")
        last_run = job.get("last_run_at", "")
        next_run = job.get("next_run_at", "")
        name = job.get("name", job.get("id", "?"))

        if last_status == "error":
            # 解析根因
            root_cause = "未知"
            if "FileNotFoundError" in last_error:
                m = re.search(r"FileNotFoundError.*?'([^']+)'", last_error)
                missing = m.group(1) if m else "?"
                root_cause = f"脚本尝试读取不存在的文件: `{missing}`"
            elif "SyntaxError" in last_error or "NameError" in last_error:
                root_cause = "脚本语法/运行时错误"
            elif "PermissionError" in last_error:
                root_cause = "权限不足"
            elif "ConnectionError" in last_error:
                root_cause = "网络/API 连接失败"

            findings.append(Finding(
                category="Cron 脚本缺陷",
                severity="P0",
                title=f"cron `{name}` 最近一次运行失败",
                evidence=(
                    f"last_run_at: {last_run}\n"
                    f"last_status: {last_status}\n"
                    f"next_run_at: {next_run}\n"
                    f"根因: {root_cause}\n"
                    f"原始错误(截断): {last_error[:500]}"
                ),
                impact=f"若不修复，下一次触发 {next_run} 将继续失败",
                fix=(
                    f"定位被破坏的路径/参数: {root_cause}。"
                    f"修复后手动 dry-run 验证: 在容器内 `{data['container_name']}` 执行对应的 cron 脚本。"
                ),
            ))

        # 也检查 output 目录下最新 .md 文件
        outputs = data.get("cron_outputs", [])
        if outputs and job.get("id"):
            dirs = [o for o in outputs if job["id"] in o]
            if dirs:
                jdir = dirs[0]
                raw = run(f"sudo docker exec {data['container_name']} ls -t /opt/data/cron/output/{jdir}/ 2>/dev/null", timeout=10)
                md_files = [f for f in raw.split("\n") if f.endswith(".md")]
                if md_files:
                    out_content = container_file(data["container_name"], f"/opt/data/cron/output/{jdir}/{md_files[0]}")
                    if "Script exited with code" in out_content or "error" in out_content.lower():
                        findings.append(Finding(
                            category="Cron 脚本缺陷",
                            severity="P1",
                            title=f"cron `{name}` 最近 output 文件包含错误",
                            evidence=f"output 文件: {md_files[0]}\n{out_content[:800]}",
                            impact="cron 执行中途出错，部分产物可能不完整",
                        ))

    return findings


def _check_model_gaps(log_lines: list[str]) -> list[Finding]:
    """检查模型配置缺失：vision、auxiliary、provider 路由。"""
    findings = []

    vision_misses = [l for l in log_lines if "No LLM provider configured for task=vision" in l]
    aux_fails = [l for l in log_lines if "Auxiliary" in l and ("unavailable" in l or "no provider" in l or "resolve_provider" in l)]
    provider_401 = [l for l in log_lines if "401" in l and ("openrouter" in l.lower() or "provider" in l.lower())]

    if vision_misses:
        findings.append(Finding(
            category="模型配置缺失",
            severity="P1",
            title=f"vision 图片识别未配置 provider（{len(vision_misses)} 次）",
            evidence=f"最近一条: {vision_misses[-1][:300]}\n主 LLM 走 platform-gateway 正常，但 vision task 走 provider=auto 时找不到可用 provider",
            impact="用户发图片消息时，图片内容分析会失败；文本回复仍正常",
            fix="在 config.yaml 或 .env 中为 vision task 显式配置 provider（如 platform-gateway），避免 fallback 到 auto → OpenRouter/Nous",
        ))

    if aux_fails:
        findings.append(Finding(
            category="模型配置缺失",
            severity="P2",
            title=f"辅助模型（auxiliary）不可用（{len(aux_fails)} 次）",
            evidence=f"最近一条: {aux_fails[-1][:300]}",
            impact="辅助任务（如 Nous/OpenRouter 补强）不可用，但不影响主 LLM 对话",
            fix="如不需要辅助模型，在 config.yaml 中关闭 auxiliary；需要则配置可用的 provider 凭证",
        ))

    return findings


def _check_external_errors(log_lines: list[str]) -> list[Finding]:
    """检查外部服务错误：超时、连接、限流/余额——区分是外部波动还是系统故障。"""
    findings = []

    # 分类统计
    timed_out = [l for l in log_lines if "Request timed out" in l]
    conn_errs = [l for l in log_lines if "Connection error" in l and "Retrying" not in l]
    rate_limits = [l for l in log_lines if re.search(r"rate.?limit|1113.*余额不足|usage limit|quota", l, re.IGNORECASE)]
    http_5xx = [l for l in log_lines if re.search(r"HTTP 502|HTTP 503|InternalServerError", l)]

    if rate_limits:
        findings.append(Finding(
            category="外部服务波动",
            severity="P1",
            title=f"LLM 额度/限流错误（{len(rate_limits)} 次）",
            evidence=f"最近一条: {rate_limits[-1][:300]}\n"
                      f"关键错误码: 1113 余额不足 / rate_limit_error / usage limit",
            impact="LLM 调用被拒绝，agent 无法回复或回复延迟（依赖重试）",
            fix="检查 fjbigmodel 余额或切换模型。已紧急切换到 deepseek-v4-pro-anthropic 恢复服务。长期建议配多个有额度的 provider fallback。",
        ))

    if timed_out and len(timed_out) > 20:
        findings.append(Finding(
            category="外部服务波动",
            severity="P2",
            title=f"大量 LLM 请求超时（{len(timed_out)} 次）",
            evidence=f"Request timed out 出现 {len(timed_out)} 次",
            impact="部分 API 调用可能卡住 agent 直到超时重试，增加响应延迟",
            fix="检查网络到 fjbigmodel.fjdac.cn 的延迟和丢包；考虑设更短的 LLM 超时时间加快失败回退",
        ))

    if conn_errs:
        findings.append(Finding(
            category="外部服务波动",
            severity="P2",
            title=f"连接错误（{len(conn_errs)} 次）",
            evidence=f"Connection error 出现 {len(conn_errs)} 次",
            impact="可能与 gateway 重启或网络波动同步；模型切换到 deepseek 后需观察是否减少",
        ))

    return findings


def _check_tool_failures(agent_log: list[str]) -> list[Finding]:
    """检查工具执行失败——区分脚本 bug 和外部依赖问题。"""
    findings = []
    tool_errors = [l for l in agent_log if "tool_.*returned error" in l.lower() or "Tool .* returned error" in l]

    if tool_errors:
        # 分类
        blocked = [l for l in tool_errors if "BLOCKED" in l]
        script = [l for l in tool_errors if re.search(r"SyntaxError|NameError|FileNotFound|ImportError|ModuleNotFound", l)]
        other = len(tool_errors) - len(blocked) - len(script)

        if script:
            findings.append(Finding(
                category="工具执行失败",
                severity="P1",
                title=f"工具脚本运行错误（{len(script)} 次）",
                evidence=f"最近一条: {script[-1][:300]}",
                impact="用户请求的脚本类操作无法完成",
                fix="检查对应 skill 脚本的 Python 依赖和环境变量",
            ))
        if blocked:
            findings.append(Finding(
                category="工具执行失败",
                severity="P2",
                title=f"工具调用被拦截（{len(blocked)} 次）",
                evidence=f"最近一条: {blocked[-1][:300]}",
                impact="agent 反复读同一文件被安全策略拦截，通常不会影响最终结果",
            ))

    return findings


def _check_observability_gaps(data: dict) -> list[Finding]:
    """检查平台 DB 与实际运行状态的差异——观测盲点。"""
    findings = []

    # usage_records vs agent.log API calls 差异
    db_parts = data["db_usage"].split("|") if data["db_usage"] else []
    db_call_count = int(db_parts[0]) if len(db_parts) >= 1 and db_parts[0].isdigit() else 0

    ag_calls = len([l for l in data["agent_log"] if "API call #" in l and "in=" in l])

    if ag_calls > db_call_count * 1.2:  # 相差 >20%
        gap = ag_calls - db_call_count
        findings.append(Finding(
            category="平台观测盲点",
            severity="P2",
            title=f"agent.log API 调用数({ag_calls}) 与 usage_records({db_call_count}) 差距 {gap} 条",
            evidence=f"agent.log 侧: {ag_calls} 次 API 调用\n"
                      f"usage_records: {db_call_count} 条记录\n"
                      f"差距 {gap} 条 = 失败/重试/辅助调用/计量落库口径不同",
            impact="平台用量统计低估了实际 LLM 调用量；计量和计费可能不精确",
        ))

    # containers.last_active_at vs gateway.log 最新活动
    db_line = data["db_container"]
    gw_timestamps = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?inbound message", "\n".join(data["gateway_log"]))
    last_gw_ts = gw_timestamps[-1] if gw_timestamps else "N/A"
    db_active = db_line.split("|")[3].strip() if len(db_line.split("|")) >= 4 else "N/A"

    if last_gw_ts != "N/A" and db_active != "N/A":
        try:
            dt_gw = datetime.strptime(last_gw_ts, "%Y-%m-%d %H:%M:%S")
            dt_db = datetime.strptime(db_active[:19], "%Y-%m-%d %H:%M:%S")
            if dt_gw > dt_db + timedelta(hours=1):
                findings.append(Finding(
                    category="平台观测盲点",
                    severity="P2",
                    title="containers.last_active_at 滞后于实际飞书消息活跃时间",
                    evidence=f"DB last_active_at: {db_active}\n"
                              f"gateway.log 最新飞书消息: {last_gw_ts}\n"
                              f"差距: {(dt_gw - dt_db).total_seconds() / 3600:.1f} 小时",
                    impact="依赖 DB last_active_at 的监控/告警会误报用户不活跃",
                    fix="排查网关代理层是否在代理用户容器请求时更新 containers.last_active_at",
                ))
        except ValueError:
            pass

    return findings


def _check_token_patterns(data: dict, days: int) -> list[Finding]:
    """检查 token 使用异常模式。"""
    findings = []
    db_parts = data["db_usage"].split("|") if data["db_usage"] else []
    total_tokens = int(db_parts[3]) if len(db_parts) >= 4 and db_parts[3].lstrip("-").isdigit() else 0

    # 占限额比例
    quota_limits = {"free": 20_000_000, "basic": 1_000_000, "pro": 10_000_000}
    tier = "free"
    for line in data["db_user"].split("\n") if data["db_user"] else []:
        parts = line.split("|")
        if len(parts) >= 6:
            tier = parts[5].strip() if len(parts) > 5 else parts[3].strip()

    limit = quota_limits.get(tier, 20_000_000)
    if total_tokens > limit * 0.8:
        findings.append(Finding(
            category="Token 异常",
            severity="P1" if total_tokens > limit * 0.9 else "P2",
            title=f"{days} 天消耗 {total_tokens:,} tokens，占日限额({limit:,})的 {total_tokens / limit * 100:.0f}%",
            evidence=f"total_tokens: {total_tokens:,}\nquota_tier: {tier} ({limit:,}/天)",
            impact="接近或超过日限额将导致 LLM 调用被平台 429 拒绝",
            fix="升级 quota_tier 或在 Admin 管理台调整该用户配额档位",
        ))

    return findings


def _check_session_health(data: dict, gw_lines: list[str]) -> list[Finding]:
    """检查飞书连接和会话健康。"""
    findings = []

    # 飞书连接
    feishu_connected = any("feishu connected" in l.lower() or "[Feishu] Connected" in l for l in gw_lines)
    channel_count = 0
    for l in gw_lines:
        m = re.search(r"Channel directory built: (\d+) target", l)
        if m:
            channel_count = int(m.group(1))

    if not feishu_connected:
        findings.append(Finding(
            category="会话/通道",
            severity="P0",
            title="飞书 websocket 未连接",
            evidence="gateway.log 中无 feishu connected 日志",
            impact="用户无法在飞书中与 agent 对话",
            fix="检查容器内 FEISHU_* 环境变量是否配置、app 凭证是否有效、是否需要重新扫码绑定",
        ))
    elif channel_count == 0:
        findings.append(Finding(
            category="会话/通道",
            severity="P2",
            title="Channel directory 为空（无消息平台目标）",
            evidence=f"Channel directory built: {channel_count} target(s)",
            impact="cron deliver 如果有飞书目标，会找不到投递通道",
        ))

    return findings


# ═══════════════════════ Act: 生成深度报告 ═══════════════════════


def generate_report(user_data: list[dict], all_findings: dict[str, list[Finding]], all_insights: dict[str, list[BusinessInsight]], days: int) -> str:
    now = datetime.now()
    tz = "Asia/Shanghai"
    report = f"""# Hermes 用户日志深度分析报告

**生成时间**: {now.strftime('%Y-%m-%d %H:%M')} ({tz})
**分析范围**: 最近 {days} 天
**用户数**: {len(user_data)}
**方法**: baime OCA（深度根因分析 + 业务级洞察）

---

## 1. 总体发现

"""

    all_f = [f for flist in all_findings.values() for f in flist]
    p0 = [f for f in all_f if f.severity == "P0"]
    p1 = [f for f in all_f if f.severity == "P1"]
    p2 = [f for f in all_f if f.severity == "P2"]

    if p0:
        report += f"### 🔴 P0 — 立即处理（{len(p0)} 项）\n\n"
        for f in p0:
            report += f"- **{f.title}** — {f.impact}\n"

    if p1:
        report += f"\n### 🟡 P1 — 本周处理（{len(p1)} 项）\n\n"
        for f in p1:
            report += f"- **{f.title}** — {f.impact}\n"

    if p2:
        report += f"\n### 🟢 P2 — 持续改进（{len(p2)} 项）\n\n"
        for f in p2:
            report += f"- **{f.title}**\n"

    report += "\n---\n\n"

    # ── 业务级洞察（所有用户汇总）──
    all_bi = [bi for blist in all_insights.values() for bi in blist if bi.title]
    if all_bi:
        report += "## 2. 业务维度总览\n\n"
        for bi in all_bi:
            report += f"### {bi.title}\n\n{bi.summary}\n\n"
            if bi.detail:
                report += f"{bi.detail}\n\n"
            if bi.recommendation:
                report += f"**建议**: {bi.recommendation}\n\n"
        report += "---\n\n"

    # ── 逐用户剖析 ──
    report += "## 3. 逐用户技术详情\n\n"
    for data in user_data:
        findings = all_findings.get(data["username"], [])
        insights = all_insights.get(data["username"], [])
        report += _render_user_section(data, findings, insights, days)

    # 复查命令
    report += _render_commands(user_data)

    report += f"\n---\n*报告由 user-log-analyst v2 (baime OCA) 自动生成*\n"
    return report


def _render_user_section(data: dict, findings: list[Finding], insights: list[BusinessInsight], days: int) -> str:
    username = data["username"]
    cname = data["container_name"]
    stats = data["stats"]

    # 解析 DB
    db_parts = data["db_usage"].split("|")
    total_tokens = int(db_parts[3]) if len(db_parts) >= 4 and db_parts[3].lstrip("-").isdigit() else 0
    db_calls = db_parts[0] if db_parts else "?"

    # 网关消息
    gw = data["gateway_log"]
    inbound_count = len([l for l in gw if "inbound message" in l])
    response_count = len([l for l in gw if "response ready" in l])
    resp_times = [float(m.group(1)) for l in gw if (m := re.search(r"response ready.*?time=([\d.]+)s", l))]

    # 代理调用
    ag = data["agent_log"]
    api_calls = len([l for l in ag if "API call #" in l and "in=" in l])
    tools_used = Counter()
    for l in ag:
        m = re.search(r"tool (\w+) completed", l)
        if m:
            tools_used[m.group(1)] += 1

    # 最近对话
    recent_msgs = []
    for l in gw:
        m = re.search(r"inbound message.*?user=\S+.*?msg='(.+)'", l)
        if m:
            ts = l[:19]
            msg = m.group(1)[:150]
            recent_msgs.append(f"`{ts}` {msg}")
    recent_msgs = recent_msgs[-12:]

    report = f"""## {username}

### 账号与容器

| 项目 | 值 |
|------|-----|
| 容器名 | `{cname}` |
| CPU | {stats.get('cpu','N/A')} |
| 内存 | {stats.get('mem','N/A')} |
| {days} 天 token | {total_tokens:,} |
| DB 用量记录 | {db_calls} 条 |

### 活跃概览

| 指标 | 值 |
|------|-----|
| 飞书收消息 | {inbound_count} 条 |
| 飞书发回复 | {response_count} 条 |
| Agent API 调用 | {api_calls} 次 |
| 平均响应时间 | {round(sum(resp_times)/len(resp_times),1) if resp_times else 0}s |
| 最长响应时间 | {max(resp_times) if resp_times else 0}s |

"""

    if tools_used:
        report += "### 工具使用\n\n| 工具 | 次数 |\n|------|------|\n"
        for tool, cnt in tools_used.most_common(10):
            report += f"| {tool} | {cnt} |\n"

    if recent_msgs:
        report += "\n### 最近对话\n\n"
        for msg in recent_msgs:
            report += f"- {msg}\n"

    if insights:
        report += "\n### 📊 业务洞察\n\n"
        for bi in insights:
            report += f"**{bi.title}**: {bi.summary}\n\n"
            if bi.detail:
                report += f"{bi.detail}\n\n"
            if bi.recommendation:
                report += f"→ {bi.recommendation}\n\n"

    if findings:
        report += "\n### 🔍 需要关注（技术层面）\n\n"
        for f in findings:
            report += f"""#### {f.severity} — {f.title}

**证据**
```
{f.evidence[:800]}
```

**影响**：{f.impact}

"""
            if f.fix:
                report += f"**修复方向**：{f.fix}\n\n"

    report += "---\n\n"
    return report


def _render_commands(user_data: list[dict]) -> str:
    report = "## 复查命令\n\n"
    for data in user_data:
        cname = data["container_name"]
        uid = data["username"]
        report += f"### {uid}\n\n"
        report += f"""```bash
# 容器健康
sudo docker exec {cname} curl -s http://127.0.0.1:18080/health

# 最近网关消息
sudo docker exec {cname} grep -E "inbound message|response ready" /opt/data/logs/gateway.log | tail -20

# 最近 agent 对话
sudo docker exec {cname} grep -E "conversation turn|API call|Turn ended" /opt/data/logs/agent.log | tail -20

# cron 状态
sudo docker exec {cname} grep -E "last_status|last_error|next_run" /opt/data/cron/jobs.json

# 错误
sudo docker exec {cname} tail -30 /opt/data/logs/errors.log
```

"""
    return report


# ═══════════════════════ Main ═══════════════════════


def main():
    parser = argparse.ArgumentParser(description="Hermes 用户日志深度分析 (baime OCA v2)")
    parser.add_argument("--user", help="指定用户 (username 或 email)")
    parser.add_argument("--all", action="store_true", help="分析所有 dedicated 用户")
    parser.add_argument("--days", type=int, default=7, help="分析天数 (默认 7)")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    if not args.user and not args.all:
        print("请指定 --user <用户名> 或 --all", file=sys.stderr)
        sys.exit(1)

    # ── Observe ──
    all_users_raw = psql("SELECT id, username, email, quota_tier, runtime_mode, role FROM users WHERE is_active=true")
    all_users = []
    for line in all_users_raw.split("\n"):
        parts = line.split("|")
        if len(parts) >= 6:
            all_users.append({
                "id": parts[0].strip(), "username": parts[1].strip(), "email": parts[2].strip(),
                "quota_tier": parts[3].strip(), "runtime_mode": parts[4].strip(), "role": parts[5].strip(),
            })

    if args.all:
        targets = [u for u in all_users if u.get("role") != "admin" and u.get("runtime_mode") == "dedicated"]
    else:
        targets = [u for u in all_users if args.user.lower() in u["username"].lower() or args.user == u["email"]]
        if not targets:
            print(f"未找到用户: {args.user}", file=sys.stderr)
            sys.exit(1)

    # 采集 + 分析
    user_data = []
    all_findings = {}
    for u in targets:
        data = collect_user_data(u["id"], u["username"], args.days)
        if data is None:
            print(f"⚠️  {u['username']}: 容器未运行，跳过", file=sys.stderr)
            user_data.append({"username": u["username"], "container_name": "N/A", "stats": {}, "gateway_log": [], "errors_log": [], "db_usage": ""})
            all_findings[u["username"]] = [
                Finding("容器状态", "P0", "容器未运行", "", "用户无法与 agent 对话", "sudo docker ps -a 查原因，必要时重建")
            ]
            continue
        user_data.append(data)
        findings = analyze_user(data, args.days)
        all_findings[u["username"]] = findings

    # ── 业务分析 ──
    all_insights = {}
    for data in user_data:
        uname = data["username"]
        if data.get("container_name") == "N/A":
            all_insights[uname] = []
            continue
        findings = all_findings.get(uname, [])
        insights = analyze_business(data, findings, args.days)
        all_insights[uname] = insights

    # ── Act ──
    if args.format == "json":
        output = {
            "generated_at": datetime.now().isoformat(),
            "days": args.days,
            "users": [{"username": d["username"], "user_id": d.get("uid", "")} for d in user_data],
            "findings": {
                d["username"]: [
                    {"severity": f.severity, "title": f.title, "evidence": f.evidence[:500], "impact": f.impact, "fix": f.fix}
                    for f in all_findings.get(d["username"], [])
                ]
                for d in user_data
            },
            "business_insights": {
                d["username"]: [
                    {"title": bi.title, "summary": bi.summary, "recommendation": bi.recommendation}
                    for bi in all_insights.get(d["username"], [])
                ]
                for d in user_data
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        report = generate_report(user_data, all_findings, all_insights, args.days)
        print(report)

        # 归档
        now = datetime.now()
        rp = report_path(now)
        scope = "all" if args.all else re.sub(r"[^a-zA-Z0-9._-]", "_", targets[0]["username"])
        filename = f"analysis-{now.strftime('%H%M')}-{scope}.md"
        filepath = rp / filename
        filepath.write_text(report, encoding="utf-8")
        print(f"\n📄 报告已归档: {filepath}", file=sys.stderr)


if __name__ == "__main__":
    main()

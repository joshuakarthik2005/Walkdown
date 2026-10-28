"""Work packages: grouping rules, combined fields, crew coverage, and the effect on the plan."""

from types import SimpleNamespace

from backend.agent import tools
from backend.agent.register import AssetInfo, Detection, RegisterEntry
from backend.clients.cost import CostLedger
from backend.planner.models import Crew, Defect, PlannerConfig
from backend.planner.packages import PackageConfig, build_packages, choose_view, package_of
from backend.verify.schema import Grade

CREWS = [Crew(id="C1", skills=["coating", "insulation"]), Crew(id="C3", skills=["mechanical", "welding"])]


def d(i, skill="coating", hours=3, sev=2, risk=0.2, permit=None, shutdown=False, asset="P-1"):
    return Defect(id=i, asset=asset, severity=sev, failure_risk=risk, repair_hours=hours, skill=skill,
                  permit=permit, needs_shutdown=shutdown)


def test_combined_fields():
    jobs = build_packages([d("W1", sev=3, risk=0.5), d("W2", risk=0.2), d("W3", skill="insulation", hours=4)],
                          {"W1": [0], "W2": [1], "W3": [2]}, CREWS)
    assert len(jobs) == 1
    p = jobs[0]
    assert p.id == "WP1" and p.members == ["W1", "W2", "W3"]
    assert p.severity == 3 and p.repair_hours == 3 + 3 + 4 - 2  # 1 h setup saved per extra member
    assert abs(p.failure_risk - (1 - 0.5 * 0.8 * 0.8)) < 1e-9
    assert p.skills == {"coating", "insulation"} and CREWS[0].can_do(p) and not CREWS[1].can_do(p)
    assert package_of(jobs) == {"W1": "WP1", "W2": "WP1", "W3": "WP1"}


def test_split_when_no_crew_has_all_skills_or_constraints_differ():
    jobs = build_packages([d("W1"), d("W2", skill="welding"), d("W3", shutdown=True), d("W4", asset="P-2"),
                           d("W5", permit="hot_work", skill="welding"), d("W6", permit="cold_work", skill="mechanical")],
                          {}, CREWS)
    groups = sorted(sorted(j.members or [j.id]) for j in jobs)
    # coating+welding: no crew has both; shutdown and other asset never mix; two different permits never mix
    assert ["W1", "W2"] not in groups and ["W1", "W3"] not in groups and ["W1", "W4"] not in groups
    assert not any({"W5", "W6"} <= set(g) for g in groups)
    assert any({"W2", "W5"} <= set(g) for g in groups)  # same skill, a permit-free job joins the hot-work job


def test_caps_and_frame_gap_and_single_defects_keep_their_id():
    jobs = build_packages([d(f"W{i}", hours=10) for i in range(4)], {}, CREWS)
    assert all(j.repair_hours <= 24 for j in jobs) and len(jobs) == 2
    near = build_packages([d("W1"), d("W2")], {"W1": [0], "W2": [50]}, CREWS, PackageConfig(max_frame_gap=10))
    assert [j.id for j in near] == ["W1", "W2"] and not near[0].members
    shut = build_packages([d("W1", hours=5, shutdown=True), d("W2", hours=5, shutdown=True)], {}, CREWS)
    assert len(shut) == 2  # shutdown packages are capped at one shift (8 h)
    assert build_packages([d("W1"), d("W2")], {}, CREWS, PackageConfig(enabled=False))[1].id == "W2"


def test_severe_defects_are_never_bundled():
    ds = [d("S1", sev=4, risk=0.6), d("S2", sev=5, risk=0.8), d("L1"), d("L2"), d("L3", sev=3)]
    jobs = build_packages(ds, {}, CREWS)
    for j in jobs:
        assert not (j.members and any(x.severity >= 4 for x in ds if x.id in j.members))
    assert {"S1", "S2"} <= {j.id for j in jobs}  # severe defects keep their own job and id


def test_bundling_a_severe_defect_would_delay_it_and_the_safeguard_prevents_that():
    """One coating crew: a severe 3 h job and two 6 h low-severity jobs on the same asset. If the severe defect
    were bundled, it would finish at the package end; kept single, it finishes exactly as without packages."""
    from backend.planner.cpsat import solve
    from backend.planner.models import PlannerConfig, Scenario
    from backend.planner.packages import unpack
    cfg = PlannerConfig(time_limit_s=10, num_workers=4)
    ds = [d("S1", sev=4, risk=0.6, hours=3), d("L1", hours=6), d("L2", hours=6)]
    sc = Scenario(name="t", horizon_days=3, defects=ds, crews=[CREWS[0]])

    def severe_end(cfg_pk: PackageConfig) -> int:
        jobs = build_packages(ds, {}, sc.crews, cfg_pk, planner=cfg)
        plan = solve(sc.model_copy(update={"defects": jobs}), cfg)
        assert plan.stats.status == "OPTIMAL"
        return {a.defect_id: a.end for a in unpack(jobs, plan.assignments)}["S1"]

    unpackaged = {a.defect_id: a.end for a in solve(sc, cfg).assignments}["S1"]
    assert severe_end(PackageConfig()) == unpackaged
    assert severe_end(PackageConfig(single_from_severity=6)) > unpackaged  # what the safeguard prevents


def _stats(status, gap):
    return SimpleNamespace(stats=SimpleNamespace(status=status, gap=gap))


def test_adaptive_rule_groups_only_when_individual_plan_is_not_proven():
    cfg = PackageConfig()
    assert choose_view(_stats("OPTIMAL", 0.0), _stats("OPTIMAL", 0.0), cfg)[0] == "individual"
    assert choose_view(_stats("FEASIBLE", 0.04), _stats("OPTIMAL", 0.0), cfg)[0] == "individual"
    assert choose_view(_stats("FEASIBLE", 0.57), _stats("OPTIMAL", 0.0), cfg)[0] == "grouped"
    assert choose_view(_stats("FEASIBLE", None), _stats("OPTIMAL", 0.0), cfg)[0] == "grouped"
    assert choose_view(_stats("FEASIBLE", 0.57), None, cfg)[0] == "individual"  # nothing to group
    assert choose_view(_stats("OPTIMAL", 0.0), _stats("OPTIMAL", 0.0), PackageConfig(mode="grouped"))[0] == "grouped"


def _grade(sev):
    return Grade.model_validate({"is_defect": True, "defect_type": "corrosion", "severity": sev, "confidence": 0.8,
                                 "recommended_action": "clean_and_recoat", "evidence": {"visual_cues": ["scale"],
                                 "location": "pipe", "extent": "small", "mask_fit": "good"}})


def test_session_solves_both_plans_and_replans_both():
    asset = AssetInfo(asset_id="P-101", asset_type="pipe", pressurised=True)
    reg = [RegisterEntry(f"W{i:02d}", asset, [Detection(f"c{i}", i, (0, 0, 5, 5), _grade(2))], False)
           for i in range(1, 5)]
    s = tools.AgentSession(clip=SimpleNamespace(), ledger=CostLedger(), base_scenario=tools.demo_backlog(2),
                           planner_config=PlannerConfig(time_limit_s=10))
    s.register = reg
    out = tools.plan_maintenance(s)
    assert set(s.variants) == {"individual", "grouped"}
    assert out["plan_view"] == "individual" and s.plan.stats.status == "OPTIMAL"  # small problem: proven
    assert {e.package_id for e in reg} == {e.defect_id for e in reg}  # individual view: own job ids
    cmp = tools.compare_views(s)
    assert cmp["grouped"]["jobs"] < cmp["individual"]["jobs"] and cmp["grouped"]["setup_hours_saved"] > 0
    tools._use_view(s, "grouped")
    assert {e.package_id for e in reg} == {"WP1"}
    tools._use_view(s, "individual")
    crew = s.base_scenario.crews[0].id
    tools.replan_tool(s, {"type": "crew_unavailable", "crew_id": crew, "start": 0, "end": 24}, now_hour=0)
    for v in s.variants.values():
        assert all(not (a.crew_id == crew and a.start < 24) for a in v["plan"].assignments)

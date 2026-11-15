"""W2 二次收口：C1/C2/C3 同一负例，对整改前/后源码各跑一次。

用法（整改前）：
  RKD_VERIFY_ROOT="var/evidence/roadmap/W2-二次收口/before-code" \
  ./.venv/Scripts/python.exe scripts/w2_second_closeout_repro.py --label before --out <dir>
用法（整改后）：
  ./.venv/Scripts/python.exe scripts/w2_second_closeout_repro.py --label after --out <dir>

只用隔离 SQLite + 真实回环 HTTP + 可控渲染桩；0 外部模型调用、0 密钥、0 费用。
竞态用确定性屏障（替换 _launch 在提交后/启动前插入一次真实 HTTP 读），不靠 sleep 碰运气。
期望值用解析手算给出，不拿另一条实现当标准答案。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("RKD_VERIFY_ROOT") or
            Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import w2_closeout_repro as base  # noqa: E402  复用隔离装配与 HTTP 夹具
from rkd_mvp.ai_spatial_outputs import build_cost, measure  # noqa: E402

CHECKS: list[dict] = []
ORG = base.ORG
MM2 = 1_000_000.0

TRIANGLE = [[0, 0], [6000, 0], [0, 6000]]          # 18.0 ㎡
TRI_HOLE = [[0, 1000], [6000, 1000], [6000, 2000], [0, 2000]]   # 与三角形交 4.5 ㎡


def record(cid: str, name: str, fn) -> None:
    try:
        ok, evidence = fn()
    except Exception as error:  # noqa: BLE001
        ok, evidence = False, {"error": f"{type(error).__name__}: {error}",
                               "trace": traceback.format_exc(limit=4).splitlines()[-4:]}
    CHECKS.append({"id": cid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


def get(path: str):
    return base.http("GET", path)


def wait_job(stack, job_id: str, timeout: float = 60.0):
    import time
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        code, data, _ = base.http("GET", f"{stack.base}/spatial-outputs?job_id={job_id}")
        last = data.get("job") or {}
        if last.get("job_id") != job_id:
            last = next((j for j in data.get("jobs") or [] if j["job_id"] == job_id), last)
        if last.get("status") in {"succeeded", "failed", "cancelled"}:
            return code, data, last
        time.sleep(0.02)
    raise AssertionError(f"等待任务超时：{job_id} 最后 {last.get('status')}")


# --------------------------------------------------------------- 解析手算工具
def triangle_rect_area(ax: float, ay: float, lx: float, ly: float,
                       rect: tuple[float, float, float, float]) -> float:
    """解析求「轴对齐直角三角形 ∩ 矩形」面积（mm²）。

    三角形：x>=ax, y>=ay, (x-ax)/lx + (y-ay)/ly <= 1（两条直角边分别沿 +x / +y）。
    矩形：(x0,y0,x1,y1)。只在斜边与矩形上下边相交的 x 处分段；段内被积函数线性，
    因此该分段积分是精确值，不是采样近似。
    """
    x0, y0, x1, y1 = rect
    low, high = max(x0, ax), min(x1, ax + lx)
    if high <= low:
        return 0.0
    lower = max(y0, ay)
    slope = ly / lx
    top_at = ax + lx                       # 斜边回到 y=ay 的 x
    upper = lambda x: ay + ly - (x - ax) * slope          # noqa: E731
    # 断点：斜边与矩形上边相交处、斜边低于矩形下边处（被积函数在此改斜率/归零）
    breaks = sorted({low, high,
                     *[b for b in (ax + lx * (ay + ly - y1) / ly,
                                   ax + lx * (ay + ly - lower) / ly,
                                   top_at) if low < b < high]})
    total = 0.0
    for a, b in zip(breaks, breaks[1:]):
        if b - a <= 0:
            continue
        mid = (a + b) / 2.0
        total += (b - a) * max(0.0, min(y1, upper(mid)) - lower)
    return total


def tri_scope(polygon_mm: list, material: str = "test-floor", **extra) -> dict:
    scope = {"kind": "material_face_slice", "declared_by": "w2c2_analytic_fixture",
             "declaration": "解析手算夹具，未经现场复核", "unit": "mm",
             "deduction_basis": "keepouts_within_scope",
             "areas": [{"object_id": "F1", "name": "解析三角材料面",
                        "polygon_mm": polygon_mm, "unit": "m2",
                        "material_ref": {"material_id": material, "name": "试验地坪"}}]}
    scope.update(extra)
    return scope


def tri_model(keepouts: list[dict], polygon_mm: list) -> dict:
    model = base.l_shape_model(keepouts)
    model["spatial"]["zones"][0]["polygon_mm"] = [list(p) for p in polygon_mm]
    model["spatial"]["zones"][0]["area_sqm"] = 18.0
    return model


# ------------------------------------------------------------------- C1 函数级
def c1_triangle_deduction():
    """C1：三角形 18㎡ 扣 4.5㎡ = 13.5㎡；主量/独立复算/饰面量/试算金额都要对。"""
    model = tri_model([base.keepout("cut", 0, 1, 6, 1)], TRIANGLE)
    qty = measure(model, finish_scope=tri_scope(TRIANGLE))
    geom = base.find_q(qty, "Q-FLOOR-GEOMETRIC-NET")
    finish = base.find_q(qty, "Q-FLOOR-FINISH")
    cost = build_cost(qty, settings={"floor_unit_price_cny": 1000})
    amount = (cost["known_items"][0]["amount_cny"] if cost["known_items"] else None)
    ok = (geom and abs(geom["value"] - 13.5) < 1e-6
          and abs((geom.get("independent_recompute_m2") or -1) - 13.5) < 1e-3
          and finish and finish.get("known_status") == "known"
          and abs((finish.get("value") or -1) - 13.5) < 1e-3
          and amount is not None and abs(amount - 13500.0) < 1.0)
    return ok, {
        "analytic_basis": "triangle 18 - ∫(6-y)dy[y=1..2]=4.5 -> 13.5㎡",
        "expected_m2": 13.5, "geometry_m2": (geom or {}).get("value"),
        "independent_m2": (geom or {}).get("independent_recompute_m2"),
        "finish_m2": (finish or {}).get("value"),
        "finish_status": (finish or {}).get("known_status"),
        "trial_amount_cny": amount, "expected_amount_cny": 13500.0}


def c1_slanted_crossing():
    """C1：扣除区斜穿斜边（x=2500..3500, y=2400..3400），净 18-0.595=17.405㎡。"""
    hole = base.keepout("X1", 2.5, 2.4, 1.0, 1.0)
    model = tri_model([hole], TRIANGLE)
    qty = measure(model, finish_scope=tri_scope(TRIANGLE))
    geom = base.find_q(qty, "Q-FLOOR-GEOMETRIC-NET")
    finish = base.find_q(qty, "Q-FLOOR-FINISH")
    ok = (geom and abs(geom["value"] - 17.405) < 1e-6
          and abs((geom.get("independent_recompute_m2") or -1) - 17.405) < 1e-3
          and finish and abs((finish.get("value") or -1) - 17.405) < 1e-3)
    return ok, {
        "analytic_basis": "毛 18㎡；扣除区 x∈[2500,3500],y∈[2400,3400] 被斜边切成两段，"
                          "∫2500..2600 1.0 dx + ∫2600..3500 (3.6-x/1000... 见 c1-handcheck.md) = 0.595㎡",
        "expected_m2": 17.405, "geometry_m2": (geom or {}).get("value"),
        "independent_m2": (geom or {}).get("independent_recompute_m2"),
        "finish_m2": (finish or {}).get("value"),
        "delta": (geom or {}).get("independent_delta_m2")}


def c1_rect_regression():
    """C1 回归：L 形 24㎡ 扣 2㎡ = 22㎡；矩形边与斜边无关，结果不得变。"""
    model = base.l_shape_model([base.keepout("K1", 1.0, 1.0, 1.0, 2.0)])
    qty = measure(model)
    gross = base.find_q(qty, "Q-FLOOR-GROSS")
    net = base.find_q(qty, "Q-FLOOR-GEOMETRIC-NET")
    ok = (gross and abs(gross["value"] - 24.0) < 1e-6
          and net and abs(net["value"] - 22.0) < 1e-6
          and abs((net.get("independent_recompute_m2") or -1) - 22.0) < 1e-3)
    return ok, {"gross": (gross or {}).get("value"), "net": (net or {}).get("value"),
                "independent": (net or {}).get("independent_recompute_m2")}


def c1_unit_contract():
    """C1：scope 坐标单位只收 mm、面积单位只收 m2；m/ft2 必须拒绝而不是照毫米算。"""
    model = tri_model([base.keepout("cut", 0, 1, 6, 1)], TRIANGLE)
    results = {}
    for name, mutate in (
            ("coord_unit_m", lambda s: s.update({"unit": "m"})),
            ("area_unit_ft2", lambda s: s["areas"][0].update({"unit": "ft2"})),
            ("unknown_deduction_basis", lambda s: s.update({"deduction_basis": "auto"})),
    ):
        scope = tri_scope(TRIANGLE)
        mutate(scope)
        try:
            qty = measure(model, finish_scope=scope)
            results[name] = {"rejected": False,
                             "finish": (base.find_q(qty, "Q-FLOOR-FINISH") or {}).get("value")}
        except ValueError as error:
            results[name] = {"rejected": True, "error": str(error)}
    return all(v.get("rejected") for v in results.values()), results


def c1_invalid_polygon():
    """C1：自交/退化/NaN/重复 object_id 必须拒绝，不能进计量。"""
    model = tri_model([], TRIANGLE)
    cases = {}
    bowtie = [[0, 0], [6000, 6000], [6000, 0], [0, 6000]]
    cases["self_intersection"] = tri_scope(bowtie)
    nan_scope = tri_scope(TRIANGLE)
    nan_scope["areas"][0]["polygon_mm"] = [[0, 0], [float("nan"), 0], [0, 6000]]
    cases["nan_coordinate"] = nan_scope
    dup = tri_scope(TRIANGLE)
    dup["areas"].append(copy.deepcopy(dup["areas"][0]))
    cases["duplicate_object_id"] = dup
    tiny = tri_scope([[0, 0], [10, 0], [0, 0]])
    cases["degenerate"] = tiny
    out = {}
    for name, scope in cases.items():
        try:
            measure(model, finish_scope=scope)
            out[name] = {"rejected": False}
        except ValueError as error:
            out[name] = {"rejected": True, "error": str(error)[:160]}
    return all(v.get("rejected") for v in out.values()), out


def c1_same_layer_overlap():
    """C1：同层重叠无说明必须拒绝；有说明时按并集算，不能各算一次相加。"""
    model = tri_model([], TRIANGLE)
    left = [[0, 0], [4000, 0], [0, 4000]]                    # 8.0 ㎡
    right = [[2000, 0], [6000, 0], [6000, 4000], [2000, 4000]]  # 16.0 ㎡
    shared = {"declared_by": "w2c2_analytic_fixture", "declaration": "叠层夹具",
              "unit": "mm", "deduction_basis": "none"}
    areas = [
        {"object_id": "A1", "polygon_mm": left, "layer": "floor_finish", "unit": "m2",
         "material_ref": {"material_id": "M1"}},
        {"object_id": "A2", "polygon_mm": right, "layer": "floor_finish", "unit": "m2",
         "material_ref": {"material_id": "M1"}},
    ]
    undeclared: dict
    try:
        measure(model, finish_scope={**shared, "areas": copy.deepcopy(areas)})
        undeclared = {"rejected": False}
    except ValueError as error:
        undeclared = {"rejected": True, "error": str(error)[:200]}
    declared_scope = {**shared, "areas": copy.deepcopy(areas),
                      "overlap_declaration": "两块材料面有意搭接 200mm，按并集计量不重复"}
    qty = measure(model, finish_scope=declared_scope)
    finish = base.find_q(qty, "Q-FLOOR-FINISH")
    # 并集：三角形(0,0)-(4,0)-(0,4) ∪ 三角形(2,0)-(6,0)-(6,4)... right 是矩形梯形，手算见下
    union_expected = 8.0 + 16.0 - _overlap_area(left, right)
    return (undeclared.get("rejected") is True
            and finish and abs((finish.get("value") or -1) - union_expected) < 1e-3), {
        "undeclared": undeclared,
        "union_expected_m2": round(union_expected, 4),
        "declared_value_m2": (finish or {}).get("value"),
        "note": "重叠声明后按并集算，不得 8+16=24 重复相加"}


def _overlap_area(left: list, right: list) -> float:
    """两块夹具多边形的重叠面积（解析，不调用被测实现）。

    left  = (0,0),(4000,0),(0,4000)            直角三角形，8㎡
    right = (2000,0),(6000,0),(6000,4000),(2000,4000)  矩形，16㎡
    重叠 = left 在 x>=2000 的部分 = ∫2000..4000 (4000-x)dx = 2㎡
    """
    del left, right  # 形状写死，仅用于自证解析式与夹具一致
    return triangle_rect_area(0, 0, 4000, 4000, (2000, 0, 6000, 4000)) / MM2


# ------------------------------------------------------------------- C1 真实入口
def _entry_case(stack, key: str, face: list, lx: float, ly: float) -> tuple[bool, dict]:
    """真实入口：声明一块三角材料面，跑完整 HTTP 链，比对解析值。

    期望值由「三角形 ∩ 每个保留区矩形」的解析积分给出，不拿被测实现当标准答案。
    """
    rev = stack.import_layout("A")
    stack.adopt(rev)
    detail = stack.options_ai.revision_by_id(ORG, stack.project_id,
                                             rev["option_revision_id"]) or {}
    model = detail.get("model") or {}
    obstacles = (model.get("boundary") or {}).get("obstacles") or []
    rects = []
    for item in obstacles:
        shape = item.get("shape") or {}
        x, y = float(shape["x"]) * 1000, float(shape["y"]) * 1000
        rects.append((item.get("object_id"), x, y,
                      x + float(shape["width"]) * 1000,
                      y + float(shape["length"]) * 1000))
    ax, ay = float(face[0][0]), float(face[0][1])
    deducted = sum(triangle_rect_area(ax, ay, lx, ly, r[1:]) for r in rects) / MM2
    face_area = 0.5 * lx * ly / MM2
    expected = face_area - deducted
    scope = tri_scope(face)
    code, gen, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                             {"option_revision_id": rev["option_revision_id"],
                              "settings": {"render": False, "finish_scope": scope,
                                           "floor_unit_price_cny": 1000}},
                             {"Idempotency-Key": key})
    if code not in (200, 202):
        return False, {"submit_status": code, "submit_body": gen}
    _, state, job = wait_job(stack, gen["item"]["job_id"])
    revision = state.get("revision") or {}
    if job.get("status") != "succeeded" or not revision:
        return False, {"job_status": job.get("status"), "error": job.get("error_code"),
                       "message": job.get("error_message")}
    finish = base.find_q(revision["quantities"], "Q-FLOOR-FINISH")
    cost = revision["cost"]
    rid = revision["production_revision_id"]
    csv_text = get(f"{stack.base}/spatial-outputs/{rid}/files/quantity.csv")[2].decode("utf-8")
    html = get(f"{stack.base}/spatial-outputs/{rid}/files/cost.html")[2].decode("utf-8")
    manifest = json.loads(get(f"{stack.base}/spatial-outputs/{rid}/files/manifest.json")[2])
    listed = [e["filename"] for e in manifest.get("files") or []]
    amount = (cost["known_items"][0]["amount_cny"] if cost["known_items"] else None)
    got = finish.get("value") if finish else None
    ok = (finish and finish.get("known_status") == "known"
          and got is not None and abs(got - expected) < 1e-3
          and amount is not None and abs(amount - round(expected * 1000, 2)) < 1.0
          and "Q-FLOOR-FINISH" in csv_text and str(round(expected, 3)) in csv_text
          and str(int(round(expected * 1000))) in html
          and "quantity.csv" in listed and "cost.html" in listed)
    return ok, {
        "obstacles": [{"object_id": r[0], "rect_mm": list(r[1:])} for r in rects],
        "face_mm": face, "face_area_m2": round(face_area, 4),
        "analytic_deduction_m2": round(deducted, 4),
        "expected_finish_m2": round(expected, 4),
        "finish": {"value": got, "status": (finish or {}).get("known_status"),
                   "groups": (finish or {}).get("material_groups")},
        "trial_amount_cny": amount,
        "expected_amount_cny": round(expected * 1000, 2),
        "csv_has_finish": "Q-FLOOR-FINISH" in csv_text,
        "html_has_amount": str(int(round(expected * 1000))) in html,
        "manifest_files": listed}


def c1_entry_architect(stack):
    """C1 真实入口（架构给的 13.5㎡/13500 元口径）：三角材料面跨卫生间保留区。"""
    face = [[19000, 2600], [25000, 2600], [19000, 8600]]
    ok, evidence = _entry_case(stack, "w2c2-c1-entry-0001", face, 6000.0, 6000.0)
    evidence["expected_fixed"] = "13.5 ㎡ / 13500 元（架构复核口径）"
    return ok, evidence


def c1_entry_partial_band(stack):
    """C1 真实入口（判别性）：保留区是竖直带，条带内被上下两处截断。

    面 (22000,0)-(26170,0)-(22000,8340)：毛 17.3889㎡；与卫生间保留区
    y∈[2600,7300] 的解析扣除 7.9665㎡ → 净 9.4224㎡。旧算法只切顶点 x，
    整个 x 区间按一个中点算成 6.5469㎡，饰面量与试算金额都跟着错。
    """
    face = [[22000, 0], [26170, 0], [22000, 8340]]
    return _entry_case(stack, "w2c2-c1-entry-band-0002", face, 4170.0, 8340.0)


# ------------------------------------------------------------------- C2 竞态
def c2_status_in_launch_gap(stack) -> tuple[bool, dict]:
    """C2：提交已提交、worker 尚未登记时，另一次真实 HTTP 状态查询不得终结任务。"""
    rev = stack.import_layout("A")
    stack.adopt(rev)
    original = stack.spatial_ai._launch
    seen: dict = {}

    def launch_after_read(org, project, job_id):
        code, data, _ = base.http("GET", f"{stack.base}/spatial-outputs?job_id={job_id}")
        job = data.get("job") or {}
        seen.update({"get_status": code, "status_in_gap": job.get("status"),
                     "error_in_gap": job.get("error_code"),
                     "revision_in_gap": (data.get("revision") or {}).get("production_revision_id")})
        original(org, project, job_id)

    stack.spatial_ai._launch = launch_after_read
    try:
        code, gen, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                                 {"option_revision_id": rev["option_revision_id"],
                                  "settings": {"render": False}},
                                 {"Idempotency-Key": "w2c2-c2-gap-0001"})
        job_id = gen["item"]["job_id"]
        _, _, job = wait_job(stack, job_id)
    finally:
        stack.spatial_ai._launch = original
    ok = (code in (200, 202) and seen.get("status_in_gap") in {"queued", "running"}
          and seen.get("error_in_gap") in (None, "")
          and job.get("status") == "succeeded")
    return ok, {"submit_status": code, **seen, "final_status": job.get("status"),
                "note": "没有重启；状态查询不得把刚提交的正常任务判成重启残留"}


def c2_cancel_in_gap(stack) -> tuple[bool, dict]:
    """C2：同一窗口内取消仍生效、不复活，且可显式重试。"""
    rev = stack.import_layout("B")
    stack.adopt(rev)
    original = stack.spatial_ai._launch
    seen: dict = {}

    def launch_after_read_and_cancel(org, project, job_id):
        code, data, _ = base.http("GET", f"{stack.base}/spatial-outputs?job_id={job_id}")
        seen["status_in_gap"] = (data.get("job") or {}).get("status")
        ccode, cdata, _ = base.http("POST", f"{stack.base}/spatial-outputs/{job_id}/cancel", {})
        seen["cancel_status"] = ccode
        seen["cancel_body_status"] = (cdata.get("item") or {}).get("status")
        original(org, project, job_id)

    stack.spatial_ai._launch = launch_after_read_and_cancel
    try:
        code, gen, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                                 {"option_revision_id": rev["option_revision_id"],
                                  "settings": {"render": False}},
                                 {"Idempotency-Key": "w2c2-c2-gapcancel-0001"})
        job_id = gen["item"]["job_id"]
        _, state, job = wait_job(stack, job_id)
    finally:
        stack.spatial_ai._launch = original
    registered = [r for r in state.get("revisions") or [] if r["job_id"] == job_id]
    rcode, retry, _ = base.http("POST", f"{stack.base}/spatial-outputs/{job_id}/retry",
                                {"settings": {"render": False}},
                                {"Idempotency-Key": "w2c2-c2-gapcancel-retry-0001"})
    retried = {}
    if rcode in (200, 202):
        _, _, retried = wait_job(stack, retry["item"]["job_id"])
    ok = (seen.get("cancel_status") == 200 and job.get("status") == "cancelled"
          and not registered and rcode in (200, 202)
          and retried.get("status") == "succeeded"
          and ((retry.get("item") or {}).get("config") or {}).get("retry_of") == job_id)
    return ok, {**seen, "final_status": job.get("status"),
                "registered": len(registered), "retry_status_code": rcode,
                "retried_status": retried.get("status"),
                "retry_of": ((retry.get("item") or {}).get("config") or {}).get("retry_of")}


def c2_restart_scope(stack) -> tuple[bool, dict]:
    """C2：真正遗留（上一实例）任务标中断；本实例在跑的不被误杀；其他类型不动。"""
    from rkd_mvp.models import new_id, now_iso
    rev = stack.import_layout("A")
    stack.adopt(rev)
    orphan = new_id("ai-spatial-job")
    foreign_dev = new_id("ai-development-job")
    with stack.dev_repo.transaction(ORG, stack.project_id, write=True) as tx:
        tx.insert_job({"job_id": orphan, "option_revision_id": rev["option_revision_id"],
                       "adoption_version": 0, "input_hash": "0" * 64, "status": "running",
                       "phase": "measurement", "attempt_count": 1, "settings": {},
                       "config": {"kind": "spatial_outputs",
                                  "run_instance": "spatial-worker-dead-000000000000"},
                       "error_code": None, "error_message": None,
                       "idempotency_key": f"orphan-{orphan}", "actor_id": "tool",
                       "created_at": now_iso(), "updated_at": now_iso()})
        tx.insert_job({"job_id": foreign_dev, "option_revision_id": rev["option_revision_id"],
                       "adoption_version": 0, "input_hash": "0" * 64, "status": "running",
                       "phase": "geometry", "attempt_count": 1, "settings": {},
                       "config": {"kind": "ai_development_production"},
                       "error_code": None, "error_message": None,
                       "idempotency_key": f"dev-{foreign_dev}", "actor_id": "tool",
                       "created_at": now_iso(), "updated_at": now_iso()})
    os.environ["RKD_STUB_RENDER_MODE"] = "wait"
    stack.gate.clear()
    stack.entered.clear()
    try:
        code, gen, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                                 {"option_revision_id": rev["option_revision_id"],
                                  "settings": {"render": True, "width": 320, "height": 240,
                                               "samples": 8}},
                                 {"Idempotency-Key": "w2c2-c2-live-0001"})
        live_id = gen["item"]["job_id"]
        if not stack.entered.wait(timeout=20):
            return False, {"stage": "render_not_entered", "job": live_id}
        recovered = stack.spatial_ai.recover(ORG, stack.project_id)
        code_live, data_live, _ = base.http(
            "GET", f"{stack.base}/spatial-outputs?job_id={live_id}")
        live_status = (data_live.get("job") or {}).get("status")
    finally:
        os.environ["RKD_STUB_RENDER_MODE"] = "fast"
        stack.gate.set()
    _, _, live_final = wait_job(stack, live_id)
    with stack.dev_repo.transaction(ORG, stack.project_id) as tx:
        orphan_job = tx.job(orphan)
        dev_job = tx.job(foreign_dev)
    ok = (live_id not in (recovered.get("recovered") or [])
          and live_status == "running" and live_final.get("status") == "succeeded"
          and orphan in (recovered.get("recovered") or [])
          and orphan_job and orphan_job["status"] == "failed"
          and orphan_job["error_code"] == "WORKER_RESTARTED"
          and dev_job and dev_job["status"] == "running")
    return ok, {"recovered": recovered.get("recovered"), "live_job": live_id,
                "live_status_during_recover": live_status,
                "live_final": live_final.get("status"),
                "orphan": {"id": orphan, "status": (orphan_job or {}).get("status"),
                           "error": (orphan_job or {}).get("error_code")},
                "other_kind": {"id": foreign_dev, "status": (dev_job or {}).get("status")},
                "instance_id": recovered.get("instance_id"),
                "note": "恢复以持久化的实例标记判定，不看内存 active 集合"}


# ------------------------------------------------------------------- C3 按 ID
def c3_explicit_isolated(stack) -> tuple[bool, dict]:
    """C3：显式查失败任务，不得借用另一个成功任务的 revision/artifacts。"""
    rev = stack.import_layout("A")
    stack.adopt(rev)
    _, good, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                           {"option_revision_id": rev["option_revision_id"],
                            "settings": {"render": False}},
                           {"Idempotency-Key": "w2c2-c3-good-0001"})
    good_id = good["item"]["job_id"]
    _, _, good_job = wait_job(stack, good_id)
    original = stack.spatial_ai.renderer

    def boom(*_a, **_k):
        raise RuntimeError("stub render failure")

    stack.spatial_ai.renderer = boom
    try:
        _, bad, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                              {"option_revision_id": rev["option_revision_id"],
                               "settings": {"render": True, "width": 320, "height": 240,
                                            "samples": 8}},
                              {"Idempotency-Key": "w2c2-c3-bad-0001"})
        bad_id = bad["item"]["job_id"]
        _, _, bad_job = wait_job(stack, bad_id)
    finally:
        stack.spatial_ai.renderer = original
    code, state, _ = base.http("GET", f"{stack.base}/spatial-outputs?job_id={bad_id}")
    revision = state.get("revision")
    artifacts = state.get("artifacts") or []
    ok = (good_job.get("status") == "succeeded" and bad_job.get("status") == "failed"
          and code == 200 and (state.get("job") or {}).get("job_id") == bad_id
          and revision is None and not artifacts)
    return ok, {"good_job": good_id, "requested_job": bad_id,
                "returned_job": (state.get("job") or {}).get("job_id"),
                "job_status": (state.get("job") or {}).get("status"),
                "returned_revision": (revision or {}).get("production_revision_id"),
                "returned_revision_job": (revision or {}).get("job_id"),
                "artifacts": len(artifacts), "revision_source": state.get("revision_source"),
                "note": "显式查一个失败任务时，revision/artifacts 必须为空，不能拿别人的"}


def c3_revision_lookup(stack) -> tuple[bool, dict]:
    """C3：按 production_revision_id 查，返回的 job 必须就是它的 job。"""
    rev = stack.import_layout("B")
    stack.adopt(rev)
    _, gen, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                          {"option_revision_id": rev["option_revision_id"],
                           "settings": {"render": False}},
                          {"Idempotency-Key": "w2c2-c3-rev-0001"})
    job_id = gen["item"]["job_id"]
    _, state, _ = wait_job(stack, job_id)
    revision = state.get("revision") or {}
    rid = revision.get("production_revision_id")
    # 再造一个更新的任务，确保"返回最新 job"会答错
    _, gen2, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                           {"option_revision_id": rev["option_revision_id"],
                            "settings": {"render": False}},
                           {"Idempotency-Key": "w2c2-c3-rev-0002"})
    wait_job(stack, gen2["item"]["job_id"])
    code, data, _ = base.http("GET",
                              f"{stack.base}/spatial-outputs?production_revision_id={rid}")
    returned = (data.get("revision") or {}).get("production_revision_id")
    ok = (rid is not None and code == 200 and returned == rid
          and (data.get("job") or {}).get("job_id") == job_id
          and (data.get("job") or {}).get("job_id") != gen2["item"]["job_id"])
    return ok, {"requested_revision": rid, "returned_revision": returned,
                "expected_job": job_id, "returned_job": (data.get("job") or {}).get("job_id"),
                "newer_job": gen2["item"]["job_id"]}


def c3_conflict_rejected(stack) -> tuple[bool, dict]:
    """C3：job_id 与 production_revision_id 同时给 → 明确拒绝。"""
    code, data, _ = base.http(
        "GET", f"{stack.base}/spatial-outputs?job_id=x&production_revision_id=y")
    return (code == 400 and data.get("error_code") == "AMBIGUOUS_QUERY"), {
        "status": code, "error_code": data.get("error_code"),
        "message": data.get("message")}


def c3_history_over_50(stack) -> tuple[bool, dict]:
    """C3：>50 条历史后，显式按 ID 仍要命中，不能被"最新 50 条"截断吃掉。"""
    rev = stack.import_layout("A")
    stack.adopt(rev)
    original = stack.spatial_ai.start_workers
    stack.spatial_ai.start_workers = False   # 同步执行：55 个任务逐条落库，避免并发噪声
    try:
        code, first, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                                   {"option_revision_id": rev["option_revision_id"],
                                    "settings": {"render": False}},
                                   {"Idempotency-Key": "w2c2-c3-history-0000"})
        target = first["item"]["job_id"]
        target_status = first["item"]["status"]
        for index in range(1, 55):
            base.http("POST", f"{stack.base}/spatial-outputs",
                      {"option_revision_id": rev["option_revision_id"],
                       "settings": {"render": False}},
                      {"Idempotency-Key": f"w2c2-c3-history-{index:04d}"})
    finally:
        stack.spatial_ai.start_workers = original
    code, state, _ = base.http("GET", f"{stack.base}/spatial-outputs?job_id={target}")
    revision = state.get("revision") or {}
    overview = base.http("GET", f"{stack.base}/spatial-outputs")[1]
    kinds = {(j.get("config") or {}).get("kind") for j in overview.get("jobs") or []}
    ok = (target_status == "succeeded" and code == 200
          and (state.get("job") or {}).get("job_id") == target
          and revision.get("job_id") == target
          and bool(state.get("artifacts"))
          and kinds in ({"spatial_outputs"}, set()))
    return ok, {"requested_job": target, "job_status_before_query": target_status,
                "query_status": code, "returned_job": (state.get("job") or {}).get("job_id"),
                "returned_revision_job": revision.get("job_id"),
                "artifacts": len(state.get("artifacts") or []),
                "overview_job_kinds": sorted(k for k in kinds if k),
                "note": "分页前按类型筛选；按 ID 直接查，不扫最新 50 条"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="after")
    parser.add_argument("--out", default=str(ROOT / "var/evidence/roadmap/W2-二次收口"))
    args = parser.parse_args()
    raw = Path(args.out)
    out_dir = raw if raw.is_absolute() else (ROOT / raw)
    out_dir.mkdir(parents=True, exist_ok=True)

    record("W2C2-C1-01", "三角形 18㎡ 扣 4.5㎡：主量/独立复算/饰面量 13.5㎡、试算 13500 元",
           c1_triangle_deduction)
    record("W2C2-C1-02", "扣除区斜穿斜边（交点 x=2600）：净 17.405㎡，两条路径一致",
           c1_slanted_crossing)
    record("W2C2-C1-03", "矩形/L 形回归：24/22 不变，独立复算一致", c1_rect_regression)
    record("W2C2-C1-04", "单位契约：scope 只收 mm/m2，m 与 ft2 必须拒绝", c1_unit_contract)
    record("W2C2-C1-05", "无效多边形：自交/NaN/重复 object_id/退化必须拒绝",
           c1_invalid_polygon)
    record("W2C2-C1-06", "同层材料面重叠：无声明拒绝；有声明按并集不重复相加",
           c1_same_layer_overlap)

    runtime = out_dir / f"runtime-{args.label}"
    stack = base.Stack(runtime)
    try:
        record("W2C2-C1-07", "真实入口（架构口径）：合法三角材料面 → 13.5㎡/13500 元，CSV/HTML/清单一致",
               lambda: c1_entry_architect(stack))
        record("W2C2-C1-08", "真实入口（判别性）：保留区竖直带内截断 → 9.4224㎡，旧算法 6.5469㎡",
               lambda: c1_entry_partial_band(stack))
        record("W2C2-C2-01", "提交后/启动前的真实 HTTP 状态查询不得终结正常任务",
               lambda: c2_status_in_launch_gap(stack))
        record("W2C2-C2-02", "同一窗口取消仍生效、不复活、可显式重试",
               lambda: c2_cancel_in_gap(stack))
        record("W2C2-C2-03", "真正遗留任务标中断；本实例在跑不被误杀；其他类型不受影响",
               lambda: c2_restart_scope(stack))
        record("W2C2-C3-01", "显式 job_id 只返回自己：失败任务不借用他人 revision/artifacts",
               lambda: c3_explicit_isolated(stack))
        record("W2C2-C3-02", "按 production_revision_id 查，返回的 job 必须对应它",
               lambda: c3_revision_lookup(stack))
        record("W2C2-C3-03", "job_id 与 production_revision_id 同时指定 → 明确拒绝",
               lambda: c3_conflict_rejected(stack))
        record("W2C2-C3-04", "超过 50 条历史仍能按 ID 命中（真实 HTTP）",
               lambda: c3_history_over_50(stack))
    finally:
        stack.close()

    failed = sum(1 for c in CHECKS if c["result"] != "observed_pass")
    payload = {
        "task_id": "W2-二次收口",
        "schema_version": "rkd-w2-second-closeout-checks.v1",
        "label": args.label,
        "source_root": str(ROOT),
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "environment": {"python": sys.version.split()[0],
                        "renderer": "controllable stub (no Blender in repro)",
                        "stack": "isolated SQLite + real loopback HTTP server",
                        "external_calls": 0, "keys_used": False},
        "checks": CHECKS,
        "totals": {"observed_pass": len(CHECKS) - failed, "observed_fail": failed},
        "external_calls": 0, "tokens": 0, "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
    }
    path = out_dir / f"repro-{args.label}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"label": args.label, "passed": len(CHECKS) - failed,
                      "failed": failed, "out": str(path)}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

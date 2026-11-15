# --no-render 报告语义修正

架构师独立运行 `verify_w2_r4.py --no-render` 曾得 12 pass / 3 fail（退出 1）。本批把图像项改为 `not_run`、缺前置证据改为 `missing_evidence`，两者都不计入产品失败；验证摘要按 function_level / contract / http / external_evidence / real_render / browser / manual_visual 分层。

在同一空目录复现结果：`{"observed_pass": 12, "observed_fail": 0, "not_run": 2, "missing_evidence": 1}`、退出码 0。完整渲染运行（本包 checks-source.json）为 15/15、0 not_run、0 缺证。

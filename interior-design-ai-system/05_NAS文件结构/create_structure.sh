#!/bin/bash
# 室内设计公司 NAS 目录一键创建脚本（fnOS / 通用 Linux）
# 用法：在共享文件夹"室内设计公司"根目录执行  bash create_structure.sh
set -e

mk() { mkdir -p "$1"; }

# 顶层
mk 00_公司知识库/01_流程与制度
mk 00_公司知识库/02_标准与规范
mk 00_公司知识库/03_培训与交接
mk 01_客户线索
mk 02_进行中项目
mk 03_已完成项目
mk 04_供应商库
mk 05_材料库
mk 06_模板库
mk 99_归档与备份/db
mk 99_归档与备份/n8n

# 项目子结构模板（新项目复制 PROJECT_TEMPLATE）
mk PROJECT_TEMPLATE/01_客户资料
mk PROJECT_TEMPLATE/02_现场测量
mk PROJECT_TEMPLATE/03_设计方案
mk PROJECT_TEMPLATE/04_效果图/_成片
mk PROJECT_TEMPLATE/04_效果图/_源文件
mk PROJECT_TEMPLATE/05_CAD施工图
mk PROJECT_TEMPLATE/06_报价与合同
mk PROJECT_TEMPLATE/07_材料与供应商
mk PROJECT_TEMPLATE/08_施工进度
mk PROJECT_TEMPLATE/09_变更与问题
mk PROJECT_TEMPLATE/10_验收与售后

# 使用说明
cat > PROJECT_TEMPLATE/_新项目说明.txt <<'EOF'
新项目建目录：复制本 PROJECT_TEMPLATE 文件夹，重命名为 项目编号_客户简称（如 HZ-26-001_某科技）。
命名规范见 00_公司知识库/01_流程与制度。
EOF

echo "目录结构创建完成。"

@echo off
rem 室内设计公司 NAS 目录一键创建脚本（Windows，在共享文件夹根目录执行）
chcp 65001 >nul
for %%d in (
  "00_公司知识库\01_流程与制度"
  "00_公司知识库\02_标准与规范"
  "00_公司知识库\03_培训与交接"
  "01_客户线索"
  "02_进行中项目"
  "03_已完成项目"
  "04_供应商库"
  "05_材料库"
  "06_模板库"
  "99_归档与备份\db"
  "99_归档与备份\n8n"
  "PROJECT_TEMPLATE\01_客户资料"
  "PROJECT_TEMPLATE\02_现场测量"
  "PROJECT_TEMPLATE\03_设计方案"
  "PROJECT_TEMPLATE\04_效果图\_成片"
  "PROJECT_TEMPLATE\04_效果图\_源文件"
  "PROJECT_TEMPLATE\05_CAD施工图"
  "PROJECT_TEMPLATE\06_报价与合同"
  "PROJECT_TEMPLATE\07_材料与供应商"
  "PROJECT_TEMPLATE\08_施工进度"
  "PROJECT_TEMPLATE\09_变更与问题"
  "PROJECT_TEMPLATE\10_验收与售后"
) do if not exist "%%~d" md "%%~d"
echo 目录结构创建完成。
pause

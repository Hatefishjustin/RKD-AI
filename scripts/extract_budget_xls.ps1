param(
    [string]$InputPath = "",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $InputPath) {
    $InputPath = Join-Path $Root "fixtures\ningbo-xiecheng\2026-09\source\20260721宁波协诚集团样品展厅装修预算.xls"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $Root "fixtures\ningbo-xiecheng\2026-09\derived\budget-source-extract.json"
}

$InputPath = (Resolve-Path -LiteralPath $InputPath).Path
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$culture = [Globalization.CultureInfo]::InvariantCulture

function Decimal-Text($value) {
    if ($null -eq $value -or [string]$value -eq "") { return $null }
    return [Convert]::ToString($value, $culture)
}

function Is-Number($value) {
    if ($null -eq $value) { return $false }
    $parsed = 0.0
    return [double]::TryParse([string]$value, [Globalization.NumberStyles]::Any, $culture, [ref]$parsed)
}

function Scope-Status([string]$section, [string]$name) {
    if ($section -eq "强电/弱电工程") {
        return @{ status = "excluded"; reason = "project_decision:mep" }
    }
    if ($name -match "消防") {
        return @{ status = "excluded"; reason = "project_decision:fire_protection" }
    }
    if ($name -match "吊灯|开关插座、灯具") {
        return @{ status = "excluded"; reason = "project_decision:mep" }
    }
    return @{ status = "included"; reason = $null }
}

$excel = $null
$book = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Open($InputPath, 0, $true)
    $lines = [Collections.Generic.List[object]]::new()

    $sheet = $book.Worksheets.Item("展厅")
    $section = ""
    for ($row = 3; $row -le 124; $row++) {
        $sequence = $sheet.Cells.Item($row, 1).Value2
        $name = [string]$sheet.Cells.Item($row, 2).Value2
        if ($sequence -and -not (Is-Number $sequence) -and $name -and $name -ne "小  计") {
            $section = $name.Trim()
            continue
        }
        if (-not (Is-Number $sequence) -or -not $name) { continue }
        $scope = Scope-Status $section $name
        $lines.Add([ordered]@{
            line_id = "xls-exhibition-r{0:d3}" -f $row
            category = "construction"
            section = $section
            sequence = [string]$sequence
            name = $name.Trim()
            unit = [string]$sheet.Cells.Item($row, 3).Value2
            quantity = Decimal-Text $sheet.Cells.Item($row, 4).Value2
            material_name = [string]$sheet.Cells.Item($row, 5).Value2
            main_material_unit_cost = Decimal-Text $sheet.Cells.Item($row, 6).Value2
            main_material_amount = Decimal-Text $sheet.Cells.Item($row, 7).Value2
            auxiliary_description = [string]$sheet.Cells.Item($row, 8).Value2
            auxiliary_unit_cost = Decimal-Text $sheet.Cells.Item($row, 9).Value2
            auxiliary_amount = Decimal-Text $sheet.Cells.Item($row, 10).Value2
            labor_unit_cost = Decimal-Text $sheet.Cells.Item($row, 11).Value2
            labor_amount = Decimal-Text $sheet.Cells.Item($row, 12).Value2
            inclusion_status = $scope.status
            exclusion_reason = $scope.reason
            source_scope_conflict = $false
            source_sheet = "展厅"
            source_row = $row
            source_locator = "展厅!A${row}:L${row}"
        })
    }

    $sheet = $book.Worksheets.Item("家具")
    $location = ""
    for ($row = 3; $row -le 8; $row++) {
        $sequence = $sheet.Cells.Item($row, 1).Value2
        $name = [string]$sheet.Cells.Item($row, 3).Value2
        if (-not (Is-Number $sequence) -or -not $name) { continue }
        $rowLocation = [string]$sheet.Cells.Item($row, 2).Value2
        if ($rowLocation) { $location = $rowLocation.Trim() }
        $description = [string]$sheet.Cells.Item($row, 6).Value2
        $lines.Add([ordered]@{
            line_id = "xls-furniture-r{0:d3}" -f $row
            category = "furniture"
            section = $(if ($location) { $location } else { "办公家具" })
            sequence = [string]$sequence
            name = $name.Trim()
            unit = [string]$sheet.Cells.Item($row, 8).Value2
            quantity = Decimal-Text $sheet.Cells.Item($row, 7).Value2
            material_name = $description
            main_material_unit_cost = Decimal-Text $sheet.Cells.Item($row, 9).Value2
            main_material_amount = Decimal-Text $sheet.Cells.Item($row, 10).Value2
            auxiliary_description = "尺寸：$([string]$sheet.Cells.Item($row, 5).Value2)"
            auxiliary_unit_cost = "0"
            auxiliary_amount = "0"
            labor_unit_cost = "0"
            labor_amount = "0"
            inclusion_status = "included"
            exclusion_reason = $null
            source_scope_conflict = $true
            source_sheet = "家具"
            source_row = $row
            source_locator = "家具!A${row}:J${row}"
        })
    }
    foreach ($row in @(10, 11)) {
        $name = [string]$sheet.Cells.Item($row, 3).Value2
        $amount = Decimal-Text $sheet.Cells.Item($row, 9).Value2
        if (-not $name -or $null -eq $amount) { continue }
        $lines.Add([ordered]@{
            line_id = "xls-furniture-r{0:d3}" -f $row
            category = "furniture"
            section = "办公家具附加费"
            sequence = [string]$sheet.Cells.Item($row, 1).Value2
            name = $name.Trim()
            unit = "项"
            quantity = "1"
            material_name = $name.Trim()
            main_material_unit_cost = $amount
            main_material_amount = $amount
            auxiliary_description = "源表家具汇总附加费"
            auxiliary_unit_cost = "0"
            auxiliary_amount = "0"
            labor_unit_cost = "0"
            labor_amount = "0"
            inclusion_status = "included"
            exclusion_reason = $null
            source_scope_conflict = $true
            source_sheet = "家具"
            source_row = $row
            source_locator = "家具!A${row}:J${row}"
        })
    }

    $summary = $book.Worksheets.Item("汇总")
    $payload = [ordered]@{
        schema_version = "rkd-budget-source-extract.v1"
        generated_at = [DateTimeOffset]::Now.ToString("o")
        source = [ordered]@{
            filename = [IO.Path]::GetFileName($InputPath)
            sha256 = (Get-FileHash -LiteralPath $InputPath -Algorithm SHA256).Hash
            asset_id = "estimate-xls-01"
            workbook_format = "xls"
        }
        source_summary = [ordered]@{
            base_direct_cost = Decimal-Text $summary.Cells.Item(4, 4).Value2
            main_material_cost = Decimal-Text $summary.Cells.Item(5, 4).Value2
            furniture_cost = Decimal-Text $summary.Cells.Item(6, 4).Value2
            source_total_before_tax = Decimal-Text $summary.Cells.Item(8, 4).Value2
            source_discounted_before_tax = Decimal-Text $summary.Cells.Item(9, 4).Value2
            source_tax_label = [string]$summary.Cells.Item(10, 2).Value2
            source_total_locator = "汇总!D8"
            source_discount_locator = "汇总!D9:E9"
        }
        source_notes = @(
            "源表汇总包含机电/消防/吊灯等与当前用户排除范围冲突的项目。",
            "源表优惠价标注不含税；用户当前确认的合同目标为含税 600000.00 元。",
            "家具汇总进入源表总价，但备注写明不含活动家具，保留来源冲突。"
        )
        lines = $lines
    }

    $directory = Split-Path -Parent $OutputPath
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding utf8NoBOM
    [pscustomobject]@{
        output = $OutputPath
        line_count = $lines.Count
        source_sha256 = $payload.source.sha256
        source_total_before_tax = $payload.source_summary.source_total_before_tax
    }
}
finally {
    if ($book) { $book.Close($false) }
    if ($excel) { $excel.Quit() }
    if ($book) { [Runtime.InteropServices.Marshal]::ReleaseComObject($book) | Out-Null }
    if ($excel) { [Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

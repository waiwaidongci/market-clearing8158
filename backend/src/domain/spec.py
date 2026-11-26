"""校园食堂餐券日终清分配置。"""

CAMPUS = "校园券账"
CANTEEN = "食堂核销账"
REDEEM = "核销"
PARTIAL = "部分退扣"
REVERSE = "全额冲正"
MAX_CENTS = 1_000_000_000_000
DEMO_DAY = "2026-11-20"
PRIOR_DAY = "2026-11-19"

SPEC = {
    "title": "校园食堂餐券双账结算",
    "short_name": "market-clearing",
    "subtitle": "按流水核对餐券核销与退扣，复核各校区和档口组的应结金额。",
    "organization": "青禾大学后勤餐饮中心，每日与东西两个校区的自营及合作档口结算餐券。",
    "workflow": (
        "校园卡中心导出餐券账，食堂收银系统导出核销账。后勤结算员原先用表格查流水并统计档口应结金额，"
        "现在将两份账合并为带来源列的 CSV，由系统逐笔核对。食堂值班员按流水回查原单，财务复核员"
        "使用勾稽表确认涉账校区和档口组后安排划款。"
    ),
    "pains": [
        "收银离线补传会导致一侧暂缺流水，汇总金额看不出缺的是哪张餐券。",
        "隔日退扣与整笔冲正需要追到原核销流水，单看金额很难发现扣错原单。",
        "两笔差额可能相互抵消，同额挂错校区也会影响档口结算。",
        "离线收银机时钟会漂移，凌晨核销按设备时间记账容易算错营业日。",
    ],
    "steps": [
        "11 月 20 日 20:30，合并校园卡中心和食堂收银记录，生成「青禾大学餐券双账_20261119-20.csv」，食堂核销账逐行带设备编号与设备时间。",
        "在「双账明细」导入 23 行，保留 11 月 19 日的三笔核销双账供隔日退扣回查。",
        "在「时钟校正」查看三台收银机的校时记录与挂起台账：C007 缺前置校时、C009 真实时间区间跨日、C010 缺后置校时，三笔先挂起。",
        "在「日终清分」选择 11 月 20 日，已归属流水与校园卡账合计 14 行、覆盖 8 个流水号；3 笔挂起食堂核销不计入当日清分。",
        "在「清分结果」查看 3 笔匹配、2 笔单边缺失、3 笔差异和 3 笔挂起；校园券账净额 3590 分，已归属食堂核销账净额 2350 分，时钟归属检查阻断。",
        "在「结算复核」按流水 C006 查补传，按 C008 核对校区归属，按 P002 核对退扣单据；挂起未解除时确认入账会被拒绝。",
        "改查 11 月 19 日，确认三笔原核销全部匹配，两账均为 2900 分，时钟归属与全部结算检查通过。",
        "在「时钟校正」补录贴近的校时后按最新校时重算，只重算受影响营业日；跨日改归属时原营业日与新营业日一起生效。",
        "在「结算交付」下载清分报告，将检查通过的批次交给财务。",
    ],
    "methodology": [
        "同一来源内流水号唯一，同一流水号可在两个来源各出现一次。按入账日选取流水，比较类型、原核销号、校区、档口组和金额。",
        "输入金额为大于零的整数分。净额等于核销金额减去部分退扣及全额冲正。隔日调整须在同一账内引用原核销，校区和档口组沿用原单。",
        "同一原单累计部分退扣须小于原金额。全额冲正最多一笔，金额等于扣除截至冲正日的部分退扣后所余金额，冲正日后禁止再退扣。",
        "各账按自身校区与档口组归集，交叉表分别与原始行计算的校区、档口组和全账合计勾稽。差额统一为校园券账减食堂核销账。",
        "存在入账记录、双账无缺失和差异且勾稽成立时才通过结算检查。单笔异常即使在汇总中抵消，仍会阻断结算。",
        "校园卡账沿用卡中心原日期；食堂核销账按设备时间记录，取前后两次校时的偏差夹出真实时间闭区间，偏差为标准时间减设备时间。",
        "食堂核销的真实时间区间整体落在同一北京时间自然日才归入该营业日清分；区间跨日或缺前/后校时依据的先挂起，不参与当日清分。",
        "校时记录允许乱序补录，补录后只重算受影响的营业日；跨日改归属时原营业日与新营业日的清分一起重算，重试不重复计账。",
    ],
    "sample_name": "青禾大学餐券双账_20261119-20.csv",
    "default_dataset": "青禾大学 11 月 19–20 日餐券双账",
    "entity": "餐券流水",
    "run": "日终清分",
    "decision": "结算复核",
    "action": "提交复核决定",
    "modes": ["确认入账", "退回补账", "暂缓结算"],
    "pages": ["结算总览", "双账明细", "时钟校正", "日终清分", "清分结果", "结算复核", "结算交付"],
    "fields": [
        {"key": "ledger", "label": "记账来源", "type": "select", "required": True, "options": [CAMPUS, CANTEEN]},
        {"key": "transaction_key", "label": "流水号", "type": "string", "required": True, "max_length": 100},
        {"key": "posting_date", "label": "入账日", "type": "date", "required": True},
        {"key": "zone", "label": "校区", "type": "string", "required": True, "max_length": 80},
        {"key": "merchant_group", "label": "档口组", "type": "string", "required": True, "max_length": 80},
        {"key": "kind", "label": "记账类型", "type": "select", "required": True, "options": [REDEEM, PARTIAL, REVERSE]},
        {"key": "original_key", "label": "原核销流水号", "type": "string", "required": False, "max_length": 100},
        {"key": "amount_cents", "label": "金额（分）", "type": "int", "required": True, "min": 1, "max": MAX_CENTS},
        # 仅食堂核销账需要：设备编号与设备时间，用于时钟漂移校正
        {"key": "device_id", "label": "收银设备编号", "type": "string", "required": False, "max_length": 80},
        {"key": "device_time", "label": "设备时间", "type": "datetime", "required": False, "max_length": 40},
    ],
    "clock_page": "时钟校正",
    "calibration_fields": [
        {"key": "device_id", "label": "收银设备编号", "type": "string", "required": True, "max_length": 80},
        {"key": "device_time", "label": "设备时间（带时区）", "type": "datetime", "required": True, "max_length": 40},
        {"key": "standard_time", "label": "标准时间（带时区）", "type": "datetime", "required": True, "max_length": 40},
    ],
    "params": [
        {"key": "posting_date", "label": "结算日", "type": "date", "required": True, "default": DEMO_DAY,
         "help": "按营业日清分。校园卡账用入账日，食堂核销账用校时夹出的真实营业日；挂起流水不参与当日清分。"},
    ],
    "fixture": {"posting_date": PRIOR_DAY},
    "axes": "横轴为逐笔核对状态，纵轴为流水号个数。",
}

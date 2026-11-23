"""处理时乱序缓冲（到达序匣）。

全局唯一架构口径：**以处理水位入匣为准**。
- 处理水位 = 已接纳事件（已开腿/已成对/已旁路）的最大处理时，跨批次持久化在「站规」。
- 事件时 > 处理水位 的刷卡（处理时早到、事件时仍在未来）不直接进主链路，先入到达序匣：
  入匣期间禁止开腿、禁止成对、禁止写开腿账/行程账。
- 后续装载把处理水位抬过匣内事件时后，按到达序（入匣先后）冲洗，重放主链路开腿/成对。
- 冲洗与出站成对共用状态机幂等：同一进站至多开一次腿、至多成对一次，绝不双配。

另一种口径「以事件时直配为准——到达即开腿/成对、永不写匣」不在本实现中出现；
本口径下到达瞬间该进站的可区分特征是：刷卡点命运=已入匣、到达序匣有匣行、开腿账无腿。
"""

from app.db import 连接
from app.seed import 水位键, 事件水位键, 此刻
from app.services import 时间

NAME = "处理时乱序缓冲"

# 匣态
在匣 = "在匣"
已冲洗 = "已冲洗"

# 刷卡点命运（匣内）
命_已入匣 = "已入匣"


def 取水位(conn) -> str | None:
    row = conn.execute("SELECT 值 FROM 站规 WHERE 键=?", (水位键,)).fetchone()
    return row["值"] if row else None


def 抬水位(conn, 处理时: str) -> None:
    """接纳一个事件后推进处理水位（单调不降）。"""
    旧 = 取水位(conn)
    if 旧 is None or 时间.解析(处理时) > 时间.解析(旧):
        conn.execute(
            "INSERT INTO 站规(键, 值) VALUES (?, ?) "
            "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
            (水位键, 处理时),
        )


def 取事件水位(conn) -> str | None:
    row = conn.execute("SELECT 值 FROM 站规 WHERE 键=?", (事件水位键,)).fetchone()
    return row["值"] if row else None


def 抬事件水位(conn, 事件时: str) -> None:
    """接纳事件的事件时推进事件水位（单调不降）；匣内未来事件不参与。"""
    旧 = 取事件水位(conn)
    if 旧 is None or 时间.解析(事件时) > 时间.解析(旧):
        conn.execute(
            "INSERT INTO 站规(键, 值) VALUES (?, ?) "
            "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
            (事件水位键, 事件时),
        )


def 须入匣(conn, 事件时: str, 处理时: str) -> bool:
    """处理时早到（处理时 < 事件时）且事件时仍在处理水位未来 → 入匣。

    - 水位尚未建立（首事件）直接接纳。
    - 处理时 >= 事件时 的事件并非来自未来：其到达本身证明时钟已越过该事件时，
      直接接纳并抬水位，顺便冲洗匣内更早的事件，避免永久卡死。
    """
    水位 = 取水位(conn)
    if 水位 is None:
        return False
    return (
        时间.解析(处理时) < 时间.解析(事件时)
        and 时间.解析(事件时) > 时间.解析(水位)
    )


def 入匣(conn, ev: dict, 批次编号: str) -> None:
    """事件进到达序匣：只写匣行 + 刷卡点置「已入匣」，不开腿、不成对。"""
    事件编号 = ev["事件编号"]
    卡号 = ev["卡号"]
    站点键 = ev["站点键"]
    方向 = ev["方向"]
    事件时 = ev["事件时"]
    处理时 = ev.get("处理时") or 此刻()
    序 = (
        conn.execute(
            "SELECT COALESCE(MAX(序), 0) + 1 AS n FROM 到达序匣"
        ).fetchone()["n"]
    )
    conn.execute(
        """INSERT INTO 到达序匣(事件编号,卡号,站点键,方向,事件时,处理时,入匣处理时,
           匣态,冲洗时刻,开腿结果,行程键,valid,批次编号,序)
           VALUES (?,?,?,?,?,?,?,'在匣','','','',1,?,?)""",
        (事件编号, 卡号, 站点键, 方向, 事件时, 处理时, 处理时, 批次编号, 序),
    )
    conn.execute(
        "UPDATE 刷卡点 SET 命运=? WHERE 事件编号=?",
        (命_已入匣, 事件编号),
    )


def 查匣(状态: str = "") -> list[dict]:
    """只读接口：事件编号、匣态、冲洗时刻、开腿结果、valid（含全部匣行）。"""
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 到达序匣 WHERE 匣态=? ORDER BY 序 ASC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 到达序匣 ORDER BY 序 ASC")
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 冲洗(conn, 接纳, 报告: dict) -> None:
    """处理水位追上后，按到达序冲洗匣内事件，重放主链路。

    接纳(conn, ev, 报告)：装载侧主链路回调，负责开腿/成对/旁路并推进水位。
    幂等：只捞 匣态='在匣' 且 事件时<=水位 的行；冲洗即翻 valid=0，任何重入都不会再捞。
    """
    水位 = 取水位(conn)
    if 水位 is None:
        return
    while True:
        行 = conn.execute(
            "SELECT * FROM 到达序匣 WHERE 匣态=? AND 事件时<=? ORDER BY 序 ASC LIMIT 1",
            (在匣, 水位),
        ).fetchone()
        if not 行:
            return
        ev = {
            "事件编号": 行["事件编号"],
            "卡号": 行["卡号"],
            "站点键": 行["站点键"],
            "方向": 行["方向"],
            "事件时": 行["事件时"],
            "处理时": 行["处理时"],
        }
        报告.setdefault("冲洗明细", []).append(
            {"事件编号": 行["事件编号"], "事件时": 行["事件时"]}
        )
        报告["冲洗"] = 报告.get("冲洗", 0) + 1

        # 先翻匣态（valid=0）再重放：即使下游重复调用，该进站也只会被处理一次。
        conn.execute(
            "UPDATE 到达序匣 SET 匣态=?, 冲洗时刻=?, valid=0 WHERE 事件编号=? AND 匣态=?",
            (已冲洗, 此刻(), 行["事件编号"], 在匣),
        )
        接纳(conn, ev, 报告, 来自匣=True)

        # 接纳回调可能推进水位，重新取。
        水位 = 取水位(conn)


def 回填冲洗结果(conn, 事件编号: str, 开腿结果: str, 行程键: str = "") -> None:
    """主链路处理完匣内事件后，把开腿/成对结果回写匣行（只读可核）。"""
    conn.execute(
        "UPDATE 到达序匣 SET 开腿结果=?, 行程键=? WHERE 事件编号=?",
        (开腿结果, 行程键, 事件编号),
    )

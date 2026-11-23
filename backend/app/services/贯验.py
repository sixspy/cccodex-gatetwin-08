from app.db import 连接
from app.seed import 此刻


def 跑贯验() -> dict:
    """行程账与刷卡点互证：每笔已成对行程对应两笔已成对刷卡；旁路/开腿命运自洽。"""
    conn = 连接()
    try:
        问题 = []
        刷卡数 = conn.execute("SELECT COUNT(*) FROM 刷卡点").fetchone()[0]
        行程 = conn.execute("SELECT * FROM 行程账 WHERE 状态='已成对'").fetchall()
        开腿数 = conn.execute("SELECT COUNT(*) FROM 开腿账 WHERE 状态='在途'").fetchone()[0]
        旁路数 = conn.execute("SELECT COUNT(*) FROM 旁路匣").fetchone()[0]

        for t in 行程:
            进 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (t["进站事件编号"],)
            ).fetchone()
            出 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (t["出站事件编号"],)
            ).fetchone()
            if not 进 or not 出:
                问题.append(f"行程{t['行程键']}缺刷卡点")
                continue
            if 进["命运"] != "已成对" or 出["命运"] != "已成对":
                问题.append(f"行程{t['行程键']}刷卡命运非已成对")
            if 进["行程键"] != t["行程键"] or 出["行程键"] != t["行程键"]:
                问题.append(f"行程{t['行程键']}刷卡行程键不一致")
            if 进["卡号"] != t["卡号"] or 出["卡号"] != t["卡号"]:
                问题.append(f"行程{t['行程键']}卡号不一致")
            if 进["方向"] != "进站" or 出["方向"] != "出站":
                问题.append(f"行程{t['行程键']}方向不配对")

        成对刷 = conn.execute(
            "SELECT COUNT(*) FROM 刷卡点 WHERE 命运='已成对'"
        ).fetchone()[0]
        if 成对刷 != len(行程) * 2:
            问题.append(f"已成对刷卡{成对刷} ≠ 行程{len(行程)}×2")

        开腿刷 = conn.execute(
            "SELECT COUNT(*) FROM 刷卡点 WHERE 命运='已开腿'"
        ).fetchone()[0]
        if 开腿刷 != 开腿数:
            问题.append(f"已开腿刷卡{开腿刷} ≠ 在途开腿{开腿数}")

        # —— 处理时乱序缓冲（到达序匣）互证 ——
        在匣 = conn.execute(
            "SELECT * FROM 到达序匣 WHERE 匣态='在匣'"
        ).fetchall()
        for b in 在匣:
            刷 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (b["事件编号"],)
            ).fetchone()
            if not 刷:
                问题.append(f"匣行{b['事件编号']}缺刷卡点")
                continue
            if 刷["命运"] != "已入匣":
                问题.append(f"在匣{b['事件编号']}刷卡命运应为已入匣，实为{刷['命运']}")
            if b["valid"] != 1:
                问题.append(f"在匣{b['事件编号']}valid应为1")
            # 入匣期间禁止开腿/成对
            腿 = conn.execute(
                "SELECT 1 FROM 开腿账 WHERE 进站事件编号=?", (b["事件编号"],)
            ).fetchone()
            if 腿:
                问题.append(f"在匣{b['事件编号']}竟已开腿")
            行 = conn.execute(
                "SELECT 1 FROM 行程账 WHERE 进站事件编号=? OR 出站事件编号=?",
                (b["事件编号"], b["事件编号"]),
            ).fetchone()
            if 行:
                问题.append(f"在匣{b['事件编号']}竟已成对")

        入匣刷 = conn.execute(
            "SELECT COUNT(*) FROM 刷卡点 WHERE 命运='已入匣'"
        ).fetchone()[0]
        if 入匣刷 != len(在匣):
            问题.append(f"已入匣刷卡{入匣刷} ≠ 在匣匣行{len(在匣)}")

        # 已冲洗匣行：valid=0，且刷卡点已离开「已入匣」命运，开腿结果非空
        冲 = conn.execute(
            "SELECT * FROM 到达序匣 WHERE 匣态='已冲洗'"
        ).fetchall()
        for b in 冲:
            if b["valid"] != 0:
                问题.append(f"已冲洗{b['事件编号']}valid应为0")
            if not b["冲洗时刻"]:
                问题.append(f"已冲洗{b['事件编号']}缺冲洗时刻")
            if not b["开腿结果"]:
                问题.append(f"已冲洗{b['事件编号']}缺开腿结果")
            刷 = conn.execute(
                "SELECT 命运 FROM 刷卡点 WHERE 事件编号=?", (b["事件编号"],)
            ).fetchone()
            if 刷 and 刷["命运"] == "已入匣":
                问题.append(f"已冲洗{b['事件编号']}刷卡仍停在已入匣")

        # 同一进站至多一笔在途/成对腿，行程账主键兜底之外再核刷卡成对不双配
        双配 = conn.execute(
            """SELECT 进站事件编号, COUNT(*) AS c FROM 行程账
               GROUP BY 进站事件编号 HAVING c > 1"""
        ).fetchall()
        for d in 双配:
            问题.append(f"进站{d['进站事件编号']}成对{d['c']}次（双配）")

        通过 = 1 if not 问题 else 0
        说明 = "行程账与刷卡点互证通过" if 通过 else "；".join(问题)[:800]
        conn.execute(
            """INSERT INTO 行程贯验(时刻,刷卡数,行程数,开腿数,旁路数,是否通过,说明)
               VALUES (?,?,?,?,?,?,?)""",
            (此刻(), 刷卡数, len(行程), 开腿数, 旁路数, 通过, 说明),
        )
        conn.commit()
        return {
            "是否通过": bool(通过),
            "刷卡数": 刷卡数,
            "行程数": len(行程),
            "开腿数": 开腿数,
            "旁路数": 旁路数,
            "说明": 说明,
            "问题": 问题,
        }
    finally:
        conn.close()

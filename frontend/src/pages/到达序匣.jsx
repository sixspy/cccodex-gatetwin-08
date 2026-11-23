import React, { useEffect, useState } from "react";
import { 取 } from "../api.js";

export default function 到达序匣() {
  const [行, 设行] = useState([]);
  const [讯, 设讯] = useState("");
  const 刷 = () =>
    取("/到达序匣").then((rs) => {
      设行(rs);
      const 在匣数 = rs.filter((r) => r.匣态 === "在匣").length;
      设讯(`共 ${rs.length} 匣行，在匣 ${在匣数}，已冲洗 ${rs.length - 在匣数}`);
    });
  useEffect(() => { 刷(); }, []);
  return (
    <div>
      <h1 className="题">到达序匣（处理时乱序缓冲）</h1>
      <p className="述">
        口径：以处理水位入匣为准——事件时晚于处理水位的刷卡先入匣，<strong>入匣期间禁止开腿/成对</strong>；
        水位追上后按到达序冲洗。只读：事件编号 / 匣态 / 冲洗时刻 / 开腿结果 / valid。
      </p>
      <div className="行">
        <button className="次" onClick={() => 取("/到达序匣?匣态=在匣").then(设行)}>只看在匣</button>
        <button className="次" onClick={() => 取("/到达序匣?匣态=已冲洗").then(设行)}>只看已冲洗</button>
        <button className="次" onClick={刷}>全部</button>
      </div>
      {讯 && <p className="讯">{讯}</p>}
      {!行.length ? <div className="空态">匣空。灌「乱序早到样例」制造在匣行。</div> : (
        <table>
          <thead>
            <tr>
              <th>序</th><th>事件编号</th><th>卡号</th><th>方向</th><th>事件时</th>
              <th>入匣处理时</th><th>匣态</th><th>冲洗时刻</th><th>开腿结果</th><th>valid</th>
            </tr>
          </thead>
          <tbody>
            {行.map((r) => (
              <tr key={r.事件编号}>
                <td>{r.序}</td><td>{r.事件编号}</td><td>{r.卡号}</td><td>{r.方向}</td>
                <td>{r.事件时}</td><td>{r.入匣处理时}</td>
                <td><span className={`徽章 ${r.匣态 === "在匣" ? "败" : "通"}`}>{r.匣态}</span></td>
                <td>{r.冲洗时刻 || "—"}</td><td>{r.开腿结果 || "—"}</td>
                <td>{r.valid}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

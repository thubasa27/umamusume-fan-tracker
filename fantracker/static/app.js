"use strict";

// ---------- 共通 ----------
const $ = (sel, root = document) => root.querySelector(sel);
const fmt = (n) => (n == null ? "" : Math.round(n).toLocaleString("ja-JP"));

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node[k] = v;
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

// null/undefined を除いた子要素の配列(DOM の append/replaceChildren は null を "null" と描画してしまう)
const kids = (...children) => children.flat().filter((c) => c != null);

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      const d = body.detail;
      msg = typeof d === "string" ? d : d && d.message ? d.message : JSON.stringify(d);
    } catch (_) { /* JSON でないエラー */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

// ---------- 保存(専用ウィンドウでは保存ダイアログ、ブラウザでは通常のダウンロード) ----------
let toastTimer;
function toast(text, isError = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = isError ? "err" : "";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
}

const nativeSave = () => window.pywebview && window.pywebview.api && window.pywebview.api.save_file;

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1]);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

async function saveBlob(name, blob) {
  const save = nativeSave();
  if (!save) {
    const url = URL.createObjectURL(blob);
    el("a", { href: url, download: name }).click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    return;
  }
  try {
    const res = await save(name, await blobToBase64(blob));
    if (res.saved) toast(`保存しました: ${res.path}`);
    else if (res.error) toast(res.error, true);
  } catch (e) {
    toast("保存に失敗しました: " + e, true);
  }
}

// ゲームの日替わり(AM 5:00)で集計日を求める。サーバー側(fantracker/dates.py)と同じ規則。
const DAY_START_HOUR = 5;
function businessDate(localDateTime) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(localDateTime || "");
  if (!m) return "";
  const ms = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) - DAY_START_HOUR * 3600e3;
  return new Date(ms).toISOString().slice(0, 10);
}
const toServerDateTime = (v) => (v.length === 16 ? v + ":00" : v);
const parseCount = (s) => Number(String(s).replace(/[,\s人]/g, ""));

// ---------- タブ ----------
const loaders = { import: () => {}, dashboard: loadDashboard, records: loadRecords };
document.querySelectorAll("nav button").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b === btn));
    for (const name of Object.keys(loaders)) $(`#tab-${name}`).hidden = name !== btn.dataset.tab;
    loaders[btn.dataset.tab]();
  })
);

// ---------- 取り込み ----------
const dropzone = $("#dropzone");
const fileInput = $("#file-input");
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") fileInput.click(); });
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("over"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("over"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("over");
  scanFiles([...e.dataTransfer.files]);
});
fileInput.addEventListener("change", () => { scanFiles([...fileInput.files]); fileInput.value = ""; });

let pendingItems = []; // {confirm(): Promise<boolean>, canBatch(): boolean}

async function scanFiles(files) {
  files = files.filter((f) => /\.(jpe?g|png)$/i.test(f.name));
  if (!files.length) return;
  $("#scan-status").textContent = `${files.length} 枚を読み取り中…`;
  $("#scan-actions").hidden = false;
  const fd = new FormData();
  for (const f of files) {
    fd.append("files", f);
    fd.append("last_modified_ms", String(f.lastModified));
  }
  try {
    const { results } = await api("/api/scan", { method: "POST", body: fd });
    const box = $("#scan-results");
    box.replaceChildren();
    pendingItems = results.map((r) => renderItem(r, box));
    $("#scan-status").textContent = `${results.length} 件を読み取りました。内容を確認して確定してください。`;
  } catch (e) {
    $("#scan-status").textContent = "読み取りに失敗しました: " + e.message;
  }
}

function renderItem(r, box) {
  const card = el("div", { class: "item" });
  box.append(card);
  const state = { confirm: async () => false, canBatch: () => false };
  card.append(el("div", { class: "name" }, r.filename));
  if (r.error) {
    card.append(el("div", { class: "err" }, r.error));
    return state;
  }
  card.replaceChildren(
    el("img", { src: `/api/images/${r.image_hash}/crop`, alt: "読み取り領域", onerror: (e) => e.target.remove() }),
    el("div", { class: "fields" }, el("div", { class: "name" }, r.filename))
  );
  const fields = $(".fields", card);

  if (r.duplicate_of) {
    fields.append(el("div", { class: "dim" }, `登録済みの画像です(記録 #${r.duplicate_of})。二重登録はされません。`));
    return state;
  }

  const valueInput = el("input", { type: "text", value: r.value == null ? "" : String(r.value), inputMode: "numeric" });
  const dtInput = el("input", { type: "datetime-local", value: r.captured_at ? r.captured_at.slice(0, 16) : "" });
  const dateLabel = el("span", { class: "dim" });
  const refreshDate = () => { dateLabel.textContent = dtInput.value ? `集計日 ${businessDate(dtInput.value)}(AM5:00 区切り)` : ""; };
  dtInput.addEventListener("input", refreshDate);
  refreshDate();
  const status = el("span");
  const btn = el("button", { class: "primary" }, "確定");

  fields.append(...kids(
    el("label", {}, "総獲得ファン数 ", valueInput, el("span", { class: "dim" }, ` 読み取り: ${r.text || "(なし)"}`)),
    el("label", {}, "撮影日時 ", dtInput, " ", dateLabel),
    r.warnings && r.warnings.length ? el("ul", { class: "warn" }, r.warnings.map((w) => el("li", {}, w))) : null,
    el("div", {}, btn, " ", status)
  ));

  let done = false;
  state.canBatch = () => !done && !(r.warnings && r.warnings.length) && r.value != null && !!dtInput.value;
  state.confirm = async () => {
    if (done) return true;
    const total = parseCount(valueInput.value);
    if (!Number.isInteger(total) || total <= 0) { status.className = "err"; status.textContent = "ファン数が数値ではありません"; return false; }
    if (!dtInput.value) { status.className = "err"; status.textContent = "撮影日時を入力してください"; return false; }
    const edited = total !== r.value || (r.captured_at || "").slice(0, 16) !== dtInput.value;
    try {
      await api("/api/records", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fan_total: total, captured_at: toServerDateTime(dtInput.value), filename: r.filename,
          image_hash: r.image_hash, manual: edited,
        }),
      });
      done = true;
      for (const x of [valueInput, dtInput, btn]) x.disabled = true;
      status.className = "ok"; status.textContent = "確定しました";
      return true;
    } catch (e) {
      status.className = "err"; status.textContent = e.message;
      return false;
    }
  };
  btn.addEventListener("click", state.confirm);
  return state;
}

$("#confirm-all").addEventListener("click", async () => {
  const targets = pendingItems.filter((p) => p.canBatch());
  let ok = 0;
  for (const t of targets) if (await t.confirm()) ok++;
  const rest = pendingItems.filter((p) => !p.canBatch()).length;
  $("#scan-status").textContent = `${ok} 件を確定しました。警告ありや登録済みなど ${rest} 件は個別に確認してください。`;
});

// ---------- ダッシュボード ----------
const whiteBackground = { // PNG ダウンロード時に背景が透明にならないようにする
  id: "whiteBackground",
  beforeDraw(chart) {
    const { ctx, width, height } = chart;
    ctx.save(); ctx.globalCompositeOperation = "destination-over";
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, width, height); ctx.restore();
  },
};
const charts = {};
function drawChart(id, config) {
  charts[id]?.destroy();
  charts[id] = new Chart($("#" + id), { ...config, plugins: [whiteBackground] });
}

function fillTable(table, head, rows) {
  table.replaceChildren(
    el("thead", {}, el("tr", {}, head.map((h, i) => el("th", { class: i === 0 ? "l" : "" }, h)))),
    el("tbody", {}, rows.map((cells) => el("tr", {}, cells.map((c, i) => el("td", { class: i === 0 || c.left ? "l" : "" }, c.left ? c.text : c)))))
  );
}

async function loadDashboard() {
  const interpolate = $("#interpolate").checked;
  const data = await api(`/api/summary?period=${$("#period").value}&interpolate=${interpolate}`);
  const s = data.series;
  $("#dash-empty").hidden = s.length > 0;
  $("#dash-body").hidden = s.length === 0;
  if (!s.length) return;

  const labels = s.map((x) => x.date);
  drawChart("chart-total", {
    type: "line",
    data: { labels, datasets: [{ label: "総獲得ファン数", data: s.map((x) => x.fan_total), borderColor: "#2e9d48", backgroundColor: "#2e9d48", tension: 0.1, pointRadius: 3 }] },
    options: { animation: false, scales: { y: { ticks: { callback: (v) => v.toLocaleString("ja-JP") } } } },
  });
  drawChart("chart-inc", {
    type: "bar",
    data: { labels, datasets: [{
      label: interpolate ? "日次増加量(欠損日は日割り)" : "日次増加量(欠損日は経過日数分の合計)",
      data: s.map((x) => x.increment),
      backgroundColor: s.map((x) => (x.interpolated ? "#a9d9b5" : x.days > 1 ? "#e0a030" : "#2e9d48")),
    }] },
    options: { animation: false, scales: { y: { ticks: { callback: (v) => v.toLocaleString("ja-JP") } } } },
  });

  const note = (x) => x.interpolated ? "補間" : x.days > 1 ? `${x.days}日分の合計` : "";
  fillTable($("#tbl-daily"), ["日付", "総獲得ファン数", "増加量", "備考"],
    [...s].reverse().map((x) => [x.date, fmt(x.fan_total), fmt(x.increment), { left: true, text: note(x) }]));
  const aggRows = (list) => [...list].reverse().map((a) => [a.period, fmt(a.sum), fmt(a.average_per_day), fmt(a.max), `${a.days}日`]);
  const aggHead = (p) => [p, "合計", "平均(1日あたり)", "最大の増加量", "対象日数"];
  fillTable($("#tbl-weekly"), aggHead("週(月曜日)"), aggRows(data.weekly));
  fillTable($("#tbl-monthly"), aggHead("月"), aggRows(data.monthly));
}
$("#period").addEventListener("change", loadDashboard);
$("#interpolate").addEventListener("change", loadDashboard);
document.querySelectorAll("button.dl").forEach((b) =>
  b.addEventListener("click", () => {
    const chart = charts[b.dataset.chart];
    if (!chart) return;
    chart.canvas.toBlob((blob) => blob && saveBlob(`${b.dataset.name}.png`, blob), "image/png");
  })
);

// ---------- 記録一覧 ----------
async function loadRecords() {
  const rows = await api(`/api/records?include_history=${$("#show-history").checked}`);
  const table = $("#tbl-records");
  table.replaceChildren(
    el("thead", {}, el("tr", {}, ["集計日", "撮影日時", "総獲得ファン数", "採用", "手修正", "ファイル名", ""].map((h, i) => el("th", { class: i === 0 || i === 5 ? "l" : "" }, h)))),
    el("tbody", {}, rows.map(recordRow))
  );
}

function recordRow(r) {
  const tr = el("tr", { class: r.adopted ? "" : "history" });
  const show = () => {
    tr.replaceChildren(
      el("td", { class: "l" }, r.business_date), el("td", {}, r.captured_at.replace("T", " ")),
      el("td", {}, fmt(r.fan_total)), el("td", {}, r.adopted ? "○" : "履歴"), el("td", {}, r.manual ? "○" : ""),
      el("td", { class: "l" }, r.filename || ""),
      el("td", {},
        el("button", { onclick: edit }, "編集"), " ",
        el("button", { onclick: remove }, "削除"))
    );
  };
  const edit = () => {
    const v = el("input", { type: "text", value: String(r.fan_total), size: 14 });
    const d = el("input", { type: "datetime-local", value: r.captured_at.slice(0, 16) });
    const msg = el("span", { class: "err" });
    tr.replaceChildren(
      el("td", { class: "l", colSpan: 2 }, d, " ", msg), el("td", {}, v), el("td", { colSpan: 3 }, ""),
      el("td", {},
        el("button", { class: "primary", onclick: async () => {
          const total = parseCount(v.value);
          if (!Number.isInteger(total) || total <= 0 || !d.value) { msg.textContent = "値を確認してください"; return; }
          const body = {};
          if (total !== r.fan_total) body.fan_total = total;
          if (d.value !== r.captured_at.slice(0, 16)) body.captured_at = toServerDateTime(d.value);
          try { if (Object.keys(body).length) await api(`/api/records/${r.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); loadRecords(); }
          catch (e) { msg.textContent = e.message; }
        } }, "保存"), " ", el("button", { onclick: show }, "キャンセル"))
    );
  };
  const remove = async () => {
    if (!confirm(`${r.business_date} の記録(${fmt(r.fan_total)})を削除しますか?`)) return;
    await api(`/api/records/${r.id}`, { method: "DELETE" });
    loadRecords();
  };
  show();
  return tr;
}
$("#show-history").addEventListener("change", loadRecords);

// 専用ウィンドウではダウンロードできないので、保存ダイアログ経由にする(ブラウザでは通常のリンクのまま)
$("#export-link").addEventListener("click", async (e) => {
  if (!nativeSave()) return;
  e.preventDefault();
  try {
    const res = await fetch("/api/export.csv");
    if (!res.ok) throw new Error(res.statusText);
    await saveBlob("fan_records.csv", await res.blob());
  } catch (err) {
    toast("CSV を取得できませんでした: " + err.message, true);
  }
});

$("#manual-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, msg = $("#manual-msg");
  const total = parseCount(f.fan_total.value);
  if (!Number.isInteger(total) || total <= 0) { msg.className = "err"; msg.textContent = "ファン数が数値ではありません"; return; }
  try {
    await api("/api/records", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fan_total: total, captured_at: toServerDateTime(f.captured_at.value) }) });
    msg.className = "ok"; msg.textContent = "追加しました"; f.fan_total.value = "";
    loadRecords();
  } catch (err) { msg.className = "err"; msg.textContent = err.message; }
});

// CSV インポート: まず report で衝突を確認し、重複する集計日があれば上書き/スキップを選ばせる
$("#csv-pick").addEventListener("click", () => $("#csv-input").click());
$("#csv-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const run = async (mode) => {
    const fd = new FormData();
    fd.append("file", file); fd.append("mode", mode);
    return api("/api/import/csv", { method: "POST", body: fd });
  };
  const panel = $("#csv-panel");
  panel.hidden = false;
  try {
    const rep = await run("report");
    const errs = rep.errors.length ? el("ul", { class: "warn" }, rep.errors.map((x) => el("li", {}, x))) : null;
    const finish = async (mode) => {
      const res = await run(mode);
      panel.replaceChildren(el("p", { class: "ok" },
        `取り込み ${res.imported} 件 / 画像重複で除外 ${res.skipped_duplicates} 件 / 集計日の重複で除外 ${res.skipped_conflicts} 件`));
      loadRecords();
    };
    if (!rep.rows) { panel.replaceChildren(...kids(el("p", { class: "err" }, "取り込める行がありません"), errs)); return; }
    const conflict = rep.conflict_dates.length
      ? el("p", {}, `集計日が既存の記録と重複: ${rep.conflict_dates.join(", ")}`) : el("p", {}, "重複はありません。");
    panel.replaceChildren(...kids(
      el("p", {}, `${rep.rows} 行を取り込めます(エラー ${rep.errors.length} 行)。`), errs, conflict,
      rep.conflict_dates.length ? el("button", { onclick: () => finish("overwrite") }, "重複は上書き") : null, " ",
      el("button", { class: "primary", onclick: () => finish("skip") }, rep.conflict_dates.length ? "重複はスキップして取り込む" : "取り込む"), " ",
      el("button", { onclick: () => { panel.hidden = true; } }, "キャンセル")
    ));
  } catch (err) {
    panel.replaceChildren(el("p", { class: "err" }, err.message));
  }
});

// ---------- 終了ボタン(ブラウザ表示のときだけ。専用ウィンドウは閉じれば終了する) ----------
api("/api/info").then((info) => {
  if (!info.can_shutdown) return;
  const btn = $("#quit");
  btn.hidden = false;
  btn.addEventListener("click", async () => {
    if (!confirm("アプリを終了しますか?")) return;
    try {
      await api("/api/shutdown", { method: "POST", headers: { "X-FanTracker": "1" } });
      document.body.replaceChildren(el("p", { style: "padding:24px" }, "終了しました。このタブは閉じてください。"));
    } catch (e) {
      toast("終了できませんでした: " + e.message, true);
    }
  });
}).catch(() => {});

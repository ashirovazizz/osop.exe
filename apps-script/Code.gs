/**
 * osop.exe: API ленты замечаний поверх Google Таблицы.
 *
 * Установка (один раз):
 *  1. Откройте таблицу с лентой → Расширения → Apps Script.
 *  2. Вставьте этот файл целиком вместо содержимого Code.gs, сохраните.
 *  3. Начать развёртывание → Новое развёртывание → тип «Веб-приложение».
 *     Запуск от имени: «Меня». Доступ: «Все» (Anyone).
 *  4. Разрешите доступ к таблице и скопируйте URL вида
 *     https://script.google.com/macros/s/…/exec
 *  5. Вставьте этот URL в index.html в константу SHEET_API.
 *
 * Таблица: первый лист, первая строка — заголовки
 * id | date | rpd | course | expert | round | comment | tags | fix | outcome | ts
 */

var COLS = ['id', 'date', 'rpd', 'course', 'expert', 'round', 'comment', 'tags', 'fix', 'outcome', 'ts'];
var LIMITS = { date: 10, rpd: 20, course: 200, expert: 120, comment: 8000, fix: 8000 };
var OUTCOMES = { wait: 1, ok: 1, bad: 1 };
var MAX_ROWS = 5000;

function sheet_() {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  if (sh.getLastRow() === 0) sh.appendRow(COLS);
  return sh;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function cell_(v, key) {
  if (v instanceof Date) return Utilities.formatDate(v, 'Europe/Moscow', 'yyyy-MM-dd');
  if (key === 'round' || key === 'ts') return Number(v) || 0;
  if (key === 'tags') return String(v || '').split(',').map(function (s) { return s.trim(); }).filter(function (s) { return /^R\d{1,2}$/.test(s); });
  return String(v === null || v === undefined ? '' : v);
}

function readAll_() {
  var sh = sheet_();
  var n = sh.getLastRow();
  if (n < 2) return [];
  var rows = sh.getRange(2, 1, n - 1, COLS.length).getValues();
  return rows.filter(function (r) { return r[0] !== ''; }).map(function (r) {
    var o = {};
    COLS.forEach(function (k, i) { o[k] = cell_(r[i], k); });
    return o;
  });
}

function clean_(raw, partial) {
  var out = {};
  Object.keys(LIMITS).forEach(function (k) {
    if (raw[k] !== undefined) out[k] = String(raw[k] || '').slice(0, LIMITS[k]).trim();
  });
  if (raw.round !== undefined) out.round = Math.max(1, Math.min(50, parseInt(raw.round, 10) || 1));
  if (raw.outcome !== undefined) {
    if (!OUTCOMES[raw.outcome]) throw new Error('outcome: wait | ok | bad');
    out.outcome = raw.outcome;
  }
  if (raw.tags !== undefined) {
    out.tags = (Array.isArray(raw.tags) ? raw.tags : []).filter(function (t) {
      return typeof t === 'string' && /^R\d{1,2}$/.test(t);
    }).slice(0, 12);
  }
  if (raw.ts !== undefined) out.ts = parseInt(raw.ts, 10) || Date.now();
  if (!partial) {
    if (!out.comment) throw new Error('нужен текст замечания (comment)');
    if (!out.outcome) out.outcome = 'wait';
    if (!out.round) out.round = 1;
    if (!out.tags) out.tags = [];
    if (out.fix === undefined) out.fix = '';
    if (!out.ts) out.ts = Date.now();
  }
  return out;
}

function toRow_(o) {
  return COLS.map(function (k) {
    if (k === 'tags') return (o.tags || []).join(',');
    // апостроф не даёт таблице превратить дату и id РПД в число или дату
    if (k === 'date' || k === 'rpd') return o[k] ? "'" + o[k] : '';
    return o[k] === undefined ? '' : o[k];
  });
}

function doGet() {
  return json_(readAll_());
}

/**
 * POST с телом text/plain (так браузер не делает preflight-запрос):
 *   {"action":"add", "doc":{...}}
 *   {"action":"update", "id":"…", "patch":{"fix":"…","outcome":"ok"}}
 */
function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var sh = sheet_();
    if (body.action === 'add') {
      if (sh.getLastRow() > MAX_ROWS) return json_({ error: 'лента переполнена' });
      var doc = clean_(body.doc || {}, false);
      doc.id = Utilities.getUuid().replace(/-/g, '').slice(0, 12);
      sh.appendRow(toRow_(doc));
      return json_({ ok: true, id: doc.id });
    }
    if (body.action === 'update') {
      var id = String(body.id || '');
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) return json_({ error: 'bad id' });
      var patch = clean_(body.patch || {}, true);
      var ids = sh.getRange(2, 1, Math.max(sh.getLastRow() - 1, 1), 1).getValues();
      for (var i = 0; i < ids.length; i++) {
        if (String(ids[i][0]) === id) {
          var row = i + 2;
          if (patch.fix !== undefined) sh.getRange(row, COLS.indexOf('fix') + 1).setValue(patch.fix);
          if (patch.outcome !== undefined) sh.getRange(row, COLS.indexOf('outcome') + 1).setValue(patch.outcome);
          return json_({ ok: true });
        }
      }
      return json_({ error: 'запись не найдена' });
    }
    return json_({ error: 'unknown action' });
  } catch (err) {
    return json_({ error: String(err && err.message || err) });
  } finally {
    lock.releaseLock();
  }
}

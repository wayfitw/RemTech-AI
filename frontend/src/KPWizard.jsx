// #45 (TASK-0507) — мастер КП-презентаций (PPTX) из 3 шагов:
//   1) загрузка документа поставщика → извлечение структуры (или пустой шаблон)
//   2) конструктор блоков: правка полей, строки характеристик, фото, drag-and-drop
//   3) генерация PPTX и скачивание
import { useEffect, useRef, useState } from "react";
import { api, downloadFile } from "./api.js";
import { toast } from "sonner";

const BLOCK_LABELS = {
  title: "Обложка", split: "Фото + характеристики", table: "Таблица",
  text: "Текст", photo: "Фото",
};
const uid = () => Math.random().toString(36).slice(2, 9);

// rows ↔ текст: "param | value" ; "# Раздел" → [Раздел, null] ; "item" → [item, ""]
function rowsToText(rows) {
  return (rows || [])
    .map((r) => (r[1] === null ? `# ${r[0]}` : r[1] ? `${r[0]} | ${r[1]}` : r[0] || ""))
    .join("\n");
}
// #53 — «сравнение моделей»: строка «XCMG XE215C | Мощность=118 кВт | Масса=21.5 т»
function textToMachines(text) {
  return (text || "").split("\n").map((line) => {
    const parts = line.split("|").map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return null;
    const specs = {};
    parts.slice(1).forEach((p) => {
      const i = p.indexOf("=");
      if (i > 0) specs[p.slice(0, i).trim()] = p.slice(i + 1).trim();
    });
    return { name: parts[0], specs };
  }).filter(Boolean);
}

// #53 — «КП на запчасти»: строка «803004555 | Фильтр масляный | 2 | 2 800 ₽ | склад»
function textToParts(text) {
  return (text || "").split("\n").map((line) => {
    const c = line.split("|").map((s) => s.trim());
    if (!c.filter(Boolean).length) return null;
    return { article: c[0] || "", name: c[1] || "", qty: c[2] || "",
             price: c[3] || "", availability: c[4] || "" };
  }).filter(Boolean);
}

function textToRows(text) {
  return (text || "").split("\n").map((line) => {
    const s = line.trim();
    if (!s) return null;
    if (s.startsWith("#")) return [s.slice(1).trim(), null];
    const i = s.indexOf("|");
    return i === -1 ? [s, ""] : [s.slice(0, i).trim(), s.slice(i + 1).trim()];
  }).filter(Boolean);
}

export default function KPWizard() {
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [meta, setMeta] = useState({
    name: "", brand: "", client_name: "", manager: "", phone: "",
    warranty: "", availability: "", price: "", payment_terms: "",
    markup_percent: "",          // #52 — наценка, пересчёт цены на бэкенде
    template: "standard",        // #53 — шаблон презентации
    machinesText: "",            // для шаблона «сравнение моделей»
    partsText: "",               // для шаблона «КП на запчасти»
  });
  const [blocks, setBlocks] = useState([]);
  const [result, setResult] = useState(null); // {file_id, name}
  const [history, setHistory] = useState([]); // #54 — последние 30 КП
  const [tgState, setTgState] = useState(null); // #55 — результат отправки в Telegram
  const dragFrom = useRef(null);

  const setField = (k, v) => setMeta((m) => ({ ...m, [k]: v }));

  useEffect(() => { loadHistory(); }, []);   // #54 — история при открытии мастера

  // нормализуем извлечённую/шаблонную структуру в редактируемые блоки
  function loadStructure(data) {
    setMeta((m) => ({
      ...m,
      name: data.name || "", brand: data.brand || "",
      warranty: data.warranty || "", availability: data.availability || "",
      price: data.price || "",
      payment_terms: (data.payment_terms || []).join("\n"),
    }));
    setBlocks((data.blocks || []).map((b) => ({
      _id: uid(), type: b.type || "text", title: b.title || "", text: b.text || "",
      rowsText: rowsToText(b.rows), image_id: null, image_name: "",
    })));
    setStep(2);
  }

  async function onExtract(file) {
    if (!file) return;
    setBusy(true);
    try {
      const data = await api.proposalExtract(file);
      loadStructure(data);
      toast.success("Структура извлечена — проверьте и поправьте блоки");
    } catch (e) {
      toast.error(e.message || "Не удалось извлечь");
    } finally {
      setBusy(false);
    }
  }

  function startBlank() {
    loadStructure({
      blocks: [
        { type: "title", title: "", text: "" },
        { type: "split", title: "Технические характеристики", rows: [] },
      ],
    });
  }

  const addBlock = (type) =>
    setBlocks((bs) => [...bs, { _id: uid(), type, title: "", text: "", rowsText: "", image_id: null, image_name: "" }]);
  const removeBlock = (id) => setBlocks((bs) => bs.filter((b) => b._id !== id));
  const patchBlock = (id, patch) =>
    setBlocks((bs) => bs.map((b) => (b._id === id ? { ...b, ...patch } : b)));

  function onDrop(id) {
    const from = dragFrom.current;
    dragFrom.current = null;
    if (from == null || from === id) return;
    setBlocks((bs) => {
      const arr = [...bs];
      const fi = arr.findIndex((b) => b._id === from);
      const ti = arr.findIndex((b) => b._id === id);
      if (fi === -1 || ti === -1) return bs;
      const [moved] = arr.splice(fi, 1);
      arr.splice(ti, 0, moved);
      return arr;
    });
  }

  async function onPhoto(id, file) {
    if (!file) return;
    try {
      const { image_id } = await api.proposalPhoto(file);
      patchBlock(id, { image_id, image_name: file.name });
      toast.success("Фото загружено");
    } catch (e) {
      toast.error(e.message || "Не удалось загрузить фото");
    }
  }

  // #54 — история последних 30 КП пользователя
  async function loadHistory() {
    try {
      setHistory(await api.proposalHistory());
    } catch {
      /* история не критична для работы мастера */
    }
  }

  async function useAsBase(id) {
    try {
      const { payload } = await api.proposalHistoryItem(id);
      loadStructure(payload || {});
      setMeta((m) => ({
        ...m,
        client_name: payload.client_name || "", manager: payload.manager || "",
        phone: payload.phone || "", template: payload.template || "standard",
        markup_percent: payload.markup_percent ?? "",
      }));
      toast.success("Данные прошлого КП загружены — правьте и генерируйте");
    } catch (e) {
      toast.error(e.message || "Не удалось загрузить КП");
    }
  }

  // #55 — отправка готового PPTX в Telegram через платформенный бот
  async function onSendTelegram() {
    if (!result?.file_id) return;
    setBusy(true);
    try {
      const r = await api.proposalSendTelegram(result.file_id);
      setTgState(r);
      if (r.sent) toast.success("Отправлено в Telegram");
      else toast.error(r.detail || "Файл слишком большой — скачайте по ссылке");
    } catch (e) {
      setTgState({ sent: false, detail: e.message });
      toast.error(e.message || "Не удалось отправить");
    } finally {
      setBusy(false);
    }
  }

  async function onGenerate() {
    if (!meta.name.trim()) {
      toast.error("Укажите модель техники (поле «Название»)");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        name: meta.name, brand: meta.brand, client_name: meta.client_name,
        manager: meta.manager, phone: meta.phone, warranty: meta.warranty,
        availability: meta.availability, price: meta.price,
        payment_terms: meta.payment_terms.split("\n").map((s) => s.trim()).filter(Boolean),
        filename: (meta.name || "КП").slice(0, 60),
        template: meta.template || "standard",
        blocks: blocks.map((b) => {
          const out = { type: b.type };
          if (b.title) out.title = b.title;
          if (b.text) out.text = b.text;
          if (b.type === "split" || b.type === "table") out.rows = textToRows(b.rowsText);
          if ((b.type === "split" || b.type === "photo") && b.image_id) out.image_id = b.image_id;
          return out;
        }),
      };
      // #52 — наценка: пересчёт делает бэкенд, сюда кладём только процент
      const markup = parseFloat(String(meta.markup_percent).replace(",", "."));
      if (!Number.isNaN(markup) && markup !== 0) payload.markup_percent = markup;
      // #53 — данные шаблонов
      if (meta.template === "comparison") payload.machines = textToMachines(meta.machinesText);
      if (meta.template === "parts") payload.parts = textToParts(meta.partsText);

      const r = await api.proposalGenerate(payload);
      setResult(r);
      setTgState(null);
      setStep(3);
      loadHistory();
      toast.success("КП-презентация готова");
    } catch (e) {
      toast.error(e.message || "Не удалось сгенерировать");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="kp-wrap">
      <div className="kp-steps">
        {[[1, "Документ"], [2, "Конструктор"], [3, "Готово"]].map(([n, label]) => (
          <div key={n} className={"kp-step" + (step === n ? " active" : "") + (step > n ? " done" : "")}>
            <span className="kp-step-n">{n}</span>{label}
          </div>
        ))}
      </div>

      {step === 1 && (
        <div className="kp-card kp-upload">
          <h2>КП-презентация на технику</h2>
          <p className="muted">
            Загрузите документ поставщика (PDF/DOCX) — ИИ извлечёт характеристики и структуру
            слайдов. Данные можно будет поправить перед генерацией.
          </p>
          <label className={"kp-file" + (busy ? " busy" : "")}>
            <i className="ti ti-upload" />
            {busy ? "Извлечение…" : "Выбрать документ поставщика"}
            <input type="file" accept=".pdf,.docx,.doc,.xlsx,.txt" hidden disabled={busy}
                   onChange={(e) => onExtract(e.target.files?.[0])} />
          </label>
          <button className="kp-link" onClick={startBlank} disabled={busy}>
            или начать с пустого шаблона
          </button>

          {history.length > 0 && (
            <div className="kp-history">
              <h3>Последние КП</h3>
              {history.map((h) => (
                <div key={h.id} className="kp-history-row">
                  <span className="kp-history-main">
                    <b>{h.machine || h.name}</b>
                    {h.client_name ? <span className="muted"> · {h.client_name}</span> : null}
                  </span>
                  <span className="muted kp-history-date">
                    {(h.created_at || "").slice(0, 10)}
                  </span>
                  {h.file_id && (
                    <button className="kp-history-btn" title="Скачать"
                            onClick={() => downloadFile(h.file_id, h.name)}>
                      <i className="ti ti-download" />
                    </button>
                  )}
                  <button className="kp-history-btn" title="Взять за основу"
                          onClick={() => useAsBase(h.id)}>
                    <i className="ti ti-copy" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {step === 2 && (
        <div className="kp-editor">
          <div className="kp-card">
            <h3>Общие данные</h3>
            <div className="kp-grid">
              <Field label="Название техники *" v={meta.name} on={(v) => setField("name", v)} />
              <Field label="Бренд" v={meta.brand} on={(v) => setField("brand", v)} />
              <Field label="Клиент (кому)" v={meta.client_name} on={(v) => setField("client_name", v)} />
              <Field label="Менеджер" v={meta.manager} on={(v) => setField("manager", v)} />
              <Field label="Телефон" v={meta.phone} on={(v) => setField("phone", v)} />
              <Field label="Базовая цена" v={meta.price} on={(v) => setField("price", v)} />
              <Field label="Наценка, %" v={meta.markup_percent}
                     on={(v) => setField("markup_percent", v)} />
              <Field label="Гарантия" v={meta.warranty} on={(v) => setField("warranty", v)} />
              <Field label="Наличие / срок" v={meta.availability} on={(v) => setField("availability", v)} />
            </div>
            <label className="kp-field">
              <span>Шаблон презентации</span>
              <select value={meta.template} onChange={(e) => setField("template", e.target.value)}>
                <option value="standard">Стандартное КП на технику</option>
                <option value="comparison">Сравнение моделей</option>
                <option value="parts">КП на запчасти</option>
              </select>
            </label>
            {meta.template === "comparison" && (
              <Field area label={'Модели для сравнения — строка на модель: «XCMG XE215C | Мощность=118 кВт | Масса=21.5 т»'}
                     v={meta.machinesText} on={(v) => setField("machinesText", v)} />
            )}
            {meta.template === "parts" && (
              <Field area label={'Позиции — строка на запчасть: «803004555 | Фильтр масляный | 2 | 2 800 ₽ | склад»'}
                     v={meta.partsText} on={(v) => setField("partsText", v)} />
            )}
            <Field label="Условия оплаты (по строке на пункт)" area
                   v={meta.payment_terms} on={(v) => setField("payment_terms", v)} />
            {meta.markup_percent ? (
              <p className="muted kp-hint">
                Цена в презентации будет пересчитана с наценкой {meta.markup_percent}% —
                расчёт выполняется на сервере.
              </p>
            ) : null}
          </div>

          <div className="kp-blocks">
            <h3>Слайды <span className="muted">— перетаскивайте за ⠿ для порядка</span></h3>
            {blocks.map((b) => (
              <div key={b._id} className="kp-block" draggable
                   onDragStart={() => (dragFrom.current = b._id)}
                   onDragOver={(e) => e.preventDefault()}
                   onDrop={() => onDrop(b._id)}>
                <div className="kp-block-head">
                  <span className="kp-drag" title="Перетащить">⠿</span>
                  <span className="kp-badge">{BLOCK_LABELS[b.type] || b.type}</span>
                  <button className="kp-x" onClick={() => removeBlock(b._id)} title="Удалить">
                    <i className="ti ti-trash" />
                  </button>
                </div>
                {b.type !== "title" && (
                  <Field label="Заголовок слайда" v={b.title} on={(v) => patchBlock(b._id, { title: v })} />
                )}
                {b.type === "title" && (
                  <>
                    <Field label="Заголовок (модель)" v={b.title} on={(v) => patchBlock(b._id, { title: v })} />
                    <Field label="Подпись (характеристики одной строкой)" v={b.text}
                           on={(v) => patchBlock(b._id, { text: v })} />
                  </>
                )}
                {b.type === "text" && (
                  <Field label="Текст" area v={b.text} on={(v) => patchBlock(b._id, { text: v })} />
                )}
                {(b.type === "split" || b.type === "table") && (
                  <Field label={'Строки: «параметр | значение», раздел — «# Название», пункт — просто текст'}
                         area v={b.rowsText} on={(v) => patchBlock(b._id, { rowsText: v })} />
                )}
                {(b.type === "split" || b.type === "photo") && (
                  <label className="kp-photo">
                    <i className="ti ti-photo" />
                    {b.image_name ? `Фото: ${b.image_name}` : "Загрузить фото техники"}
                    <input type="file" accept="image/*" hidden
                           onChange={(e) => onPhoto(b._id, e.target.files?.[0])} />
                  </label>
                )}
              </div>
            ))}
            <div className="kp-add">
              {Object.entries(BLOCK_LABELS).filter(([t]) => t !== "title").map(([t, label]) => (
                <button key={t} onClick={() => addBlock(t)}><i className="ti ti-plus" />{label}</button>
              ))}
            </div>
          </div>

          <div className="kp-actions">
            <button className="kp-secondary" onClick={() => setStep(1)}>← Назад</button>
            <button className="kp-primary" onClick={onGenerate} disabled={busy}>
              {busy ? "Генерация…" : "Сгенерировать PPTX"} <i className="ti ti-file-download" />
            </button>
          </div>
        </div>
      )}

      {step === 3 && result && (
        <div className="kp-card kp-done">
          <i className="ti ti-circle-check kp-done-ico" />
          <h2>КП-презентация готова</h2>
          <p className="muted">{result.name}</p>
          <button className="kp-primary" onClick={() => downloadFile(result.file_id, result.name)}>
            <i className="ti ti-download" /> Скачать PPTX
          </button>
          <button className="kp-secondary kp-tg" onClick={onSendTelegram} disabled={busy}>
            <i className="ti ti-brand-telegram" /> {busy ? "Отправка…" : "Отправить в Telegram"}
          </button>
          {tgState && (
            <p className={"kp-tg-state" + (tgState.sent ? " ok" : "")}>
              {tgState.sent
                ? "✓ Отправлено в Telegram"
                : (tgState.detail || "Не удалось отправить")}
              {tgState.reason === "too_large" && (
                <button className="kp-link"
                        onClick={() => downloadFile(result.file_id, result.name)}>
                  скачать файл
                </button>
              )}
            </p>
          )}
          <button className="kp-link" onClick={() => setStep(2)}>← вернуться к правке</button>
          <button className="kp-link" onClick={() => { setBlocks([]); setResult(null); setTgState(null); setStep(1); }}>
            создать новое КП
          </button>
        </div>
      )}
    </div>
  );
}

function Field({ label, v, on, area }) {
  return (
    <label className="kp-field">
      <span>{label}</span>
      {area
        ? <textarea rows={4} value={v} onChange={(e) => on(e.target.value)} />
        : <input value={v} onChange={(e) => on(e.target.value)} />}
    </label>
  );
}
